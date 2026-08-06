import pytest

from src.toptraders.outcomes import classify_win, resolve_entry_price, settle_call


@pytest.mark.parametrize(
    "direction,entry,close,expected",
    [
        ("long", 100.0, 100.4, False),  # inside buffer -> loss
        ("long", 100.0, 100.6, True),
        ("long", 100.0, 99.0, False),
        ("bull", 100.0, 101.0, True),
        ("short", 100.0, 100.4, False),  # inside buffer -> loss
        ("short", 100.0, 99.3, True),
        ("bear", 100.0, 95.0, True),
    ],
)
def test_classify_win(direction, entry, close, expected):
    assert classify_win(direction, entry, close) is expected


def test_resolve_entry_price_missing_uses_first_close_after_entry():
    closes = [(1000.0, 10.0), (1100.0, 20.0), (1200.0, 30.0)]  # (price, ts)
    assert (
        resolve_entry_price(None, closes, entry_time=15.0) == 1100.0
    )  # first close >= entry time


def test_resolve_entry_price_present_keeps_it():
    closes = [(1000.0, 10.0), (1100.0, 20.0)]
    assert resolve_entry_price(1050.0, closes) == 1050.0


def test_resolve_entry_price_falls_back_to_last_close():
    closes = [(1000.0, 10.0)]
    assert resolve_entry_price(None, closes) == 1000.0


@pytest.mark.asyncio
async def test_settle_call_horizons_and_completion(tmp_path):
    import time

    from src.toptraders import store

    await store.close_tt_db()
    db = await store.get_tt_db(str(tmp_path / "tt.db"))
    aid = await store.upsert_account("pw", "polymarket")
    cid, _ = await store.upsert_call(
        aid, "polymarket", "AAPL>100", "bull", 1.0, time.time() - 2 * 86400, "pm-s1"
    )
    call = (await store.get_open_calls_needing_settlement())[0]

    # entry 1.0; 1d close 1.2 (win), 5d/30d not yet available
    async def provider(symbol, target_time):
        if target_time <= time.time():
            return 1.2
        return None

    result = await settle_call(call, provider)
    assert result["call_id"] == cid
    outcomes = await store.get_outcomes_for_call(cid)
    assert {o["horizon"] for o in outcomes} == {1}
    assert outcomes[0]["win"] == 1
    await store.close_tt_db()
