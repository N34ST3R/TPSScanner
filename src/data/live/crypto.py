import time
import httpx

_cache = {}
_cache_ttl = 25


_global_cache = {"_ts": 0, "data": None}


def _decimate(prices: list, target: int = 40) -> list:
    """Downsample a long price series to ~target points for compact sparklines."""
    if not prices:
        return []
    if len(prices) <= target:
        return [round(float(p), 6) for p in prices]
    step = len(prices) / target
    out = []
    i = 0
    while i < len(prices):
        out.append(round(float(prices[int(i)]), 6))
        i += step
    if len(out) < 2:
        out.append(round(float(prices[-1]), 6))
    return out


async def fetch_crypto() -> dict:
    now = time.time()
    cache_key = "crypto"
    if cache_key in _cache and now - _cache[cache_key]["_ts"] < _cache_ttl:
        return {k: v for k, v in _cache[cache_key].items() if k != "_ts"}

    coins = []
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 25,
                    "page": 1,
                    "sparkline": "true",
                    "price_change_percentage": "1h,24h,7d,30d",
                },
            )
            if resp.status_code == 200:
                for c in resp.json():
                    spark = (c.get("sparkline_in_7d") or {}).get("price") or []
                    coins.append(
                        {
                            "id": c.get("id", ""),
                            "symbol": c.get("symbol", "").upper(),
                            "name": c.get("name", ""),
                            "price": c.get("current_price", 0),
                            "market_cap": c.get("market_cap", 0),
                            "volume_24h": c.get("total_volume", 0),
                            "circulating_supply": c.get("circulating_supply", 0),
                            "ath": c.get("ath", 0),
                            "change_1h": c.get(
                                "price_change_percentage_1h_in_currency", 0
                            )
                            or 0,
                            "change_24h": c.get("price_change_percentage_24h", 0) or 0,
                            "change_7d": c.get(
                                "price_change_percentage_7d_in_currency", 0
                            )
                            or 0,
                            "change_30d": c.get(
                                "price_change_percentage_30d_in_currency", 0
                            )
                            or 0,
                            "rank": c.get("market_cap_rank", 0),
                            "image": c.get("image", ""),
                            "sparkline": _decimate(spark),
                        }
                    )
        except Exception:
            pass

    result = {
        "coins": coins,
        "total": len(coins),
        "updated_at": now,
    }
    result["_ts"] = now
    _cache[cache_key] = result

    return {k: v for k, v in result.items() if k != "_ts"}


_mcap_cache = {}


async def fetch_mcap_history(days: int = 30) -> dict:
    """Total crypto market-cap history.

    CoinGecko has no public market-cap *history* endpoint, so we approximate:
    total_cap(t) = BTC close(t) * BTC supply / BTC dominance, then rescale so the
    latest point equals the real global market cap. Tracks the true shape closely
    since BTC dominates the total.
    """
    days = max(7, min(days, 3650))
    # Bucket to the 3 real periods so cache keys stay bounded.
    bucket = 30 if days <= 31 else 365 if days <= 366 else 1825
    key = f"mcap-{bucket}"
    if key in _mcap_cache and time.time() - _mcap_cache[key]["_ts"] < 300:
        return _mcap_cache[key]["data"]
    out = {"points": [], "days": days}
    try:
        import yfinance as yf

        period = "1mo" if bucket <= 31 else "1y" if bucket <= 366 else "max"
        df = yf.download(
            "BTC-USD", period=period, interval="1d", progress=False, auto_adjust=True
        )
        # Keep index + values aligned: drop NaN rows from the series itself, then
        # zip with its own (filtered) index.
        close_s = df["Close"].iloc[:, 0].dropna()
        if len(close_s) < 2:
            return out
        g = await fetch_global_stats()
        dom = max(float(g.get("btc_dominance") or 55) / 100.0, 0.05)
        cur_total = float(g.get("total_market_cap") or 0)
        supply = 19_800_000.0
        scale = 1.0
        last = float(close_s.iloc[-1])
        if last > 0 and cur_total > 0:
            scale = cur_total / (last * supply / dom)
        pts = [
            {"t": int(ts.timestamp()), "v": round(float(v) * supply / dom * scale)}
            for ts, v in zip(close_s.index, close_s)
        ]
        # keep last N days, decimated
        pts = pts[-bucket:]
        out["points"] = _decimate([p["v"] for p in pts], target=120)
        t0 = pts[0]["t"]
        t1 = pts[-1]["t"]
        step = (t1 - t0) / max(len(out["points"]) - 1, 1)
        out["points"] = [
            {"t": int(t0 + i * step), "v": v}
            for i, v in enumerate(out["points"])
        ]
        out["change"] = (
            round((pts[-1]["v"] / pts[0]["v"] - 1) * 100, 2) if pts[0]["v"] else 0
        )
        out["days"] = bucket
        _mcap_cache[key] = {"_ts": time.time(), "data": out}
    except Exception:
        pass
    return out


async def fetch_global_stats() -> dict:
    """Global crypto market: total cap, BTC dominance, 24h volume, change."""
    if _global_cache["data"] and time.time() - _global_cache["_ts"] < 60:
        return _global_cache["data"]
    out = {
        "total_market_cap": 0,
        "total_volume_24h": 0,
        "btc_dominance": 0,
        "eth_dominance": 0,
        "change_24h": 0,
        "market_cap_change_24h": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.coingecko.com/api/v3/global")
            if resp.status_code == 200:
                d = resp.json().get("data", {})
                out["total_market_cap"] = float((d.get("total_market_cap") or {}).get("usd") or 0)
                out["total_volume_24h"] = float((d.get("total_volume") or {}).get("usd") or 0)
                mcp = d.get("market_cap_percentage") or {}
                out["btc_dominance"] = round(float(mcp.get("btc") or 0), 2)
                out["eth_dominance"] = round(float(mcp.get("eth") or 0), 2)
                out["change_24h"] = round(float(d.get("market_cap_change_percentage_24h_usd") or 0), 2)
                out["market_cap_change_24h"] = out["change_24h"]
                _global_cache["_ts"] = time.time()
                _global_cache["data"] = out
    except Exception:
        pass
    return out
