# TPS Scanner

TPS Scanner aggregates **live data from across the internet** (stocks, crypto, news,
insider trades, top traders, prediction markets and social sentiment), scans it with a
rule-based pattern engine.

> **Not a broker.** The platform scans, ranks and simulates; it never places real orders.



<img width="2558" height="1425" alt="image" src="https://github.com/user-attachments/assets/ed1f7332-3fa5-4a46-a7e9-a9ee5ecbcdb3" />

---

## What it does

| Area | What you get |
|------|--------------|
| **Live Markets** | Indices (S&P 500, NASDAQ, DOW, VIX, 10Y, Russell 2K), commodities, forex, gainers/losers/most-active, scrolling ticker tape |
| **Stocks** | Full watchlist with real quotes, company logos, per-symbol pattern scans and a **draggable / resizable chart modal** (Chart.js candlesticks, zoom & pan, EMA overlays, volume, OHLC stats) |
| **Crypto** | CoinMarketCap-style **Market Overview**: ticker carousel, Fear & Greed gauge, Altcoin Season Index, Top-20 Index, BTC/ETH/Others dominance bar, a total market-cap chart with 30d/1y/All tabs, movers, and a 25-coin table with sparklines |
| **News** | 20+ news feeds, image/video thumbnails, sentiment badges, source links, and **breaking-story clustering** (the same story across outlets is grouped into one row with a heat badge HOT / TRENDING / MULTI-SOURCE) and clickable **ticker mentions** that launch a live scan |
| **Fear & Greed** | Real CNN score with an animated gauge **plus a 30-day history chart** (Alternative.me fallback) |
| **Insider Trading** | Merged Form 4 filings from **Yahoo Finance and OpenInsider**, filterable by buy/sell |
| **Top Traders** | Tracks real traders from **StockTwits, TradingView and Polymarket**, with a leaderboard, rich trader cards, win-rate tracking and a copy engine |
| **Scanner / Signals** | 0 to 100 score per symbol (candlestick patterns + indicators), one latest signal per symbol so the dashboard shows variety; a background scanner re-runs every 5 minutes |
| **Paper Simulator** | Buy/sell positions at live prices, portfolio summary, P&L alerts |
| **Extras** | Economic calendar, options flow, analyst ratings, Solana wallet tracking, Polymarket markets, social sentiment |

---

## Step 1: Prerequisites

