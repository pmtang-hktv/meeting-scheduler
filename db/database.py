from __future__ import annotations
import contextlib
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
    migration_path = os.path.join(os.path.dirname(__file__), "migrations", "001_initial.sql")
    with open(migration_path) as f:
        sql = f.read()
    async with get_db() as db:
        await db.executescript(sql)
        await db.commit()
