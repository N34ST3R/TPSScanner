# Architecture

A deep dive into how TPS Scanner is put together: the async data pipeline, caching,
rate limiting, and the top-trader engine. Written for anyone who wants to extend the
codebase.

---

## 1. High-level view

The app is a single Python process running several cooperating async subsystems:

```
                    ┌──────────────────────────────────────────────┐
                    │               asyncio event loop             │
                    │                                              │
   Browser ───────► │  Quart app (src/delivery/dashboard.py)       │
   (SPA on :5000)   │      REST API  /api/...                      │
                    │           │                                   │
                    │  live data layer (src/data/live/)            │
                    │      httpx.AsyncClient + yfinance (threads)  │
                    │           │                                   │
                    │  caching + rate limiting + SQLite (aiosqlite)│
                    │           │                                   │
                    │  background tasks:                            │
                    │    background_scanner (5 min)                 │
                    │    top-trader scheduler (30 min + settle)     │
                    │    MCP server (:8001)                         │
                    └──────────────────────────────────────────────┘
```

Every subsystem is event-driven and non-blocking. The only synchronous work
(yfinance, TA-Lib scans) runs on a thread pool so the event loop never stalls.

---

## 2. Async foundations

The whole stack is built around a single `asyncio` event loop.

### 2.1 Quart (async web framework)

`src/delivery/dashboard.py` creates the `Quart` app and serves the SPA plus ~40 REST
endpoints. Handlers are `async def`, so a slow upstream call never blocks other
requests. The template is rendered once and cached by Quart after the first request;
a code change to `templates/index.html` requires a server restart to appear.

### 2.2 aiosqlite (async SQLite)

`src/store/database.py` opens the main DB at `data/scanner.db` once
(`PRAGMA journal_mode=WAL`), then shares the single connection. Tables: `watchlist`,
`signals`, `alerts`, `paper_trades`, `signal_log`. The top-trader engine has its own
DB at `data/toptraders.db` (`src/toptraders/store.py`). WAL mode lets readers proceed
while the background scanner writes.

### 2.3 httpx.AsyncClient for live HTTP

All live modules (`src/data/live/*.py`) use `httpx.AsyncClient` with short timeouts
(10 to 15 s). A module-level helper pattern:

```python
async with httpx.AsyncClient(timeout=10) as client:
    resp = await client.get(url, params=...)
```

The client is created per request. That is fine at the current request rate and
keeps connection state simple.

### 2.4 yfinance in the thread pool

`yfinance` is synchronous. Two call sites wrap it:

- `src/data/fetcher.py` uses
  `asyncio.get_event_loop().run_in_executor(None, _fetch)`.
- `src/toptraders/outcomes.py` uses `asyncio.to_thread(_fetch)`.

`asyncio.to_thread` is the modern equivalent and the one to use for new code.

### 2.5 asyncio.gather for parallelism

Batch jobs fan out with `asyncio.gather(..., return_exceptions=True)` so one failing
symbol or feed does not kill the batch:

- `fetch_watchlist` fetches OHLCV for every watchlist symbol in parallel.
- `fetch_news` fetches all ~20 feeds concurrently.
- The collector runs each trader adapter sequentially but fetches profiles per
  adapter.

Callers then filter `isinstance(r, Exception)` before using results.

### 2.6 asyncio.create_task for background work

`src/main.py` starts four tasks with `create_task`:

1. `background_scanner` (infinite loop, 5 minute cadence).
2. `_first_scan` (one warm-up scan ~12 s after boot so the dashboard has data
   quickly).
3. `run_dashboard` (Quart on port 5000).
4. `run_tt_scheduler` (top-trader engine, see section 5).

The manual "Collect now" endpoint also spawns a one-shot task via
`asyncio.create_task(_run_collect())`.

---

## 3. The async data pipeline

### 3.1 The live data layer

Each data domain lives in `src/data/live/` and exposes one async `fetch_*` function:

| Module | Function | Source |
|--------|----------|--------|
| `markets.py` | `fetch_indices`, `fetch_commodities`, `fetch_forex`, `fetch_movers`, `fetch_fear_greed` | yfinance + CNN + Alternative.me |
| `crypto.py` | `fetch_crypto`, `fetch_global_stats`, `fetch_mcap_history` | CoinGecko + yfinance |
| `news.py` | `fetch_news` (with clustering + ticker extraction) | ~20 RSS feeds |
| `insider.py` | `fetch_insider` | Yahoo + OpenInsider |
| `analyst.py`, `calendar.py`, `options_flow.py`, `social.py`, `stock_list.py` | domain fetchers | public APIs |

