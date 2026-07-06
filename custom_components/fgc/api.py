"""Thin async client for the FGC open-data (Opendatasoft Explore v2.1) API."""
from __future__ import annotations

import re
from typing import Any, TypedDict

import aiohttp

from .const import (
    API_BASE_URL,
    API_PAGE_SIZE,
    DATASET_SCHEDULE,
    DATASET_STOPS,
    DATASET_VEHICLE_POSITIONS,
)

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class StationInfo(TypedDict):
    """A physical station: its display name and every platform stop_id it has."""

    name: str
    stop_ids: list[str]


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
        # Note: `total_count` is unreliable for `group_by` queries (it reflects
        # only the current page, not the true total), so pagination must stop
        # based on a short/empty page rather than comparing against it.
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._get(
                dataset, {**params, "limit": API_PAGE_SIZE, "offset": offset}
            )
            rows = page.get("results", [])
            results.extend(rows)
            offset += len(rows)
            if len(rows) < API_PAGE_SIZE:
                break
        return results

    async def async_get_stations(self) -> dict[str, StationInfo]:
        """Return a mapping of station code -> {name, stop_ids}.

        A "station" is every platform sharing a `parent_station`. Some
        termini have multiple platforms (e.g. one for arrivals, one for
        departures) with no `parent_station` linking them at all, so those
        are instead grouped by matching `stop_name`.
        """
        rows = await self._get_all_pages(
            DATASET_SCHEDULE,
            {
                "select": "parent_station, stop_id, stop_name",
                "group_by": "parent_station, stop_id, stop_name",
            },
        )
        groups: dict[tuple[str, str], StationInfo] = {}
        for row in rows:
            stop_id = row.get("stop_id")
            name = row.get("stop_name")
            parent = row.get("parent_station")
            if not stop_id or not name:
                continue
            key = ("parent", parent) if parent else ("name", name)
            group = groups.setdefault(key, StationInfo(name=name, stop_ids=[]))
            group["stop_ids"].append(stop_id)

        stations: dict[str, StationInfo] = {}
        for (kind, _value), info in groups.items():
            info["stop_ids"].sort()
            code = _value if kind == "parent" else info["stop_ids"][0]
            stations[code] = info
        return stations

    async def async_get_day_schedule(self, stop_ids: list[str]) -> list[dict[str, Any]]:
        """Return every scheduled stop-time at any of `stop_ids` for today."""
        if not stop_ids or not all(_CODE_RE.match(s) for s in stop_ids):
            raise FgcApiError(f"Invalid stop ids: {stop_ids!r}")
        where = " or ".join(f'stop_id="{s}"' for s in stop_ids)
        return await self._get_all_pages(
            DATASET_SCHEDULE,
            {
                "where": where,
                "order_by": "departure_time asc",
                "select": (
                    "stop_id, departure_time, route_short_name, trip_headsign, "
                    "platform_code, stop_name, route_color, route_text_color"
                ),
            },
        )

    async def async_get_vehicle_positions(self) -> list[dict[str, Any]]:
        """Return the current Geotren position record for every active train."""
        return await self._get_all_pages(DATASET_VEHICLE_POSITIONS, {})

    async def async_get_station_names(self) -> dict[str, str]:
        """Return every stop_id -> stop_name in the network.

        Includes the bare parent-station codes (e.g. "PC") used by the
        vehicle-position feed's origin/destination/next-stop fields, which
        aren't reachable through `async_get_stations` (that one is built
        from `viajes-de-hoy`'s stop_times rows, which never reference a bare
        parent code directly).
        """
        rows = await self._get_all_pages(DATASET_STOPS, {"select": "stop_id, stop_name"})
        return {
            row["stop_id"]: row["stop_name"]
            for row in rows
            if row.get("stop_id") and row.get("stop_name")
        }
