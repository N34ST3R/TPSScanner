import json
import time
from pathlib import Path

from src.toptraders import store
from src.store.config import TOP_TRADERS_MIN_CALLS, TOP_TRADERS_MIN_PNL

LEADERBOARD_PATH = (
    Path(__file__).parent.parent.parent / "data" / "toptraders" / "leaderboard.json"
)

HORIZON_SUFFIX = {1: "1d", 5: "5d", 30: "30d"}
SETTLED_COL = {1: "settled_1d", 5: "settled_5d", 30: "settled_30d"}
WINS_COL = {1: "wins_1d", 5: "wins_5d", 30: "wins_30d"}


def _eligible(ledger, horizon: int, min_calls: int, min_pnl: float) -> bool:
    settled = ledger[SETTLED_COL[horizon]]
    return settled >= min_calls and (ledger["pnl_total"] or 0) >= min_pnl


async def compute_win_rate(horizon: int = 5) -> list[dict]:
    ledgers = await store.all_ledgers()
    rows = []
    for led in ledgers:
        if not _eligible(led, horizon, TOP_TRADERS_MIN_CALLS, TOP_TRADERS_MIN_PNL):
            continue
        settled = led[SETTLED_COL[horizon]]
        wins = led[WINS_COL[horizon]]
        acct = await store.get_account_by_id(led["account_id"])
        account = dict(acct) if acct else {}
        rows.append(
            {
                "rank": 0,
                "handle": account.get("handle", f"id{led['account_id']}"),
                "display_name": account.get("display_name", ""),
                "source": account.get("source", ""),
                "win_rate": round(wins / settled, 4) if settled else 0.0,
                "wins": wins,
                "settled": settled,
                "pnl_total": round(led["pnl_total"] or 0, 2),
                "copy_enabled": bool(account.get("copy_enabled")),
            }
        )
    rows.sort(key=lambda r: (-r["win_rate"], -r["pnl_total"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


async def rebuild_leaderboard(horizon: int = 5) -> dict:
    traders = await compute_win_rate(horizon)
    summary = {
        "tracked": len(await store.list_accounts()),
        "eligible": len(traders),
        "pooled_win_rate": (
            round(
                sum(t["wins"] for t in traders) / sum(t["settled"] for t in traders), 4
            )
            if traders and sum(t["settled"] for t in traders)
            else 0.0
        ),
    }
    result = {
        "generated_at": time.time(),
        "horizon": horizon,
        "traders": traders,
        "summary": summary,
    }
    LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_PATH.write_text(json.dumps(result, indent=2))
    return result
