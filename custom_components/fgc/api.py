"""Thin async client for the FGC open-data (Opendatasoft Explore v2.1) API."""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, TypedDict

import aiohttp
from google.transit import gtfs_realtime_pb2

from .const import (
    API_BASE_URL,
    API_PAGE_SIZE,
    DATASET_AIR_QUALITY,
    DATASET_ALERTS,
    DATASET_CARBON_FOOTPRINT,
    DATASET_SCHEDULE,
    DATASET_SKI_ALERTS,
    DATASET_SKI_FACILITIES,
    DATASET_SKI_PARKING,
    DATASET_SKI_WEATHER,
    DATASET_SKI_WEBCAMS,
    DATASET_STOPS,
    DATASET_TRIP_UPDATES,
    DATASET_VEHICLE_POSITIONS,
)

_LOGGER = logging.getLogger(__name__)

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Safety net against a runaway pagination loop (e.g. a server bug that never
# returns a short page). No real dataset here should ever need this many
# pages; hitting it means something is wrong and we should give up loudly.
_MAX_PAGES = 100

# Warn once the anonymous/keyed daily quota drops below this fraction
# remaining, so a user heading towards HTTP 429s gets a clue why before
# their sensors start failing to refresh.
_LOW_QUOTA_THRESHOLD = 0.1

# Applied to every outbound request (the FGC API itself, and any URL it
# hands back to us, e.g. the GTFS-RT feed file). Without this, a stalled
# upstream would hang the coordinator indefinitely instead of failing and
# retrying on its normal schedule.
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

# How much of a non-200/unparsable response body to fold into our own
# exception message — enough to be useful in the log, not enough for a
# verbose/malicious upstream to bloat it.
_ERROR_BODY_MAX_CHARS = 300

# The FGC API always hands back absolute URLs for secondary downloads (the
# GTFS-RT feed file, ski webcam stills). Refusing anything but https guards
# against ever being redirected into fetching an internal/non-https
# resource if that upstream data were ever tampered with.
_ALLOWED_URL_SCHEMES = {"https"}

# Hard ceiling on a single GTFS-RT feed download, so a misbehaving or
# compromised upstream can't make us buffer an unbounded response into
# memory before protobuf-parsing it. The real feed is on the order of a
# few hundred KB.
_MAX_FEED_BYTES = 20 * 1024 * 1024


def _require_https(url: str, what: str) -> None:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise FgcApiError(f"Refusing to fetch {what}: non-https URL ({url!r})")


def _truncate_body(payload: Any) -> str:
    text = str(payload)
    if len(text) > _ERROR_BODY_MAX_CHARS:
        text = text[:_ERROR_BODY_MAX_CHARS] + "…"
    return text


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
        self._low_quota_warned = False

    async def _get(self, dataset: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Apikey {self._api_key}"
        url = f"{API_BASE_URL}/{dataset}/records"
        try:
            async with self._session.get(
                url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
            ) as resp:
                try:
                    payload = await resp.json()
                except (aiohttp.ContentTypeError, ValueError) as err:
                    # ValueError covers json.JSONDecodeError: a malformed or
                    # truncated body (e.g. from a flaky upstream) shouldn't
                    # surface as a raw, unexpected exception type.
                    raise FgcApiError(
                        f"FGC API returned an unparsable response (HTTP {resp.status}): {err}"
                    ) from err
                if resp.status == 401 or (
                    isinstance(payload, dict) and payload.get("error") == "API key is not valid"
                ):
                    raise FgcAuthError("Invalid FGC API key")
                if resp.status != 200:
                    raise FgcApiError(
                        f"FGC API returned HTTP {resp.status}: {_truncate_body(payload)}"
                    )
                self._check_rate_limit(resp.headers)
                return payload
        except aiohttp.ClientError as err:
            raise FgcApiError(f"Error communicating with FGC API: {err}") from err
        except TimeoutError as err:
            raise FgcApiError(f"Timed out communicating with FGC API: {err}") from err

    def _check_rate_limit(self, headers: Any) -> None:
        """Warn once when the daily quota is running low, so a user sees a
        clear reason before refreshes start failing outright."""
        try:
            remaining = int(headers["X-RateLimit-Remaining"])
            limit = int(headers["X-RateLimit-Limit"])
        except (KeyError, TypeError, ValueError):
            return
        if limit <= 0:
            return
        low = remaining / limit < _LOW_QUOTA_THRESHOLD
        if low and not self._low_quota_warned:
            self._low_quota_warned = True
            _LOGGER.warning(
                "FGC open-data API quota running low: %d/%d requests remaining "
                "today. Consider adding your own API key, removing some "
                "stations, or turning off the live map/ski sensors "
                "(Configure -> Settings) to reduce usage.",
                remaining,
                limit,
            )
        elif not low:
            self._low_quota_warned = False

    async def _get_all_pages(
        self, dataset: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # Note: `total_count` is unreliable for `group_by` queries (it reflects
        # only the current page, not the true total), so pagination must stop
        # based on a short/empty page rather than comparing against it.
        results: list[dict[str, Any]] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            page = await self._get(
                dataset, {**params, "limit": API_PAGE_SIZE, "offset": offset}
            )
            rows = page.get("results", [])
            results.extend(rows)
            offset += len(rows)
            if len(rows) < API_PAGE_SIZE:
                return results
        raise FgcApiError(
            f"Gave up paging '{dataset}' after {_MAX_PAGES} pages "
            f"({len(results)} rows) — the API may be misbehaving."
        )

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

    async def async_get_ski_facilities(self) -> list[dict[str, Any]]:
        """Return the open/closed status of every lift/facility at every
        FGC-operated ski resort (La Molina, Vall de Núria, Vallter, Espot,
        Port Ainé, Boí Taüll)."""
        return await self._get_all_pages(DATASET_SKI_FACILITIES, {})

    async def async_get_ski_weather(self) -> list[dict[str, Any]]:
        """Return the latest weather reading(s) for each ski resort."""
        return await self._get_all_pages(DATASET_SKI_WEATHER, {})

    async def async_get_ski_alerts(self) -> list[dict[str, Any]]:
        """Return every service alert (active or not) for the ski resorts."""
        return await self._get_all_pages(DATASET_SKI_ALERTS, {})

    async def async_get_ski_webcams(self) -> list[dict[str, Any]]:
        """Return every webcam entry (active or not) for the ski resorts."""
        return await self._get_all_pages(DATASET_SKI_WEBCAMS, {})

    async def async_get_realtime_departures(self) -> dict[str, list[int]]:
        """Return stop_id -> a list of live-predicted departure times (Unix
        epoch seconds), from the GTFS-Realtime Trip Updates feed.

        Unlike the other datasets, this one is a binary protobuf file rather
        than a JSON records endpoint: first look up its current download
        URL (the file is republished frequently, and nothing guarantees its
        id/URL stays stable), then fetch and parse that.
        """
        meta = await self._get(DATASET_TRIP_UPDATES, {"limit": 1})
        results = meta.get("results", [])
        file_info = results[0].get("file") if results else None
        file_url = file_info.get("url") if file_info else None
        if not file_url:
            raise FgcApiError("GTFS-RT trip-updates feed has no file to download")
        _require_https(file_url, "the GTFS-RT trip-updates feed")

        try:
            async with self._session.get(file_url, timeout=_REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    raise FgcApiError(
                        f"Could not download GTFS-RT trip updates (HTTP {resp.status})"
                    )
                content_length = resp.content_length
                if content_length is not None and content_length > _MAX_FEED_BYTES:
                    raise FgcApiError(
                        f"GTFS-RT trip-updates feed is too large "
                        f"({content_length} bytes > {_MAX_FEED_BYTES} limit); refusing to "
                        "download it"
                    )
                data = await resp.content.read(_MAX_FEED_BYTES + 1)
                if len(data) > _MAX_FEED_BYTES:
                    raise FgcApiError(
                        f"GTFS-RT trip-updates feed exceeded the {_MAX_FEED_BYTES}-byte "
                        "limit while downloading; refusing to parse a partial feed"
                    )
        except aiohttp.ClientError as err:
            raise FgcApiError(f"Error downloading GTFS-RT trip updates: {err}") from err
        except TimeoutError as err:
            raise FgcApiError(f"Timed out downloading GTFS-RT trip updates: {err}") from err

        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(data)
        except Exception as err:  # noqa: BLE001 - protobuf raises plain Exception/DecodeError
            raise FgcApiError(f"Could not parse GTFS-RT trip updates: {err}") from err

        by_stop: dict[str, list[int]] = {}
        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            for stop_time_update in entity.trip_update.stop_time_update:
                if not stop_time_update.HasField("departure"):
                    continue
                epoch = stop_time_update.departure.time
                if epoch:
                    by_stop.setdefault(stop_time_update.stop_id, []).append(epoch)
        return by_stop

    async def async_get_air_quality(self) -> list[dict[str, Any]]:
        """Return the latest air-quality reading near every FGC train station."""
        return await self._get_all_pages(DATASET_AIR_QUALITY, {})

    async def async_get_ski_parking(self) -> list[dict[str, Any]]:
        """Return every parking facility at every FGC mountain resort."""
        return await self._get_all_pages(DATASET_SKI_PARKING, {})

    async def async_get_carbon_footprint(self) -> list[dict[str, Any]]:
        """Return FGC's yearly corporate greenhouse-gas emissions report."""
        return await self._get_all_pages(DATASET_CARBON_FOOTPRINT, {})

    async def async_get_service_alerts(self) -> list[dict[str, Any]]:
        """Return every currently-published FGC train service alert
        (network/line-wide disruptions, planned works, etc.)."""
        return await self._get_all_pages(DATASET_ALERTS, {})