The dashboard endpoint and the module-level cache wrap each fetch:

```
GET /api/live/crypto  →  live_crypto()  →  fetch_crypto()  →  cache hit?  →  HTTP
                                                              ↕ miss
                                                          httpx → parse → cache.set
```

### 3.2 Request flow through the pipeline

1. Browser calls `/api/live/<domain>` (the SPA auto-refreshes every 30 to 60 s).
2. The Quart handler calls the matching `fetch_*` function inside a
   `try/except` so a dead upstream returns a graceful `{"items": [], "error": ...}`
   payload instead of a 500.
3. The fetch function checks its TTL cache (section 4). On a miss it acquires the
   rate limiter (section 5), hits the network, parses into the common schema, and
   stores the result.
4. The endpoint `jsonify`s the result. The SPA renders it with the appropriate
   renderer (table, gauge, chart, carousel).

### 3.3 The scan pipeline

The scanner turns raw OHLCV into ranked signals:

```
watchlist (SQLite)
   │  scan_once() under _scan_lock
   ▼
fetch_stock() per symbol   (yfinance, 5m bars, 5 days)
   ▼
normalize_ohlcv()          (common schema: date, o/h/l/c, volume)
   ▼
generate_signal()          (src/analysis/signal.py)
   │   ├─ TA-Lib candlestick patterns      (+10 each, max 30)
   │   ├─ indicators: RSI, MACD, EMA cross (+5 each, max 20)
   │   ├─ support/resistance proximity     (+15)
   │   ├─ volume spikes                    (+10)
   │   └─ RSI divergence                   (+15)
   ▼
0-100 score + label (NOISE/WATCH/HOLD/BUY/SELL/STRONG)
   ▼
INSERT INTO signals   (one row per scan, newest 500 kept)
```

`scan_once()` in `src/main.py` is the single entry point. The 5 minute background
loop, the boot warm-up, and the manual `/api/scan/watchlist` endpoint all call it.
`_scan_lock` (an `asyncio.Lock`) guarantees only one scan runs at a time, so Yahoo
is never hammered by overlapping batches.

The dashboard reads signals through `/api/signals/recent`, which returns the latest
signal **per symbol** (`GROUP BY symbol ... MAX(id)`), so the Signals card shows
variety across the watchlist rather than a wall of one ticker.

---

## 4. Caching

Caching lives in three places, in order of speed.

### 4.1 In-memory TTL cache (`src/data/cache.py`)

`InMemoryCache` is a dict of `key → value` plus a parallel dict of
`key → timestamp`. `get(key, ttl)` lazily evicts expired entries (it does not run a
sweeper). Used by the OHLCV fetcher:

```python
cache_key = f"stock:{symbol}:{period}:{interval}"
cached = cache.get(cache_key, ttl=60)   # 60 s
```

### 4.2 Module-level dict caches (the live layer)

Each live module keeps its own `_cache` / `_global_cache` dict keyed by a domain
name, guarded by a stored `_ts`. TTLs are tuned per source:

| Cache | TTL | Why this value |
|-------|-----|----------------|
| `crypto` (25 coins) | 25 s | Price ticker freshness vs CoinGecko rate limits |
| `crypto/global` | 60 s | Global stats move slowly |
| `crypto/mcap` | 300 s | Market-cap history changes slowly; yfinance call is expensive |
| `market/overview` (quotes) | 20 s | Live watch freshness |
| `fear-greed` | minutes | Score updates a few times a day |

`fetch_mcap_history` buckets the `days` parameter to `30 / 365 / 1825` before
keying the cache, so arbitrary query strings cannot create unbounded cache entries
or repeat expensive downloads.

### 4.3 Durable caches (SQLite + JSON files)

- `signals` table in `scanner.db` stores scan history (trimmed to the newest 500).
- `data/toptraders/leaderboard.json` caches the ranked leaderboard so the API can
  serve it without recomputing.
- `data/copytrade.json` persists copy-trade positions.
- `_mcap_cache` aside, long-running aggregates (win rates, settled calls) are
  computed once per settle pass and stored in `toptraders.db`.

### 4.4 Downsampling

Long price series are decimated before reaching the browser. `_decimate(prices,
target=40)` in `crypto.py` samples roughly `target` evenly spaced points so 30 day
or 1 year sparklines stay small. The market-cap history decimates to 120 points.

