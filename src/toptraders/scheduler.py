import asyncio
import time as time_mod
from datetime import datetime, timezone

from src.toptraders import collector, copytrader, leaderboard, outcomes

COLLECT_INTERVAL = 1800
SETTLE_HOUR_UTC = 22
REBUILD_MIN_OFFSET = 15
SETTLE_WINDOW_MIN = 20


def _next_collect_at(now: float, interval: int = COLLECT_INTERVAL) -> float:
    return now + interval


def _settle_window_open(
    dt, settle_hour: int = SETTLE_HOUR_UTC, window_min: int = SETTLE_WINDOW_MIN
) -> bool:
    hour, minute = dt.hour, dt.minute
    start = settle_hour * 60
    end = settle_hour * 60 + window_min
    pos = hour * 60 + minute
    return start <= pos <= end


async def run_scheduler(collect_interval=None, settle_hour=None, window_min=None):
    collect_interval = collect_interval or COLLECT_INTERVAL
    settle_hour = settle_hour or SETTLE_HOUR_UTC
    window_min = window_min or SETTLE_WINDOW_MIN
    next_collect = _next_collect_at(time_mod.time(), collect_interval)
    while True:
        now = time_mod.time()
        if now >= next_collect:
            print("[toptraders] collecting calls...")
            try:
                res = await collector.collect_all()
                print(f"[toptraders] collected: {res}")
            except Exception as e:
                print(f"[toptraders] collect error: {e}")
            next_collect = _next_collect_at(now, collect_interval)
        dt = datetime.now(timezone.utc)
        if _settle_window_open(dt, settle_hour, window_min):
            print("[toptraders] settling outcomes...")
            try:
                res = await outcomes.settle_all_open()
                print(f"[toptraders] settled: {res}")
            except Exception as e:
                print(f"[toptraders] settle error: {e}")
            try:
                lb = await leaderboard.rebuild_leaderboard()
                print(f"[toptraders] leaderboard: {lb['summary']}")
            except Exception as e:
                print(f"[toptraders] rebuild error: {e}")
            try:
                closed = await copytrader.close_due_positions()
                print(f"[toptraders] closed {len(closed)} copy positions")
            except Exception as e:
                print(f"[toptraders] copy error: {e}")
            await asyncio.sleep(60)
        await asyncio.sleep(30)
