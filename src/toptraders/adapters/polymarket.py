import time

import httpx

from src.data.rate_limiter import rate_limiter
from src.toptraders.adapters.base import AccountDraft, BaseAdapter, CallDraft

DATA_API = "https://data-api.polymarket.com"


def parse_profiles(payload: dict) -> list[AccountDraft]:
    profiles = []
    for row in payload.get("data", []):
        addr = str(row.get("address", ""))
        if not addr:
            continue
        profiles.append(
            AccountDraft(
                handle=addr,
                source="polymarket",
                display_name=str(row.get("display_name") or row.get("name") or ""),
            )
        )
    return profiles


def parse_calls(payload: dict) -> list[CallDraft]:
    calls = []
    for t in payload.get("data", []):
        user = str(t.get("user", ""))
        side = str(t.get("side", "")).upper()
        market = t.get("market") or {}
        ticker = str(market.get("ticker") or "")
        if not user or not ticker:
            continue
        direction = "bull" if side == "BUY" else "bear" if side == "SELL" else None
        if direction is None:
            continue
        ts = float(t.get("timestamp") or 0)
        calls.append(
            CallDraft(
                account_handle=user,
                source="polymarket",
                symbol=ticker,
                direction=direction,
                entry_price=float(t.get("price") or 0),
                entry_time=ts,
                source_call_id=f"{user}-{int(ts)}-{ticker}-{side}",
            )
        )
    return calls


class PolymarketAdapter(BaseAdapter):
    source = "polymarket"

    async def fetch_profiles(self) -> list[AccountDraft]:
        try:
            await rate_limiter.acquire("polymarket")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{DATA_API}/leaderboard", params={"limit": 500}
                )
                resp.raise_for_status()
                return parse_profiles(resp.json())
        except Exception as e:
            print(f"Polymarket profiles error: {e}")
            return []

    async def fetch_calls(self, accounts: list) -> list[CallDraft]:
        all_calls = []
        for acc in accounts[:100]:
            try:
                await rate_limiter.acquire("polymarket")
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"{DATA_API}/trades",
                        params={"user": acc["handle"], "limit": 100},
                    )
                    resp.raise_for_status()
                    all_calls.extend(parse_calls(resp.json()))
            except Exception as e:
                print(f"Polymarket trades error for {acc['handle']}: {e}")
        return all_calls
