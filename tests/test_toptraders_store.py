import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from src.toptraders import store


@pytest_asyncio.fixture
async def tmp_db(tmp_path):
    await store.close_tt_db()
    target = tmp_path / "test_tt.db"
    await store.get_tt_db(str(target))
    yield target
    await store.close_tt_db()


@pytest.mark.asyncio
async def test_schema_created(tmp_db):
    db = await store.get_tt_db(str(tmp_db))
    tables = set()
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        tables = {r[0] for r in await cur.fetchall()}
    assert {"accounts", "calls", "outcomes", "settled_calls", "ledger"} <= tables


@pytest.mark.asyncio
async def test_account_upsert_and_copy_toggle(tmp_db):
    aid = await store.upsert_account("pw", "polymarket", "Poly Whale")
    aid2 = await store.upsert_account("pw", "polymarket", "Poly Whale")
    assert aid == aid2
    await store.set_copy_enabled("pw", True)
    acc = await store.get_account("pw")
    assert acc["copy_enabled"] == 1


@pytest.mark.asyncio
async def test_call_dedupe_on_source_call_id(tmp_db):
    aid = await store.upsert_account("pw", "polymarket")
    cid, created1 = await store.upsert_call(
        aid, "polymarket", "AAPL>100", "bull", 1.0, 1000.0, "pm-1"
    )
    _, created2 = await store.upsert_call(
        aid, "polymarket", "AAPL>100", "bull", 1.0, 1000.0, "pm-1"
    )
    assert created1 is True and created2 is False
    assert cid is not None


@pytest.mark.asyncio
async def test_open_calls_listing_and_settle(tmp_db):
    aid = await store.upsert_account("pw", "polymarket")
    cid, _ = await store.upsert_call(
        aid, "polymarket", "AAPL>100", "bull", 1.0, 1000.0, "pm-2"
    )
    open_calls = await store.list_open_calls()
    assert any(c["id"] == cid for c in open_calls)
    await store.insert_outcome(cid, 5, 1.1, 1600.0, 10.0, 1)
    await store.mark_call_settled(cid)
    outcomes = await store.get_outcomes_for_call(cid)
    assert len(outcomes) == 1 and outcomes[0]["horizon"] == 5
    assert store.get_settled_call  # defined