---

## 5. Rate limiting

### 5.1 Token bucket (`src/data/rate_limiter.py`)

A single `RateLimiter` instance holds per-source limits. Each source has
`interval` (seconds per token), `tokens` (current balance) and `max` (bucket cap):

| Source | Max tokens | Refill interval |
|--------|-----------|-----------------|
| `yahoo` | 2 | 0.5 s |
| `webull` | 1 | 1.0 s |
| `polymarket` | 10 | 0.1 s |
| `solana` | 10 | 0.1 s |
| `birdeye` | 5 | 0.2 s |
| `scraper` | 2 | 1.0 s |

`acquire(source)`:

1. Refills tokens proportional to elapsed time since the last refill.
2. If fewer than one token is available, sleeps `(1 - tokens) * interval`.
3. Otherwise decrements the balance.

Unknown sources pass through (the default limit is one burst per interval, applied
only to known hosts).

### 5.2 Cooperative throttling

Because all fetches run on one event loop, `await rate_limiter.acquire("yahoo")`
pauses that coroutine without blocking the loop. Batch fetches (watchlist scans,
news feeds) naturally serialize on the bucket, which is what protects free-tier
endpoints.

### 5.3 Scan lock

Rate limiting guards per-request cost, but a full watchlist scan can still issue
dozens of yfinance calls. `_scan_lock` in `src/main.py` is an `asyncio.Lock`
acquired around `scan_once()`. The loop, the warm-up scan, and manual scans all
check `_scan_lock.locked()` and back off (the manual endpoint returns 409) instead
of stacking requests.

---

## 6. The top-trader engine

The engine tracks real traders from public platforms, scores their calls, ranks
them, and simulates copying the best ones. All inside `src/toptraders/`.

### 6.1 Adapters (`src/toptraders/adapters/`)

`base.py` defines two dataclasses and an abstract adapter:

```python
@dataclass
class AccountDraft: handle, source, display_name
@dataclass
class CallDraft: account_handle, source, symbol, direction,
                 entry_price, entry_time, source_call_id

class BaseAdapter:
    source = "base"
    async def fetch_profiles(self) -> list[AccountDraft]  # who to track
    async def fetch_calls(self, accounts) -> list[CallDraft]  # what they say
```

Implementations: `stocktwits`, `tradingview`, `polymarket`, `twitter`. Each adapter
owns its own API quirks (StockTwits parses sentiment entities into `long`/`short`
directions, Polymarket parses market resolves, etc.). Adapters use `rate_limiter`
with the `scraper` bucket.

### 6.2 Collection (`collector.py`)

`collect_all()` runs each adapter in sequence and aggregates a summary:

```
for adapter in ADAPTERS:
    profiles = await adapter.fetch_profiles()
    for d in profiles: store.upsert_account(d.handle, d.source, d.display_name)

    accounts = await store.list_accounts()
    drafts = await adapter.fetch_calls(accounts)      # capped at 200 accounts
    for d in drafts:
        store.upsert_call(account_id, d.source, d.symbol, d.direction,
                          d.entry_price, d.entry_time, d.source_call_id)
```

`upsert_call` dedupes on `(source, source_call_id)`, so re-collecting never
duplicates a call. A call with a missing entry price is stored with `0` and the
settlement step backfills it from the first close at/after the call time.

### 6.3 Scheduler (`scheduler.py`)

A background loop wakes every 30 s and checks two clocks:

1. **Collect cadence.** Every 30 minutes (`COLLECT_INTERVAL = 1800`) it calls
   `collector.collect_all()`.
2. **Settle window.** Every day between 22:00 and 22:20 UTC it runs, in order:
   - `outcomes.settle_all_open()` (close out due calls),
   - `leaderboard.rebuild_leaderboard()` (re-rank traders),
   - `copytrader.close_due_positions()` (exit paper positions at their horizon),
   then sleeps 60 s so the pass only runs once per window.

### 6.4 Outcomes (`outcomes.py`)

Each open call is settled at three horizons: 1 day, 5 days, 30 days.

```
settle_call(call, close_provider):
    for horizon in (1, 5, 30):
        target = entry_time + horizon * 86400
        if target > now: continue                # not due yet
        if horizon already recorded: continue    # idempotent
        close = await close_provider(symbol, target)   # yfinance daily close
        win = classify_win(direction, entry, close)    # BUFFER = 0.5%
        insert_outcome(...)                            # pnl_pct + win flag
    save_settled_call(...)   # aggregate wins/pnls per horizon
    mark_call_settled(...)
```

