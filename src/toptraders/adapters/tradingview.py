import re
import time

from bs4 import BeautifulSoup

from src.toptraders.adapters.base import AccountDraft, BaseAdapter, CallDraft


def parse_ideas(html: str) -> list[CallDraft]:
    soup = BeautifulSoup(html, "html.parser")
    calls = []
    for card in soup.select(".js-idea"):
        idea_id = card.get("data-idea-id") or ""
        author_el = card.select_one(".tv-user-widget__link")
        author = (
            author_el.get("href", "").rstrip("/").split("/")[-1] if author_el else ""
        )
        tag_el = card.select_one(".tv-widget-idea__signal-tag")
        direction = tag_el.get_text(strip=True).lower() if tag_el else ""
        ticker_el = card.select_one(".tv-widget-idea__ticker")
        ticker = ticker_el.get_text(strip=True).upper() if ticker_el else ""
        if not (idea_id and author and direction in ("long", "short") and ticker):
            continue
        calls.append(
            CallDraft(
                account_handle=author,
                source="tradingview",
                symbol=ticker,
                direction=direction,
                entry_price=0,
                entry_time=time.time(),
                source_call_id=f"tv-{idea_id}",
            )
        )
    return calls


class TradingViewAdapter(BaseAdapter):
    source = "tradingview"

    async def fetch_profiles(self) -> list[AccountDraft]:
        # TV exposes no public top-user list; accounts are seeded from ideas.
        return []

    async def fetch_calls(self, accounts: list) -> list[CallDraft]:
        try:
            from curl_cffi import requests as cffi_requests

            resp = cffi_requests.get(
                "https://www.tradingview.com/ideas/", impersonate="chrome"
            )
            resp.raise_for_status()
            return parse_ideas(resp.text)
        except Exception as e:
            print(f"TradingView ideas error: {e}")
            return []
