import pytest

from src.toptraders.adapters.stocktwits import parse_profiles, parse_calls

FIXTURE_TRENDING = {
    "messages": [
        {
            "id": 101,
            "body": "NVDA looking strong",
            "user": {"username": "alphaninja", "name": "Alpha Ninja"},
            "entities": {
                "symbols": [{"symbol": "NVDA"}],
                "sentiment": {"basic": "Bullish"},
            },
        },
        {
            "id": 102,
            "body": "TSLA overvalued",
            "user": {"username": "bearspeak", "name": "Bear Speak"},
            "entities": {
                "symbols": [{"symbol": "TSLA"}],
                "sentiment": {"basic": "Bearish"},
            },
        },
        {
            "id": 103,
            "body": "no opinion here",
            "user": {"username": "neutralguy"},
            "entities": {"symbols": [], "sentiment": {"basic": "Neutral"}},
        },
    ]
}


def test_parse_profiles_from_trending():
    profiles = parse_profiles(FIXTURE_TRENDING)
    assert {p.handle for p in profiles} == {"alphaninja", "bearspeak", "neutralguy"}
    assert profiles[0].source == "stocktwits"


def test_parse_calls_direction_and_dedupe():
    calls = parse_calls(FIXTURE_TRENDING, "alphaninja")
    assert len(calls) == 1
    assert calls[0].symbol == "NVDA"
    assert calls[0].direction == "long"
    assert calls[0].entry_price == 0  # backfilled at settlement
    assert calls[0].source_call_id == "alphaninja-101"


def test_parse_calls_ignores_no_sentiment():
    calls = parse_calls(FIXTURE_TRENDING, "bearspeak")
    assert len(calls) == 1 and calls[0].direction == "short"
