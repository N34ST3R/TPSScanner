import pytest
import pytest_asyncio

from src.toptraders import store
from src.toptraders import collector
from src.toptraders.adapters.base import AccountDraft, CallDraft, BaseAdapter


@pytest_asyncio.fixture
async def tmp_db(tmp_path):
    await store.close_tt_db()
    await store.get_tt_db(str(tmp_path / "tt.db"))
    yield
    await store.close_tt_db()


class FakeAdapter(BaseAdapter):
    source = "fake"

    async def fetch_profiles(self):
        return [AccountDraft(handle="h1", source="fake", display_name="H One")]

    async def fetch_calls(self, accounts):
        return [
            CallDraft(
                account_handle="h1",
                source="fake",
                symbol="FAKE",
                direction="long",
                entry_price=10.0,
                entry_time=1000.0,
                source_call_id="fake-1",
            )
        ]


@pytest.mark.asyncio
async def test_collect_all_upserts_accounts_and_calls(tmp_db):
    result = await collector.collect_all(adapter_overrides=[FakeAdapter()])
    assert result["accounts"] == 1
    assert result["calls"] == 1
    open_calls = await store.list_open_calls()
    assert open_calls[0]["handle"] == "h1"
    # second run is idempotent
    result2 = await collector.collect_all(adapter_overrides=[FakeAdapter()])
    assert result2["calls"] == 0
    assert len(await store.list_open_calls()) == 1


@pytest.mark.asyncio
async def test_collect_all_survives_adapter_failure(tmp_db):
    class BrokenAdapter(BaseAdapter):
        source = "broken"

        async def fetch_profiles(self):
            raise RuntimeError("boom")

        async def fetch_calls(self, accounts):
            raise RuntimeError("boom")

    result = await collector.collect_all(adapter_overrides=[BrokenAdapter()])
    assert result["accounts"] == 0
    assert result["errors"]
