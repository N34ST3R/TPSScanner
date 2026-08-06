"""Global market feeds: indices, commodities, forex, movers and fear & greed.

All fetchers are real-network, cached server-side, and degrade to empty results
on failure so the dashboard never hard-crashes.
"""
import asyncio
import time

import httpx

_cache: dict = {}


def _cached(key: str, ttl: float) -> dict | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["_ts"] < ttl:
        return {k: v for k, v in entry.items() if k != "_ts"}
    return None


def _store(key: str, payload: dict):
    payload = dict(payload)
    payload["_ts"] = time.time()
    _cache[key] = payload
    return {k: v for k, v in payload.items() if k != "_ts"}


async def _quote(symbol: str) -> dict | None:
    """One real quote via yfinance fast_info (cheap quoteSummary call)."""
    import yfinance as yf

    def _fetch():
        info = yf.Ticker(symbol).fast_info
        price = float(info.get("lastPrice", 0) or 0)
        prev = float(
            info.get("previousClose", 0) or info.get("previous_close", 0) or price
        )
        chg = (price - prev) if prev else 0
        pct = (chg / prev * 100) if prev else 0
        return {
            "symbol": symbol,
            "price": round(price, 4),
            "change": round(chg, 4),
            "change_pct": round(pct, 2),
        }

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _fetch)
    except Exception:
        return None


async def _quotes(symbols: list[str]) -> list[dict]:
    results = await asyncio.gather(*[_quote(s) for s in symbols])
    return [r for r in results if r]


INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX", "^RUT"]
INDEX_LABELS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^DJI": "Dow Jones",
    "^VIX": "VIX",
    "^TNX": "10Y Yield",
    "^RUT": "Russell 2K",
}


async def fetch_indices() -> dict:
    cached = _cached("indices", 25)
    if cached:
        return cached
    quotes = await _quotes(INDEX_SYMBOLS)
    items = []
    for q in quotes:
        sym = q["symbol"]
        items.append(
            {
                "symbol": sym,
                "name": INDEX_LABELS.get(sym, sym),
                "price": q["price"],
                "change": q["change"],
                "change_pct": q["change_pct"],
            }
        )
    return _store("indices", {"items": items, "count": len(items)})


COMMODITY_SYMBOLS = ["GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F"]
COMMODITY_LABELS = {
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "WTI Crude",
    "BZ=F": "Brent",
    "NG=F": "Nat Gas",
    "HG=F": "Copper",
}


async def fetch_commodities() -> dict:
    cached = _cached("commodities", 30)
    if cached:
        return cached
    quotes = await _quotes(COMMODITY_SYMBOLS)
    items = []
    for q in quotes:
        sym = q["symbol"]
        items.append(
            {
                "symbol": sym,
                "name": COMMODITY_LABELS.get(sym, sym),
                "price": q["price"],
                "change": q["change"],
                "change_pct": q["change_pct"],
            }
        )
    return _store("commodities", {"items": items, "count": len(items)})


FOREX_SYMBOLS = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "AUDUSD=X",
    "USDCAD=X",
    "USDCHF=X",
    "USDCNY=X",
]
FOREX_LABELS = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "USDCHF=X": "USD/CHF",
    "USDCNY=X": "USD/CNY",
}


async def fetch_forex() -> dict:
    cached = _cached("forex", 30)
    if cached:
        return cached
    quotes = await _quotes(FOREX_SYMBOLS)
    items = []
    for q in quotes:
        sym = q["symbol"]
        items.append(
            {
                "symbol": sym,
                "name": FOREX_LABELS.get(sym, sym),
                "price": q["price"],
                "change": q["change"],
                "change_pct": q["change_pct"],
            }
        )
    return _store("forex", {"items": items, "count": len(items)})


MOVER_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "NFLX",
    "AMD", "INTC", "AVGO", "ORCL", "ADBE", "CRM", "CSCO", "QCOM",
    "MU", "PLTR", "BABA", "PINS", "NIO", "SNOW", "UBER", "SHOP",
    "BA", "XOM", "CVX", "CAT", "GE", "F", "GM",
    "JPM", "GS", "MS", "BAC", "WFC", "C",
    "DIS", "NKE", "SBUX", "MCD", "WMT", "PG", "KO", "PEP",
    "JNJ", "PFE", "MRK", "UNH", "TMO", "LLY", "ABBV", "DOW",
]


async def fetch_movers() -> dict:
    """Top gainers / losers / most active from a single batched Yahoo download."""
    cached = _cached("movers", 60)
    if cached:
        return cached

    import yfinance as yf

    def _download():
        return yf.download(
            MOVER_UNIVERSE,
            period="5d",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )

    df = await asyncio.get_event_loop().run_in_executor(None, _download)
    rows = []
    for sym in MOVER_UNIVERSE:
        try:
            sub = df[sym].dropna()
            if len(sub) < 2:
                continue
            last = float(sub["Close"].iloc[-1])
            prev = float(sub["Close"].iloc[-2])
            vol = int(sub["Volume"].iloc[-1] or 0)
            pct = (last - prev) / prev * 100 if prev else 0
            rows.append(
                {
                    "symbol": sym,
                    "price": round(last, 2),
                    "change_pct": round(pct, 2),
                    "volume": vol,
                }
            )
        except Exception:
            continue
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return _store(
        "movers",
        {
            "gainers": rows[:10],
            "losers": sorted(rows, key=lambda r: r["change_pct"])[:10],
            "most_active": sorted(rows, key=lambda r: r["volume"], reverse=True)[:10],
            "count": len(rows),
        },
    )


async def fetch_fear_greed() -> dict:
    cached = _cached("feargreed", 30 * 60)
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.cnn.com/markets/fear-and-greed",
                },
            )
            if resp.status_code == 200 and "json" in (
                resp.headers.get("content-type") or ""
            ):
                data = resp.json().get("fear_and_greed", {})
                score = float(data.get("score") or 0)
                rating = str(data.get("rating") or "Neutral")
                history = []
                for ts, item in sorted(
                    data.get("history", {}).items(), key=lambda kv: kv[0]
                )[-180:]:
                    history.append(
                        {"t": float(item.get("x") or 0), "v": float(item.get("y") or 0)}
                    )
                # CNN dropped the long history field; pull it from Alternative.me
                # (free crypto fear & greed API) when CNN gives us nothing.
                if not history:
                    history = await _alt_me_history()
                return _store(
                    "feargreed",
                    {
                        "score": round(score, 1),
                        "rating": rating,
                        "previous": float(data.get("previous_close") or score),
                        "history": history,
                    },
                )
    except Exception:
        pass
    return _store("feargreed", {"score": 0, "rating": "Unknown", "history": []})


async def _alt_me_history() -> list[dict]:
    """30-day fear & greed history from Alternative.me (used when CNN has none)."""
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                "https://api.alternative.me/fng/?limit=30",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                out = []
                for item in resp.json().get("data", []):
                    try:
                        out.append(
                            {
                                "t": float(item.get("timestamp") or 0),
                                "v": float(item.get("value") or 0),
                            }
                        )
                    except (TypeError, ValueError):
                        continue
                out.sort(key=lambda h: h["t"])
                return out
    except Exception:
        pass
    return []
