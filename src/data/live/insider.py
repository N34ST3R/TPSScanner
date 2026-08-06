import asyncio
import re
import time
import httpx

import yfinance as yf

_cache = {}
_cache_ttl = 60

INSIDER_TICKERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "BRK-B",
    "UNH",
    "JNJ",
    "V",
    "XOM",
    "WMT",
    "JPM",
    "PG",
    "MA",
    "HD",
    "CVX",
    "MRK",
    "ABBV",
    "LLY",
    "PEP",
    "KO",
    "AVGO",
    "COST",
    "TMO",
    "MCD",
    "CSCO",
    "ACN",
    "ABT",
    "DHR",
    "NKE",
    "ORCL",
    "TXN",
    "PM",
    "UPS",
    "CRM",
    "AMD",
    "QCOM",
    "INTC",
    "BA",
    "NFLX",
    "DIS",
    "PYPL",
    "ADBE",
    "CMCSA",
    "NEE",
    "BMY",
    "HON",
    "UNP",
    "LOW",
    "MS",
    "GS",
    "CAT",
    "BLK",
    "AXP",
    "ISRG",
    "ADI",
    "MDLZ",
    "GILD",
    "SYK",
    "CB",
    "PLD",
    "ZTS",
    "MMC",
    "CI",
    "SCHW",
    "SO",
    "DUK",
    "ICE",
    "PLTR",
    "SOFI",
    "RIVN",
    "LCID",
    "NIO",
    "COIN",
    "MSTR",
    "SQ",
    "SHOP",
]


async def fetch_insider() -> dict:
    now = time.time()
    cache_key = "insider"
    if cache_key in _cache and now - _cache[cache_key]["_ts"] < _cache_ttl:
        return {k: v for k, v in _cache[cache_key].items() if k != "_ts"}

    all_trades = []

    def _fetch():
        import re

        for ticker in INSIDER_TICKERS[:75]:
            try:
                t = yf.Ticker(ticker)
                insider = t.insider_transactions
                if insider is None or insider.empty:
                    continue
                for _, row in insider.head(5).iterrows():
                    text = str(row.get("Text", ""))
                    raw_shares = row.get("Shares")
                    raw_value = row.get("Value")
                    shares = (
                        int(raw_shares)
                        if raw_shares and raw_shares == raw_shares
                        else 0
                    )
                    value = (
                        float(raw_value) if raw_value and raw_value == raw_value else 0
                    )

                    price_match = re.search(r"at price ([\d.]+)", text)
                    text_price = float(price_match.group(1)) if price_match else 0
                    price = (
                        round(value / shares, 2)
                        if shares > 0 and value > 0
                        else text_price
                    )

                    owns = str(row.get("Ownership", ""))
                    insider_name = str(row.get("Insider", ""))
                    position = str(row.get("Position", ""))
                    start = str(row.get("Start Date", ""))

                    text_lower = text.lower()
                    is_buy = "purchase" in text_lower or "buy" in text_lower
                    is_sell = "sale" in text_lower or "sell" in text_lower
                    is_gift = (
                        "gift" in text_lower
                        or "award" in text_lower
                        or "grant" in text_lower
                    )
                    trade_type = (
                        "buy"
                        if is_buy
                        else ("sell" if is_sell else ("gift" if is_gift else "other"))
                    )

                    all_trades.append(
                        {
                            "ticker": ticker,
                            "insider": insider_name,
                            "title": position,
                            "trade_type": trade_type,
                            "price": price if trade_type != "gift" else 0,
                            "shares": shares,
                            "owned": owns,
                            "delta_ownership": "",
                            "value": value if trade_type != "gift" else 0,
                            "date": start,
                            "source": "Yahoo Finance",
                            "detail": text[:120] if text else "",
                        }
                    )
            except Exception:
                pass

    await asyncio.to_thread(_fetch)

    # ---- Second source: OpenInsider Form 4 feed (real, live) ----
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "http://openinsider.com/latest-insider-trading",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                    )
                },
            )
            if resp.status_code == 200:
                open_trades = _parse_openinsider(resp.text)
                # merge, prefer OpenInsider rows (they carry exact dates/prices)
                existing = {t["detail"]: t for t in all_trades}
                for t in open_trades:
                    existing[t["detail"]] = t
                all_trades = list(existing.values())
    except Exception:
        pass

    all_trades.sort(key=lambda t: t.get("date", ""), reverse=True)
    result = {"trades": all_trades[:200], "total": len(all_trades), "updated_at": now}
    result["_ts"] = now
    _cache[cache_key] = result
    return {k: v for k, v in result.items() if k != "_ts"}


def _parse_openinsider(html: str) -> list[dict]:
    """Parse the OpenInsider 'latest insider trading' table into our trade shape.

    Column layout observed (per <td>):
      0 marker | 1 timestamp(SEC link) | 2 trade date | 3 ticker link | 4 company
      5 insider | 6 title | 7 trade type | 8 price | 9 shares | 10 value | 11 delta
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    trades = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 11:
            continue
        # ticker lives in a link like href="/GLBE"
        link = cells[3]
        m = re.search(r"href=\\?\"?/?([A-Z0-9.\-]{1,8})\\?\"?", link)
        m = re.search(r"href=\\?\"?/?([A-Z0-9.\-]{1,8})\\?\"?", link) if not m else m
        if not m:
            continue
        ticker = m.group(1).upper()
        if not re.match(r"^[A-Z0-9.\-]{1,8}$", ticker):
            continue
        company = re.sub(r"<[^>]+>", "", cells[4]).strip()
        insider = re.sub(r"<[^>]+>", "", cells[5]).strip()
        title = re.sub(r"<[^>]+>", "", cells[6]).strip()
        ttype_raw = re.sub(r"<[^>]+>", "", cells[7]).strip().upper()
        price_raw = re.sub(r"[^0-9.]", "", cells[8])
        qty_raw = re.sub(r"[^0-9.-]", "", cells[9])
        value_raw = re.sub(r"[^0-9.]", "", cells[10])
        date_raw = re.sub(r"<[^>]+>", "", cells[2]).strip()
        try:
            qty = int(float(qty_raw)) if qty_raw else 0
        except ValueError:
            qty = 0
        try:
            value = float(value_raw) if value_raw else 0.0
        except ValueError:
            value = 0.0
        try:
            price = float(price_raw) if price_raw else 0.0
        except ValueError:
            price = 0.0
        if ttype_raw.startswith("P") or "BUY" in ttype_raw:
            ttype = "buy"
        elif ttype_raw.startswith("S"):
            ttype = "sell"
        elif "GIFT" in ttype_raw or "GRANT" in ttype_raw or "AWARD" in ttype_raw:
            ttype = "gift"
        else:
            ttype = "other"
        detail = f"{ticker} {insider} {title} {ttype_raw}"
        trades.append(
            {
                "ticker": ticker,
                "insider": insider,
                "title": title or company[:40],
                "trade_type": ttype,
                "price": price,
                "shares": abs(qty),
                "owned": "",
                "delta_ownership": re.sub(r"<[^>]+>", "", cells[11]).strip()[:10]
                if len(cells) > 11
                else "",
                "value": value,
                "date": date_raw,
                "source": "OpenInsider",
                "detail": detail[:120],
            }
        )
    return trades
