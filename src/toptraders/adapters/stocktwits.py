import time

import httpx

from src.data.rate_limiter import rate_limiter
from src.toptraders.adapters.base import AccountDraft, BaseAdapter, CallDraft

API = "https://api.stocktwits.com/api/2"


def parse_profiles(payload: dict) -> list[AccountDraft]:
    seen = {}
    for msg in payload.get("messages", []):
        user = msg.get("user") or {}
        username = str(user.get("username", ""))
        if not username or username in seen:
            continue
        seen[username] = AccountDraft(
            handle=username,
            source="stocktwits",
            display_name=str(user.get("name") or username),
        )
    return list(seen.values())


def parse_calls(payload: dict, username: str) -> list[CallDraft]:
    calls = []
    for msg in payload.get("messages", []):
        msg_user = (msg.get("user") or {}).get("username") or ""
        if msg_user != username:
            continue
        mid = msg.get("id")
        entities = msg.get("entities") or {}
        sentiment = (entities.get("sentiment") or {}).get("basic", "Neutral")
        direction = None
        if "Bullish" in sentiment:
            direction = "long"
        elif "Bearish" in sentiment:
            direction = "short"
        if direction is None:
            continue
        symbols = [s.get("symbol", "") for s in entities.get("symbols", [])]
        ts = _parse_ts(msg.get("created_at"))
        for sym in symbols:
            if not sym:
                continue
            calls.append(
                CallDraft(
                    account_handle=username,
                    source="stocktwits",
                    symbol=sym,
                    direction=direction,
                    entry_price=0,
                    entry_time=ts,
                    source_call_id=f"{username}-{mid}",
                )
            )
    return calls


def _parse_ts(created_at) -> float:
    try:
        from datetime import datetime, timezone

        return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


class StockTwitsAdapter(BaseAdapter):
    source = "stocktwits"

    async def fetch_profiles(self) -> list[AccountDraft]:
        try:
            await rate_limiter.acquire("scraper")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{API}/streams/trending.json",
                    headers={"User-Agent": "TradingScanner/1.0"},
                )
                resp.raise_for_status()
                return parse_profiles(resp.json())
        except Exception as e:
            print(f"StockTwits profiles error: {e}")
            return []

    async def fetch_calls(self, accounts: list) -> list[CallDraft]:
        all_calls = []
        for acc in accounts[:200]:
            try:
                await rate_limiter.acquire("scraper")
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{API}/users/{acc['handle']}/streams.json",
                        headers={"User-Agent": "TradingScanner/1.0"},
                    )
                    resp.raise_for_status()
                    all_calls.extend(parse_calls(resp.json(), acc["handle"]))
            except Exception as e:
                print(f"StockTwits stream error for {acc['handle']}: {e}")
        return all_calls