| What | Why | How to get it |
|------|-----|---------------|
| Python 3.11+ | Core runtime | [python.org](https://python.org) or `brew install python` |
| TA-Lib C library | Candlestick pattern detection | See below |
| Git | Clone the repo | [git-scm.com](https://git-scm.com) |

### Installing TA-Lib (the hard part)

TA-Lib has a C dependency. Pick ONE method:

**Option A - Pre-built wheel (Windows, easiest):**
```bash
pip install TA-Lib --find-links https://github.com/cgohlke/talib-build/releases
```

**Option B - Conda (any OS):**
```bash
conda install -c conda-forge ta-lib
```

**Option C - Build from source (Linux/Mac):**
```bash
# Ubuntu/Debian
sudo apt-get install build-essential wget
wget https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib
./configure --prefix=/usr
make
sudo make install

# Mac
brew install ta-lib
```

If TA-Lib install fails, the scanner still works; it just won't detect candlestick
patterns. Indicators (RSI, MACD, etc.) use only pandas/numpy.

---

## Step 2: Install the Project

```bash
cd trading-scraper

# Virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Step 3: Configure Your Settings

```bash
cp .env.example .env
```

| Variable | Required? | What it does |
|----------|-----------|-------------|
| `ACCOUNT_SIZE` | Yes | Account size in USD, used for position sizing recommendations |
| `WEBULL_ACCOUNT_ID` | No | Only if you have a Webull account |
| `WEBULL_ACCESS_TOKEN` | No | Your Webull API token |
| `WALLET_ADDRESSES` | No | Comma-separated wallet addresses to track |
| `SOLANA_RPC` | No | Solana RPC endpoint (default works; Helius/QuickNode is faster) |
| `BIRDEYE_API_KEY` | No | Free Birdeye API key for Solana token prices |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook URL for alerts |
| `SCRAPE_URLS` | No | Comma-separated URLs for the manual scraper |

**Minimum viable config:**
```env
ACCOUNT_SIZE=100
```

Most live-data features (markets, crypto, news, insider, top traders) need **no API keys**;
they use public endpoints.

---

## Step 4: Run It

**Full app** (dashboard + MCP server + background scanner + top-trader scheduler):
```bash
python src/main.py
```
```
Dashboard: http://localhost:5000
MCP Server: http://localhost:8001
```
On boot the watchlist auto-seeds with default symbols and a warm-up scan runs ~12s later,
so the Signals card has varied data immediately.

**Quick preview** (dashboard only, no MCP/scanner; handy for development):
```bash
python scripts/preview_server.py          # port 5050
python scripts/preview_server.py 8080     # custom port
```

Open the dashboard URL in your browser. Use the **Quick scan** box (or `Ctrl/Cmd K`) to
scan any ticker such as `AAPL`, `NVDA`, `BTC-USD`…

---

## How the Signal System Works

Every scan produces a **score from 0 to 100**:

| Score | Label | What it means |
|-------|-------|--------------|
| 0-20 | NOISE | Nothing happening |
| 21-40 | WATCH | Potential setup forming |
| 41-60 | HOLD | Mixed signals; wait for clarity |
| 61-80 | BUY / SELL | Actionable signal |
| 81-100 | STRONG BUY / STRONG SELL | High-confidence signal |

### What adds points:
- **Candlestick patterns** (Engulfing, Hammer, Doji, …), +10 each, max 30
- **Indicator confirmations** (RSI, MACD, EMA crossovers), +5 each, max 20
- **Support/resistance proximity**, +15
- **Volume spikes**, +10
- **RSI divergence**, +15
- **Contradictory patterns**, −20 (resets direction)

The `net_direction` counter tracks bullish (+1) vs bearish (−1) signals to decide whether
a high score means BUY or SELL.

---

## Data Sources

| Source | Data |
|--------|------|
| Yahoo Finance (`yfinance`) | Quotes, OHLCV history, indices, commodities, forex, movers, insider trades |
| CoinGecko | 25 top coins (price, cap, volume, sparklines, 1h/24h/7d/30d), global stats, market-cap history |
| CNN + Alternative.me | Fear & Greed score and 30-day history |
| 20+ RSS/news feeds | Articles with thumbnails, video posters, sentiment, source links |
| OpenInsider | Form 4 insider trades (parsed from HTML) |
| StockTwits / TradingView / Polymarket | Top-trader accounts, calls and leaderboards |
| Polymarket Gamma API | Active prediction markets |
| Solana RPC + Birdeye | Wallet token balances |

All live fetches are cached with short TTLs and rate-limited per source.

---

## News Intelligence

- **Duplicate clustering** groups near-identical headlines across feeds into one
  story with a source count and a heat badge (**HOT** ≥ 4 sources, **TRENDING** ≥ 2).
- **Ticker extraction** finds uppercase ticker mentions per article (with a
  noise blacklist) and renders them as chips that open a live scan of that symbol.
- Every story card links back to the original article.

---

## Project Structure

```
trading-scraper/
├── src/
│   ├── analysis/                 # Signal engine
│   │   ├── patterns.py           # TA-Lib candlestick patterns
│   │   ├── indicators.py         # RSI, MACD, EMA, Bollinger, etc.
│   │   ├── custom_patterns.py    # Support/resistance, volume spikes
│   │   └── signal.py             # 0-100 score generator
│   ├── data/
│   │   ├── live/                 # Live internet data (all async)
│   │   │   ├── markets.py        # Indices, commodities, forex, movers, Fear & Greed
│   │   │   ├── crypto.py         # Coins, global stats, market-cap history
│   │   │   ├── news.py           # Feeds, clustering, ticker extraction
│   │   │   ├── insider.py        # Yahoo + OpenInsider Form 4s
│   │   │   ├── analyst.py        # Analyst ratings
│   │   │   ├── calendar.py       # Economic calendar
│   │   │   ├── options_flow.py   # Options flow
│   │   │   ├── social.py         # Social sentiment
│   │   │   └── stock_list.py     # Full stock universe
│   │   ├── fetcher.py            # Yahoo/Webull async OHLCV
│   │   ├── polymarket.py         # Polymarket Gamma API
│   │   ├── wallet.py             # Solana RPC + Birdeye
│   │   ├── scraper.py            # httpx + BeautifulSoup
│   │   ├── cache.py              # In-memory TTL cache
│   │   ├── rate_limiter.py       # Per-source rate limiting
│   │   └── normalize.py          # Common schema normalization
│   ├── delivery/
│   │   ├── dashboard.py          # Quart web API
│   │   ├── templates/index.html  # Single-page dashboard UI
│   │   ├── alerts.py             # Notifications
│   │   ├── simulation.py         # Paper trading + watchlists
│   │   └── mcp_server.py         # FastMCP for AI tools
│   ├── store/
│   │   ├── database.py           # SQLite async (aiosqlite)
│   │   └── config.py             # .env configuration
│   ├── toptraders/               # Top-trader engine
│   │   ├── adapters/             # stocktwits / tradingview / polymarket / twitter
│   │   ├── collector.py          # Pulls accounts + calls
│   │   ├── leaderboard.py        # Win-rate + leaderboard
│   │   ├── copytrader.py         # Copy-call simulation
│   │   ├── scheduler.py          # Periodic collection
│   │   ├── store.py              # Trader persistence
│   │   └── outcomes.py           # Call outcomes
│   └── main.py                   # Entry point
├── scripts/
│   └── preview_server.py         # Dashboard-only launcher (default 5050)
├── tests/                        # Test suite
├── requirements.txt
├── .env.example
└── README.md
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard SPA |
| GET | `/api/watchlist` | List watched tickers |
| POST | `/api/watchlist` | Add a ticker `{"symbol": "AAPL"}` |
| DELETE | `/api/watchlist/<symbol>` | Remove a ticker |
| GET | `/api/scan/<symbol>?timeframe=5m` | Scan one ticker |
| GET | `/api/scan/watchlist` | Scan + persist the whole watchlist |
| GET | `/api/signals/recent?limit=50` | Latest signal **per symbol** |
| GET | `/api/history/<symbol>?period=5d&interval=5m` | OHLCV for charting |
| GET | `/api/market/overview` | Live quotes for the watchlist |
| GET | `/api/live/indices` | S&P 500, NASDAQ, DOW, VIX, … |
| GET | `/api/live/commodities` | Commodity quotes |
| GET | `/api/live/forex` | FX pairs |
| GET | `/api/live/movers` | Gainers / losers / most active |
| GET | `/api/live/fear-greed` | CNN Fear & Greed + history |
| GET | `/api/live/crypto` | Top 25 coins with sparklines |
| GET | `/api/live/crypto/global` | Total cap, volume, BTC/ETH dominance |
| GET | `/api/live/crypto/mcap?days=30` | Total market-cap history (30d/1y/All) |
| GET | `/api/live/news` | Articles + trending clusters + tickers |
| GET | `/api/live/stocks` | Full stock universe |
| GET | `/api/live/insider` | Insider trades (Yahoo + OpenInsider) |
| GET | `/api/live/analyst` | Analyst ratings |
| GET | `/api/live/calendar` | Economic calendar |
| GET | `/api/live/options` | Options flow |
| GET | `/api/live/social` | Social sentiment |
| GET | `/api/polymarket` | Active prediction markets |
| GET | `/api/wallet/<address>` | Solana wallet portfolio |
| GET | `/api/scrape?url=...` | Scrape a public URL |
| GET | `/api/alerts` | Alert history |
| GET | `/api/alerts/check` | Portfolio-based alert check |
| GET | `/api/stats` | Watchlist / signal / alert counts |
| GET | `/api/simulation/portfolio` | Paper portfolio |
| POST | `/api/simulation/buy` / `sell` | Paper trades |
| GET | `/api/simulation/transactions` | Trade history |
| GET | `/api/toptraders/accounts` | Tracked traders |
| GET | `/api/toptraders/leaderboard` | Ranked traders |
| GET | `/api/toptraders/picks` | Open calls with live P&L |
| POST | `/api/toptraders/collect` | Trigger background collection |
| GET | `/api/toptraders/collect/status` | Collection progress |
| POST | `/api/toptraders/copy/<call_id>` | Copy a trader's call |
| POST | `/api/toptraders/accounts/<handle>/toggle` | Enable/disable copy |

---

## MCP Server (for AI Tools)

Runs on port **8001** and exposes tools like `scan_ticker`, `scan_watchlist`,
`scan_polymarket`, `scan_wallet`, `scrape_page`, `get_alert_history` and
`get_market_overview`.

**Security:** Don't expose port 8001 externally; the scraper tool can hit any URL
including localhost.

---

## Background Scanner

Runs automatically every 5 minutes and:
1. Pulls your watchlist from the database
2. Fetches the latest OHLCV data for each ticker
3. Runs pattern detection + indicator analysis
4. Stores signals (kept to the newest 500) and triggers alerts

A warm-up scan runs ~12 seconds after boot so the dashboard has fresh signals quickly.
All scans share a lock so manual scans never collide with the background loop.

---

## Testing

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `TA-Lib import error` | Install the C library first (see Step 1) |
| `yfinance returns empty` | Market may be closed; try another ticker or check your internet |
| `Dashboard won't start` | Make sure ports 5000 / 5050 aren't already in use |
| `Solana RPC timeout` | Use a paid RPC provider (Helius, QuickNode) |
| `Discord alerts not sending` | Verify your webhook URL and channel |
| Signals all show one symbol | The watchlist was empty; defaults reseed on every boot. Add more tickers via Watch |

---

## Notes

- No automated trading (signals only); the paper simulator is sandboxed
- Rule-based patterns + VADER sentiment; no ML
- Read-only for Polymarket / Webull
- Single user, one timeframe per scan
