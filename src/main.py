import asyncio
import json
import signal as sig
import sys
from pathlib import Path


def _json_default(o):
    """Numpy-safe JSON serializer (np.int32/np.float64 -> native)."""
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.database import get_db, close_db
from src.delivery.dashboard import app as dashboard_app
from src.delivery.mcp_server import mcp
from src.analysis.signal import scan_watchlist as do_scan_watchlist
from src.toptraders.scheduler import run_scheduler as run_tt_scheduler


async def seed_watchlist():
    """Seed the scan watchlist with sensible defaults so signals flow on first run.

    Merges (never wipes): any user-added symbols are kept, defaults are ensured
    present so the background scanner always has a varied universe to scan.
    """
    from src.delivery.simulation import DEFAULT_WATCHLIST

    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM watchlist")
    count = (await cursor.fetchone())[0]
    added = 0
    for sym in DEFAULT_WATCHLIST:
        cur = await db.execute(
            "INSERT OR IGNORE INTO watchlist (symbol, source) VALUES (?, ?)",
            (sym, "auto"),
        )
        added += cur.rowcount
    if added:
        await db.commit()
        print(f"Seeded watchlist: {added} default symbols merged (had {count} before).")


_scan_lock = asyncio.Lock()


async def scan_once():
    """One full watchlist scan + DB write. Shared by the loop and the boot warm-up.

    Locked so overlapping callers (the 5-min loop + the boot warm-up + manual
    scans) never hammer Yahoo with concurrent batches.
    """
    if _scan_lock.locked():
        return 0
    async with _scan_lock:
        db = await get_db()
        cursor = await db.execute("SELECT symbol FROM watchlist")
        rows = await cursor.fetchall()
        symbols = [r[0] for r in rows]
        if symbols:
            results = await do_scan_watchlist(symbols)
            for r in results:
                await db.execute(
                    "INSERT INTO signals (symbol, source, score, label, net_direction, patterns, indicators, timeframe) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r["symbol"],
                        "yahoo",
                        r["score"],
                        r["label"],
                        r["net_direction"],
                        json.dumps(r.get("patterns", []), default=_json_default),
                        json.dumps(r.get("indicators", {}), default=_json_default),
                        r.get("timeframe", "5m"),
                    ),
                )
            await db.commit()
            # Keep the DB lean: retain the most recent 500 signals overall and
            # drop stale rows for symbols that left the watchlist.
            await db.execute(
                "DELETE FROM signals WHERE id NOT IN (SELECT id FROM signals ORDER BY id DESC LIMIT 500)"
            )
            await db.commit()
        return len(symbols)


async def background_scanner():
    while True:
        try:
            await scan_once()
        except Exception as e:
            print(f"Scanner error: {e}")
        await asyncio.sleep(300)


async def run_dashboard():
    await dashboard_app.run_task(host="0.0.0.0", port=5000)


async def run_mcp():
    await mcp.run_async()


async def main():
    await get_db()
    await seed_watchlist()
    # Kick a first scan shortly after boot so the dashboard has varied signals
    # within ~15 seconds instead of waiting for the 5-minute cadence.
    try:
        import asyncio

        async def _first_scan():
            await asyncio.sleep(12)
            try:
                await scan_once()
            except Exception:
                pass

        asyncio.create_task(_first_scan())
    except Exception:
        pass
    print("Trading Pattern Scanner starting...")
    print("Dashboard: http://localhost:5000")
    print("MCP Server: http://localhost:8001")

    tasks = [
        asyncio.create_task(background_scanner()),
        asyncio.create_task(run_dashboard()),
        asyncio.create_task(run_mcp()),
        asyncio.create_task(run_tt_scheduler()),
    ]

    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for s in (sig.SIGINT, sig.SIGTERM):
            loop.add_signal_handler(s, lambda: [t.cancel() for t in tasks])

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await close_db()
        print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
