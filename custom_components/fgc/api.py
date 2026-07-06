"""Thin async client for the FGC open-data (Opendatasoft Explore v2.1) API."""
from __future__ import annotations

import re
from typing import Any

import aiohttp

from .const import API_BASE_URL, API_PAGE_SIZE, DATASET_SCHEDULE

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class FgcApiError(Exception):
    """Generic error talking to the FGC API."""


class FgcAuthError(FgcApiError):
    """The provided API key was rejected."""


class FgcApiClient:
    """Client for the `viajes-de-hoy` (today's timetable) FGC dataset."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None) -> None:
        self._session = session
        self._api_key = api_key or None

    async def _get(self, dataset: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Apikey {self._api_key}"
        url = f"{API_BASE_URL}/{dataset}/records"
        try:
            async with self._session.get(url, params=params, headers=headers) as resp:
                payload = await resp.json()
                if resp.status == 401 or (
                    isinstance(payload, dict) and payload.get("error") == "API key is not valid"
                ):
                    raise FgcAuthError("Invalid FGC API key")
                if resp.status != 200:
                    raise FgcApiError(
                        f"FGC API returned HTTP {resp.status}: {payload}"
                    )
                return payload
        except aiohttp.ClientError as err:
            raise FgcApiError(f"Error communicating with FGC API: {err}") from err

    async def _get_all_pages(
        self, dataset: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._get(
                dataset, {**params, "limit": API_PAGE_SIZE, "offset": offset}
            )
            rows = page.get("results", [])
            results.extend(rows)
            offset += len(rows)
            if not rows or offset >= page.get("total_count", 0):
                break
        return results

    async def async_get_stations(self) -> dict[str, str]:
        """Return a mapping of station code -> human-readable station name.

        A "station" is the `parent_station` shared by a stop's platforms, or
        the stop's own `stop_id` for single-platform termini that have no
        `parent_station`.
        """
        rows = await self._get_all_pages(
            DATASET_SCHEDULE,
            {
                "select": "parent_station, stop_id, stop_name",
                "group_by": "parent_station, stop_id, stop_name",
            },
        )
        stations: dict[str, str] = {}
        for row in rows:
            code = row.get("parent_station") or row.get("stop_id")
            name = row.get("stop_name")
            if code and name:
                stations[code] = name
        return stations

    async def async_get_day_schedule(self, station_code: str) -> list[dict[str, Any]]:
        """Return every scheduled stop-time at `station_code` for today."""
        if not _CODE_RE.match(station_code):
            raise FgcApiError(f"Invalid station code: {station_code!r}")
        where = f'parent_station="{station_code}" or stop_id="{station_code}"'
        return await self._get_all_pages(
            DATASET_SCHEDULE,
            {
                "where": where,
                "order_by": "departure_time asc",
                "select": (
                    "departure_time, route_short_name, trip_headsign, "
                    "platform_code, stop_name"
                ),
            },
        )
