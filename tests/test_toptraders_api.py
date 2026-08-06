import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from src.toptraders import store, leaderboard
from src.delivery import simulation
from src.delivery.dashboard import app


@pytest_asyncio.fixture
async def client(tmp_path):
    await store.close_tt_db()
    store.DB_PATH = tmp_path / "tt.db"
    app.config["TESTING"] = True
    yield app.test_client()
    await store.close_tt_db()


@pytest.mark.asyncio
async def test_picks_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        simulation, "get_current_price", AsyncMock(return_value={"price": 100.0})
    )
    await store.get_tt_db()
    aid = await store.upsert_account("api-trader", "stocktwits", "API Trader")
    await store.upsert_call(aid, "stocktwits", "NVDA", "long", 0.0, 1000.0, "api-1")
    resp = await client.get("/api/toptraders/picks")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert len(data["picks"]) == 1
    assert data["picks"][0]["handle"] == "api-trader"


@pytest.mark.asyncio
async def test_leaderboard_endpoint_empty_ok(client, monkeypatch, tmp_path):
    monkeypatch.setattr(leaderboard, "LEADERBOARD_PATH", tmp_path / "leaderboard.json")
    resp = await client.get("/api/toptraders/leaderboard")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert "traders" in data


@pytest.mark.asyncio
async def test_copy_endpoint(client):
    resp = await client.get("/api/toptraders/copy")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert "deployed" in data


@pytest.mark.asyncio
async def test_toggle_copy_endpoint(client):
    await store.upsert_account("tog-trader", "polymarket")
    resp = await client.post("/api/toptraders/accounts/tog-trader/toggle")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["copy_enabled"] == 1
    acc = await store.get_account("tog-trader")
    assert acc["copy_enabled"] == 1
