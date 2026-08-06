import asyncio
from datetime import datetime, timezone

import pytest

from src.toptraders.scheduler import (
    _next_collect_at,
    _settle_window_open,
)


def test_next_collect_at_baseline():
    now = 1000.0
    assert _next_collect_at(now, interval=1800) == 1000.0 + 1800


def test_settle_window_detection():
    # 21:59 UTC -> not open; 22:00 -> open
    dt_before = datetime(2026, 8, 6, 21, 59, tzinfo=timezone.utc)
    dt_open = datetime(2026, 8, 6, 22, 0, tzinfo=timezone.utc)
    dt_after = datetime(2026, 8, 6, 22, 20, tzinfo=timezone.utc)
    assert _settle_window_open(dt_before, settle_hour=22, window_min=20) is False
    assert _settle_window_open(dt_open, settle_hour=22, window_min=20) is True
    assert _settle_window_open(dt_after, settle_hour=22, window_min=20) is True