`classify_win` requires the close to beat the entry by more than a 0.5 % buffer
(`BUFFER = 0.005`) before counting a win, so breakeven noise does not inflate win
rates. After a settle pass, `_rebuild_ledger(account_id)` recomputes each touched
account's aggregate `ledger` row (settled counts, wins, total PnL in dollars).

### 6.5 Leaderboard (`leaderboard.py`)

`compute_win_rate(horizon=5)` reads every ledger row and keeps only eligible
traders:

- at least `TOP_TRADERS_MIN_CALLS` (default 10) settled calls at that horizon,
- and total PnL at least `TOP_TRADERS_MIN_PNL` (default $1,000).

It ranks by win rate descending, then PnL as a tiebreak, writes
`data/toptraders/leaderboard.json`, and returns the list. The dashboard serves it
through `/api/toptraders/leaderboard` and `/api/toptraders/picks` (the latter adds
live PnL for open calls).

### 6.6 Copy trader (`copytrader.py`)

The copy engine sizes and paper-trades positions in `data/copytrade.json`.

`size_for(wr, cap)` scales position size linearly with win rate between 50 % (size
0) and 100 % (size = cap):

```python
cap * (wr - 0.50) / 0.50
```

`copy_call(call_id, wr)`:

1. Looks up the open call and the trader's used allocation.
2. Rejects if the per-trader cap (`TOP_TRADERS_MAX_CAP`, default $5,000) would be
   exceeded.
3. Pulls a live price via `simulation.get_current_price` and executes a paper buy
   through `simulation.execute_buy`.
4. Records the position with `horizon_exit = 5` (days).

`close_due_positions()` runs during the settle window. For each open position past
its horizon it prefers the call's settled PnL (entry price scaled by the horizon
PnL %) and otherwise falls back to a live quote, then executes a paper sell.

The API exposes `/api/toptraders/copy/<call_id>` to open a copy and
`/api/toptraders/accounts/<handle>/toggle` to enable or disable a trader.

---

## 7. Data flow diagram (top traders)

```
Adapters (StockTwits / TradingView / Polymarket / Twitter)
   │ fetch_profiles, fetch_calls            (rate-limited httpx)
   ▼
collector.collect_all()  ── every 30 min ──►  scheduler.run_scheduler()
   │                                              │ (22:00-22:20 UTC)
   ▼                                              ▼
store (toptraders.db)                     outcomes.settle_all_open()
   │ accounts / calls                        │ (1d, 5d, 30d horizons)
   │                                          ▼
   │                                 store: outcomes + settled_calls
   │                                          ▼
   │                                 _rebuild_ledger() per account
   │                                          ▼
   │                                 leaderboard.rebuild_leaderboard()
   │                                          │  leaderboard.json
   ▼                                          ▼
API (/api/toptraders/*)               copytrader.close_due_positions()
   │                                   (paper sells in copytrade.json)
   ▼
SPA (Top Traders page)
```

---

## 8. Persistence layout

| Path | What lives there |
|------|------------------|
| `data/scanner.db` | Watchlist, signals, alerts, paper trades, signal log (WAL) |
| `data/toptraders.db` | Accounts, calls, outcomes, settled calls, ledgers (WAL) |
| `data/toptraders/leaderboard.json` | Cached ranked leaderboard |
| `data/copytrade.json` | Copy-trade positions and config |
| `data/*.db-wal` / `*.db-shm` | SQLite WAL sidecar files (normal, ignore) |

Both SQLite connections are opened once and shared, with WAL journaling so
background writers do not block readers.

---

## 9. Extension checklist

To add a new live data domain:

1. Create `src/data/live/<domain>.py` with an async `fetch_<domain>()` returning a
   plain dict, wrapped in a module-level TTL cache.
2. Acquire `rate_limiter` before any network call; add a bucket to
   `rate_limiter._limits` if the source is new.
3. Add a `/api/live/<domain>` route in `dashboard.py` with the same
   `try/except` fallback shape as the others.
4. Add a renderer + page in `templates/index.html` and register it in the SPA
   router and auto-refresh loop.
5. Add a test in `tests/` (mocking the upstream with `httpx.MockTransport` if the
   endpoint is rate-sensitive).

To add a top-trader source: implement `BaseAdapter` in
`src/toptraders/adapters/`, add it to `ADAPTERS` in `collector.py`, and the
collect/settle/leaderboard pipeline picks it up automatically.
