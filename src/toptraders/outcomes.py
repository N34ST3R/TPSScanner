import asyncio
import time as time_mod

from src.toptraders import store

BUFFER = 0.005
HORIZONS = (1, 5, 30)


def classify_win(direction: str, entry_price: float, close_price: float) -> bool:
    if direction in ("long", "bull"):
        return close_price > entry_price * (1 + BUFFER)
    if direction in ("short", "bear"):
        return close_price < entry_price * (1 - BUFFER)
    return False


def resolve_entry_price(entry_price, daily_closes, entry_time=0.0) -> float:
    """daily_closes: list of (price, ts) ascending. Backfills missing entry
    with the first close at/after the call's entry time, else last close."""
    if entry_price and entry_price > 0:
        return float(entry_price)
    if not daily_closes:
        return 0.0
    for price, ts in daily_closes:
        if ts >= entry_time:
            return float(price)
    return float(daily_closes[-1][0])


async def settle_call(call, close_provider, now=None) -> dict:
    """Settle one open call at each horizon whose target time has passed.
    close_provider(symbol, target_time) -> float|None. Returns per-horizon results."""
    entry_time = float(call["entry_time"])
    now = now if now is not None else time_mod.time()
    results = []
    for horizon in HORIZONS:
        target = entry_time + horizon * 86400
        if target > now:
            continue
        existing = {
            o["horizon"]: dict(o) for o in await store.get_outcomes_for_call(call["id"])
        }
        if horizon in existing:
            results.append(existing[horizon])
            continue
        close_price = await close_provider(call["symbol"], target)
        if close_price is None:
            continue
        win = classify_win(call["direction"], call["entry_price"], close_price)
        pnl_pct = (
            ((close_price - call["entry_price"]) / call["entry_price"] * 100)
            if call["entry_price"]
            else 0.0
        )
        await store.insert_outcome(call["id"], horizon, close_price, now, pnl_pct, win)
        results.append({"horizon": horizon, "win": win, "pnl_pct": pnl_pct})
    if results:
        # store.wins/pnls arrays per horizon index order (1,5,30)
        win_map = {r["horizon"]: r.get("win", 0) for r in results}
        pnl_map = {r["horizon"]: r.get("pnl_pct", 0.0) for r in results}
        wins = [win_map.get(h, 0) for h in HORIZONS]
        pnls = [pnl_map.get(h, 0.0) for h in HORIZONS]
        await store.save_settled_call(
            call["id"],
            call["account_id"],
            call["symbol"],
            call["entry_price"],
            call["entry_time"],
            wins,
            pnls,
            now,
        )
        await store.mark_call_settled(call["id"])
    return {"call_id": call["id"], "settled": len(results), "results": results}


async def settle_all_open(close_provider=None) -> dict:
    """Full settle pass. close_provider defaults to yfinance-based provider."""
    if close_provider is None:
        close_provider = _yf_close_provider
    calls = await store.get_open_calls_needing_settlement()
    settled_count = 0
    touched_accounts = set()
    for call in calls:
        try:
            res = await settle_call(call, close_provider)
            if res["settled"]:
                settled_count += 1
                touched_accounts.add(call["account_id"])
        except Exception as e:
            print(f"Settle error call {call['id']}: {e}")
    for account_id in touched_accounts:
        await _rebuild_ledger(account_id)
    return {"settled": settled_count, "touched_accounts": len(touched_accounts)}


async def _rebuild_ledger(account_id: int):
    db = await store.get_tt_db()
    async with db.execute(
        "SELECT win_1d, win_5d, win_30d, pnl_1d, pnl_5d, pnl_30d, entry_price "
        "FROM settled_calls WHERE account_id = ?",
        (account_id,),
    ) as cur:
        rows = await cur.fetchall()
    settled = [0, 0, 0]
    wins = [0, 0, 0]
    pnl_total = 0.0
    for r in rows:
        for i, win_key in enumerate(("win_1d", "win_5d", "win_30d")):
            if r[win_key] is not None:
                settled[i] += 1
                wins[i] += int(r[win_key])
        entry = float(r["entry_price"] or 0.0)
        pnl_total += sum(float(r[f"pnl_{h}"] or 0.0) / 100 * entry for h in (1, 5, 30))
    await store.update_ledger(
        account_id,
        settled[0],
        settled[1],
        settled[2],
        wins[0],
        wins[1],
        wins[2],
        pnl_total,
    )


async def _yf_close_provider(symbol: str, target_time: float):
    """Daily close at/just before target_time, via yfinance in a thread."""

    def _fetch():
        import pandas as pd
        import yfinance as yf

        target_ts = pd.Timestamp(target_time, unit="s", tz="UTC")
        df = yf.Ticker(symbol).history(period="1y", interval="1d")
        if df.empty:
            return None
        df.index = (
            df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
        )
        df = df[df.index <= target_ts]
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])

    return await asyncio.to_thread(_fetch)
