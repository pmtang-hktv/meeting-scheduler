from __future__ import annotations
import asyncio
import googlemaps
from db.database import get_db

_CACHE_TTL_DAYS = 7


async def get_travel_minutes(
    origin: str, destination_area: str, gmaps_key: str
) -> int | None:
    cached = await _get_cached(destination_area)
    if cached is not None:
        return cached
    result = await asyncio.get_event_loop().run_in_executor(
        None, _fetch_from_maps, origin, destination_area, gmaps_key
    )
    if result is not None:
        await _cache_result(destination_area, result)
    return result


def _fetch_from_maps(origin: str, destination: str, api_key: str) -> int | None:
    try:
        client = googlemaps.Client(key=api_key)
        matrix = client.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            units="metric",
        )
        element = matrix["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return None
        return element["duration"]["value"] // 60  # seconds → minutes
    except Exception:
        return None


async def _get_cached(destination_area: str) -> int | None:
    async with await get_db() as db:
        async with db.execute(
            """
            SELECT travel_mins FROM travel_cache
            WHERE destination_area = ?
              AND datetime(cached_at, '+7 days') > datetime('now')
            """,
            (destination_area,),
        ) as cur:
            row = await cur.fetchone()
            return row["travel_mins"] if row else None


async def _cache_result(destination_area: str, travel_mins: int) -> None:
    async with await get_db() as db:
        await db.execute(
            """
            INSERT INTO travel_cache (destination_area, travel_mins)
            VALUES (?, ?)
            ON CONFLICT(destination_area) DO UPDATE SET
                travel_mins = excluded.travel_mins,
                cached_at   = datetime('now')
            """,
            (destination_area, travel_mins),
        )
        await db.commit()
