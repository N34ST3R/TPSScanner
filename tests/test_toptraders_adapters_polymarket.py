import pytest

from src.toptraders.adapters.polymarket import (
    parse_profiles,
    parse_calls,
    PolymarketAdapter,
)

FIXTURE_LEADERBOARD = {
    "data": [
        {"address": "0xaaa", "display_name": "Poly Whale", "volume": 12345.0},
        {"address": "0xbbb", "display_name": "Shark", "volume": 9000.0},
    ]
}

FIXTURE_TRADES = {
    "data": [
        {
            "user": "0xaaa",
            "side": "BUY",
            "size": 10.0,
            "price": 0.55,
            "timestamp": 1750000000,
            "market": {
                "ticker": "AAPL>150-2026-09-01",
                "question": "AAPL above 150 by Sept?",
            },
        },
        {
            "user": "0xaaa",
            "side": "SELL",
            "size": 5.0,
            "price": 0.40,
            "timestamp": 1750001000,
            "market": {"ticker": "ETH>4000-2026-09-01", "question": "ETH above 4000?"},
        },
    ]
}


def test_parse_profiles():
    profiles = parse_profiles(FIXTURE_LEADERBOARD)
    assert len(profiles) == 2
    assert profiles[0].handle == "0xaaa"
    assert profiles[0].display_name == "Poly Whale"


def test_parse_calls_buy_is_bull():
    calls = parse_calls(FIXTURE_TRADES)
    assert len(calls) == 2
    assert calls[0].symbol == "AAPL>150-2026-09-01"
    assert calls[0].direction == "bull"
    assert calls[0].source_call_id == "0xaaa-1750000000-AAPL>150-2026-09-01-BUY"
    assert calls[1].direction == "bear"


@pytest.mark.asyncio
async def test_adapter_source_name():
    assert PolymarketAdapter().source == "polymarket"
