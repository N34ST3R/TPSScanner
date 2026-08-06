import pytest

from src.toptraders.adapters.tradingview import parse_ideas, TradingViewAdapter
from src.toptraders.adapters.twitter import TwitterAdapter

FIXTURE_HTML = """
<div class="tv-widget-idea js-idea" data-idea-id="12345">
  <div class="tv-widget-idea__header">
    <a class="tv-user-widget__link" href="/u/chartwiz">chartwiz</a>
    <span class="tv-widget-idea__signal-tag">long</span>
  </div>
  <div class="tv-widget-idea__ticker">AAPL</div>
</div>
<div class="tv-widget-idea js-idea" data-idea-id="67890">
  <div class="tv-widget-idea__header">
    <a class="tv-user-widget__link" href="/u/bearmach">bearmach</a>
    <span class="tv-widget-idea__signal-tag">short</span>
  </div>
  <div class="tv-widget-idea__ticker">TSLA</div>
</div>
"""


def test_parse_ideas_extracts_calls():
    calls = parse_ideas(FIXTURE_HTML)
    assert len(calls) == 2
    assert calls[0].account_handle == "chartwiz"
    assert calls[0].symbol == "AAPL"
    assert calls[0].direction == "long"
    assert calls[0].source_call_id == "tv-12345"
    assert calls[1].direction == "short"


def test_twitter_stub_raises():
    from src.toptraders.adapters.base import BaseAdapter

    tw = TwitterAdapter()
    assert isinstance(tw, BaseAdapter)
    assert tw.source == "twitter"
    with pytest.raises(NotImplementedError):
        import asyncio

        asyncio.run(tw.fetch_profiles())


@pytest.mark.asyncio
async def test_adapter_source_name():
    assert TradingViewAdapter().source == "tradingview"
