import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "toptraders.db"

_db = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1,
    copy_enabled INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL,
    entry_time REAL,
    source_call_id TEXT,
    status TEXT DEFAULT 'open',
    UNIQUE(source, source_call_id)
);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL,
    horizon INTEGER NOT NULL,
    settle_price REAL,
    settle_time REAL,
    pnl_pct REAL,
    win INTEGER,
    UNIQUE(call_id, horizon)
);
CREATE TABLE IF NOT EXISTS settled_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    entry_price REAL,
    entry_time REAL,
    win_1d INTEGER, win_5d INTEGER, win_30d INTEGER,
    pnl_1d REAL, pnl_5d REAL, pnl_30d REAL,
    settle_time REAL
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL UNIQUE,
    settled_1d INTEGER DEFAULT 0,
    settled_5d INTEGER DEFAULT 0,
    settled_30d INTEGER DEFAULT 0,
    wins_1d INTEGER DEFAULT 0,
    wins_5d INTEGER DEFAULT 0,
    wins_30d INTEGER DEFAULT 0,
    pnl_total REAL DEFAULT 0,
    last_settle_time REAL
);
"""


async def get_tt_db(path=None) -> aiosqlite.Connection:
    global _db
    if _db is None:
        db_path = Path(path) if path else DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.executescript(SCHEMA)
        await _db.commit()
    return _db


async def close_tt_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def upsert_account(handle: str, source: str, display_name: str = "") -> int:
    db = await get_tt_db()
    await db.execute(
        "INSERT INTO accounts (handle, source, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(handle) DO UPDATE SET display_name=excluded.display_name",
        (handle, source, display_name),
    )
    await db.commit()
    async with db.execute("SELECT id FROM accounts WHERE handle = ?", (handle,)) as cur:
        row = await cur.fetchone()
        return row["id"]


async def set_copy_enabled(handle: str, enabled: bool):
    db = await get_tt_db()
    await db.execute(
        "UPDATE accounts SET copy_enabled = ? WHERE handle = ?", (int(enabled), handle)
    )
    await db.commit()


async def get_account(handle: str):
    db = await get_tt_db()
    async with db.execute("SELECT * FROM accounts WHERE handle = ?", (handle,)) as cur:
        return await cur.fetchone()


async def list_accounts() -> list:
    db = await get_tt_db()
    async with db.execute("SELECT * FROM accounts ORDER BY joined_at") as cur:
        return await cur.fetchall()


async def upsert_call(
    account_id: int,
    source: str,
    symbol: str,
    direction: str,
    entry_price,
    entry_time,
    source_call_id: str,
) -> tuple:
    db = await get_tt_db()
    async with db.execute(
        "SELECT id FROM calls WHERE source = ? AND source_call_id = ?",
        (source, source_call_id),
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        return existing["id"], False
    await db.execute(
        "INSERT INTO calls (account_id, source, symbol, direction, entry_price, entry_time, source_call_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            account_id,
            source,
            symbol,
            direction,
            entry_price,
            entry_time,
            source_call_id,
        ),
    )
    await db.commit()
    async with db.execute(
        "SELECT id FROM calls WHERE source = ? AND source_call_id = ?",
        (source, source_call_id),
    ) as cur:
        row = await cur.fetchone()
        return row["id"], True


async def list_open_calls() -> list:
    db = await get_tt_db()
    await db.execute(
        "UPDATE calls SET entry_price = 0 WHERE entry_price IS NULL"
    )  # safety: ensure non-null for calcs
    await db.commit()
    async with db.execute(
        "SELECT c.*, a.handle, a.source AS account_source, a.display_name "
        "FROM calls c JOIN accounts a ON a.id = c.account_id "
        "WHERE c.status = 'open' ORDER BY c.entry_time DESC"
    ) as cur:
        return await cur.fetchall()


async def get_open_calls_needing_settlement() -> list:
    db = await get_tt_db()
    async with db.execute(
        "SELECT c.*, a.handle FROM calls c JOIN accounts a ON a.id = c.account_id "
        "WHERE c.status = 'open' AND c.entry_time > 0"
    ) as cur:
        return await cur.fetchall()


async def mark_call_settled(call_id: int):
    db = await get_tt_db()
    await db.execute("UPDATE calls SET status = 'settled' WHERE id = ?", (call_id,))
    await db.commit()


async def insert_outcome(
    call_id: int, horizon: int, settle_price, settle_time, pnl_pct, win: bool
):
    db = await get_tt_db()
    await db.execute(
        "INSERT OR REPLACE INTO outcomes (call_id, horizon, settle_price, settle_time, pnl_pct, win) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (call_id, horizon, settle_price, settle_time, pnl_pct, int(win)),
    )
    await db.commit()


async def get_outcomes_for_call(call_id: int) -> list:
    db = await get_tt_db()
    async with db.execute(
        "SELECT * FROM outcomes WHERE call_id = ? ORDER BY horizon", (call_id,)
    ) as cur:
        return await cur.fetchall()


async def save_settled_call(
    call_id, account_id, symbol, entry_price, entry_time, wins, pnls, settle_time
):
    db = await get_tt_db()
    await db.execute(
        "INSERT OR REPLACE INTO settled_calls (call_id, account_id, symbol, entry_price, entry_time, "
        "win_1d, win_5d, win_30d, pnl_1d, pnl_5d, pnl_30d, settle_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            call_id,
            account_id,
            symbol,
            entry_price,
            entry_time,
            wins[0],
            wins[1],
            wins[2],
            pnls[0],
            pnls[1],
            pnls[2],
            settle_time,
        ),
    )
    await db.commit()


async def get_settled_call(call_id: int):
    db = await get_tt_db()
    async with db.execute(
        "SELECT * FROM settled_calls WHERE call_id = ?", (call_id,)
    ) as cur:
        return await cur.fetchone()


async def update_ledger(
    account_id,
    settled_1d,
    settled_5d,
    settled_30d,
    wins_1d,
    wins_5d,
    wins_30d,
    pnl_total,
):
    db = await get_tt_db()
    await db.execute(
        "INSERT INTO ledger (account_id, settled_1d, settled_5d, settled_30d, wins_1d, wins_5d, wins_30d, pnl_total, last_settle_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now')) "
        "ON CONFLICT(account_id) DO UPDATE SET "
        "settled_1d=excluded.settled_1d, settled_5d=excluded.settled_5d, settled_30d=excluded.settled_30d, "
        "wins_1d=excluded.wins_1d, wins_5d=excluded.wins_5d, wins_30d=excluded.wins_30d, "
        "pnl_total=excluded.pnl_total, last_settle_time=excluded.last_settle_time",
        (
            account_id,
            settled_1d,
            settled_5d,
            settled_30d,
            wins_1d,
            wins_5d,
            wins_30d,
            pnl_total,
        ),
    )
    await db.commit()


async def get_ledger(account_id: int):
    db = await get_tt_db()
    async with db.execute(
        "SELECT * FROM ledger WHERE account_id = ?", (account_id,)
    ) as cur:
        return await cur.fetchone()


async def all_ledgers() -> list:
    db = await get_tt_db()
    async with db.execute("SELECT * FROM ledger ORDER BY pnl_total DESC") as cur:
        return await cur.fetchall()


async def get_account_by_id(account_id: int):
    db = await get_tt_db()
    async with db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)) as cur:
        return await cur.fetchone()
