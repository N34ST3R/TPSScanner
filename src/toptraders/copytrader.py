import json
import time
from pathlib import Path

from src.toptraders import store
from src.delivery import simulation
from src.store.config import TOP_TRADERS_MAX_CAP

DATA_DIR = Path(__file__).parent.parent.parent / "data"
COPY_STATE_FILE = DATA_DIR / "copytrade.json"

DEFAULT_STATE = {
    "positions": {},
    "config": {"max_per_trader": TOP_TRADERS_MAX_CAP},
}


def size_for(wr: float, cap: float = None) -> float:
    cap = cap if cap is not None else TOP_TRADERS_MAX_CAP
    return max(0.0, min(cap, cap * (wr - 0.50) / 0.50))


def load_copy_state() -> dict:
    if COPY_STATE_FILE.exists():
        with open(COPY_STATE_FILE, "r") as f:
            return json.load(f)
    return json.loads(json.dumps(DEFAULT_STATE))


def save_copy_state(state: dict):
    COPY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COPY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _trader_used(state: dict, handle: str) -> float:
    return sum(
        p["size"]
        for p in state["positions"].values()
        if p.get("account_handle") == handle and p.get("status") == "open"
    )


async def copy_call(call_id: int, wr: float = 0.75) -> dict:
    state = load_copy_state()
    calls = await store.list_open_calls()
    call = next((c for c in calls if c["id"] == call_id), None)
    if call is None:
        return {"success": False, "error": "Call not found or already settled"}
    handle = call["handle"]
    cap = state["config"].get("max_per_trader", TOP_TRADERS_MAX_CAP)
    used = _trader_used(state, handle)
    size = size_for(wr, cap)
    if used + size > cap:
        return {"success": False, "error": f"Per-trader cap ${cap:,.0f} reached"}
    price_data = await simulation.get_current_price(call["symbol"])
    price = price_data["price"]
    if price <= 0:
        return {"success": False, "error": "Could not get price"}
    quantity = max(1, int(size / price))
    result = await _to_thread(simulation.execute_buy, call["symbol"], quantity, price)
    if not result["success"]:
        return {"success": False, "error": result["error"]}
    state["positions"][f"{call_id}:{call['symbol']}"] = {
        "call_id": call_id,
        "account_handle": handle,
        "symbol": call["symbol"],
        "direction": call["direction"],
        "quantity": quantity,
        "size": round(quantity * price, 2),
        "entry_time": time.time(),
        "horizon_exit": 5,
        "status": "open",
        "entry_price": price,
    }
    save_copy_state(state)
    return {
        "success": True,
        "message": f"Copied {call['symbol']} @ ${price:.2f} ({quantity} qty)",
        "size": state["positions"][f"{call_id}:{call['symbol']}"]["size"],
    }


async def _to_thread(fn, *args):
    import asyncio

    return await asyncio.to_thread(fn, *args)


async def close_position(position_key: str, price: float) -> dict:
    state = load_copy_state()
    pos = state["positions"].get(position_key)
    if pos is None or pos["status"] != "open":
        return {"success": False, "error": "Position not open"}
    result = await _to_thread(
        simulation.execute_sell, pos["symbol"], pos["quantity"], price
    )
    if not result["success"]:
        return {"success": False, "error": result["error"]}
    pos["status"] = "closed"
    pos["close_time"] = time.time()
    pos["close_price"] = price
    save_copy_state(state)
    return {"success": True, "message": f"Closed {pos['symbol']}"}


async def close_due_positions(now=None) -> list:
    now = now if now is not None else time.time()
    state = load_copy_state()
    closed = []
    for key, pos in list(state["positions"].items()):
        if pos["status"] != "open":
            continue
        horizon = pos.get("horizon_exit", 5)
        if pos["entry_time"] + horizon * 86400 > now:
            continue
        settled = await store.get_settled_call(pos["call_id"])
        if settled is not None:
            price = (
                settled[f"pnl_{horizon}d" if False else "entry_price"]
                or pos["entry_price"]
            )
            # prefer the horizon's settle price: pnl maps are percentages, so use
            # entry * (1 + pnl_pct/100)
            price = _settle_price(pos, settled, horizon)
        else:
            pd = await simulation.get_current_price(pos["symbol"])
            price = pd["price"] or pos["entry_price"]
        res = await close_position(key, price)
        if res["success"]:
            closed.append(key)
    return closed


def _settle_price(pos: dict, settled, horizon: int) -> float:
    pnl_col = f"pnl_{horizon}d"
    if hasattr(settled, "keys"):
        pnl = settled[pnl_col] if pnl_col in settled.keys() else 0.0
    else:
        pnl = settled.get(pnl_col) or 0.0
    return pos["entry_price"] * (1 + pnl / 100)


async def get_copy_summary() -> dict:
    state = load_copy_state()
    open_positions = [p for p in state["positions"].values() if p["status"] == "open"]
    deployed = sum(p["size"] for p in open_positions)
    by_trader = {}
    for p in open_positions:
        h = p["account_handle"]
        by_trader[h] = by_trader.get(h, 0) + p["size"]
    return {
        "deployed": round(deployed, 2),
        "position_count": len(open_positions),
        "allocation": by_trader,
        "max_per_trader": state["config"].get("max_per_trader", TOP_TRADERS_MAX_CAP),
    }
