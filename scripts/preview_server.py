"""Lightweight launcher - dashboard only, on a configurable port.

Used for local preview without the MCP server or background scanner.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.store.database import get_db, close_db
from src.delivery.dashboard import app


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    await get_db()
    from src.main import seed_watchlist

    await seed_watchlist()
    print(f"Preview dashboard: http://127.0.0.1:{port}")
    await app.run_task(host="127.0.0.1", port=port)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
