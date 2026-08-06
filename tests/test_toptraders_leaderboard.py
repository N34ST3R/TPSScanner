import json

import pytest
import pytest_asyncio

from src.toptraders import leaderboard
from src.toptraders import store


@pytest_asyncio.fixture
async def tmp_db(tmp_path):
    await store.close_tt_db()
    target = tmp_path / "test_tt.db"
    await store.get_tt_db(str(target))
    yield target
    await store.close_tt_db()


@pytest.mark.asyncio
async def test_leaderboard_ranking_and_gates(tmp_db):
    a1 = await store.upsert_account("alpha", "stocktwits")
    a2 = await store.upsert_account("beta", "polymarket")
    # alpha: 12 settled, 9 wins -> 75%
    for i in range(12):
        cid, _ = await store.upsert_call(
            a1, "stocktwits", f"S{i}", "long", 100.0, 1000.0 + i, f"a-{i}"
        )
        await store.insert_outcome(cid, 5, 101.0, 2000.0, 1.0, i < 9)
    # beta: only 5 settled -> below min calls gate
    for i in range(5):
        cid, _ = await store.upsert_call(
            a2, "polymarket", f"B{i}", "long", 100.0, 1000.0 + i, f"b-{i}"
        )
        await store.insert_outcome(cid, 5, 101.0, 2000.0, 1.0, i < 5)
    # pnl gate: alpha pnl_total must be >= 1000 -> set via ledger update directly
    await store.update_ledger(a1, 0, 12, 0, 0, 9, 0, 5000.0)

    lb = await leaderboard.compute_win_rate(horizon=5)
    assert len(lb) == 1
    assert lb[0]["handle"] == "alpha"
    assert lb[0]["win_rate"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_rebuild_writes_json(tmp_db, tmp_path, monkeypatch):
    out = tmp_path / "lb.json"
    monkeypatch.setattr(leaderboard, "LEADERBOARD_PATH", out)
    await leaderboard.rebuild_leaderboard(horizon=5)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "traders" in data and "generated_at" in data
