from __future__ import annotations
import contextlib
import glob
import os
import aiosqlite


_DB_PATH: str = ""


def configure(db_path: str) -> None:
    global _DB_PATH
    _DB_PATH = db_path


@contextlib.asynccontextmanager
async def get_db():
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db(db_path: str) -> None:
    configure(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    # Run every migration in filename order. All statements use CREATE ... IF NOT
    # EXISTS, so re-running on an existing database is a no-op.
    async with get_db() as db:
        for path in sorted(glob.glob(os.path.join(migrations_dir, "*.sql"))):
            with open(path) as f:
                await db.executescript(f.read())
        # Columns added to existing tables after first release. CREATE ... IF NOT
        # EXISTS won't add them to a DB that already has the table, and SQLite lacks
        # ADD COLUMN IF NOT EXISTS, so apply these idempotently here.
        await _ensure_column(db, "day_offs", "half_day", "TEXT")
        await db.commit()


async def _ensure_column(db, table: str, column: str, decl: str) -> None:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    if column not in existing:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
