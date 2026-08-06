from src.toptraders import store
from src.toptraders.adapters.polymarket import PolymarketAdapter
from src.toptraders.adapters.stocktwits import StockTwitsAdapter
from src.toptraders.adapters.tradingview import TradingViewAdapter

ADAPTERS = [PolymarketAdapter(), StockTwitsAdapter(), TradingViewAdapter()]


async def _collect_adapter(adapter) -> dict:
    out = {"accounts": 0, "calls": 0, "errors": []}
    try:
        drafts = await adapter.fetch_profiles()
        for d in drafts:
            await store.upsert_account(d.handle, d.source, d.display_name)
        out["accounts"] = len(drafts)
    except Exception as e:
        out["errors"].append(f"{adapter.source}: profiles: {e}")
    try:
        accounts = await store.list_accounts()
        if adapter.source == "tradingview":
            drafts = await adapter.fetch_calls(accounts)
        else:
            drafts = await adapter.fetch_calls(accounts)
        for d in drafts:
            acc = await store.get_account(d.account_handle)
            if acc is None:
                await store.upsert_account(d.account_handle, d.source)
                acc = await store.get_account(d.account_handle)
            _, created = await store.upsert_call(
                acc["id"],
                d.source,
                d.symbol,
                d.direction,
                d.entry_price,
                d.entry_time,
                d.source_call_id,
            )
            if created:
                out["calls"] += 1
    except Exception as e:
        out["errors"].append(f"{adapter.source}: calls: {e}")
    return out


async def collect_all(adapter_overrides=None) -> dict:
    adapters = adapter_overrides if adapter_overrides is not None else ADAPTERS
    total = {"profiles": 0, "accounts": 0, "calls": 0, "errors": []}
    for adapter in adapters:
        res = await _collect_adapter(adapter)
        total["accounts"] += res["accounts"]
        total["calls"] += res["calls"]
        total["profiles"] += res["accounts"]
        total["errors"].extend(res["errors"])
    return total
