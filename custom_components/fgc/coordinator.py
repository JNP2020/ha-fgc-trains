"""DataUpdateCoordinator for the FGC integration.

The `viajes-de-hoy` dataset holds the *whole day's* static timetable per
station, so instead of asking the API "what's next" on every poll (which
that dataset can't answer server-side for text-typed time fields anyway),
we fetch and cache each station's full remaining schedule once per day and
then just re-filter that cached list against the current time on every
(cheap, network-free) update.

A "station" (as picked in the config/options flow) can have several
platforms/`stop_id`s. At an intermediate stop these usually serve different
directions (one platform towards each terminus) and get one sensor each.
At a terminus, one platform is typically dedicated to trains ending their
trip there; those rows are announced with a `trip_headsign` equal to the
station's own name (the train isn't going anywhere further) and are
dropped entirely, so a plain terminus collapses back down to a single
"next departure" sensor instead of getting a bogus platform for arrivals.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FgcApiClient, FgcApiError, StationInfo
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class Departure(TypedDict):
    """A single upcoming departure."""

    datetime: datetime
    stop_id: str
    line: str | None
    destination: str | None
    platform: str | None
    station_name: str | None


class _CachedSchedule(TypedDict):
    day: date
    departures: list[Departure]
    platform_labels: dict[str, str]


def _parse_departures(rows: list[dict[str, Any]], today: date) -> list[Departure]:
    """Turn raw API rows into sorted, tz-aware Departure dicts.

    GTFS allows `departure_time` past "24:00:00" for trips that run into the
    next service day (e.g. "24:26:00" == 00:26 the next calendar day).

    Rows where the announced destination is this very stop are trains
    ending their trip here, not a departure a rider could board, so they're
    dropped rather than turned into a Departure.
    """
    tzinfo = dt_util.now().tzinfo
    departures: list[Departure] = []
    for row in rows:
        raw_time = row.get("departure_time")
        stop_id = row.get("stop_id")
        destination = row.get("trip_headsign")
        stop_name = row.get("stop_name")
        if not raw_time or not stop_id:
            continue
        if destination and stop_name and destination == stop_name:
            continue
        try:
            hours, minutes, seconds = (int(part) for part in raw_time.split(":"))
        except ValueError:
            continue
        day_offset, hours = divmod(hours, 24)
        dep_dt = datetime.combine(today, datetime.min.time(), tzinfo) + timedelta(
            days=day_offset, hours=hours, minutes=minutes, seconds=seconds
        )
        departures.append(
            Departure(
                datetime=dep_dt,
                stop_id=stop_id,
                line=row.get("route_short_name"),
                destination=destination,
                platform=row.get("platform_code"),
                station_name=stop_name,
            )
        )
    departures.sort(key=lambda dep: dep["datetime"])
    return departures


def _compute_platform_labels(departures: list[Departure]) -> dict[str, str]:
    """Pick the most common destination per platform as its direction label."""
    by_platform: dict[str, Counter] = {}
    for dep in departures:
        if dep["destination"]:
            by_platform.setdefault(dep["stop_id"], Counter())[dep["destination"]] += 1
    return {
        stop_id: counter.most_common(1)[0][0] for stop_id, counter in by_platform.items()
    }


class FgcCoordinator(DataUpdateCoordinator[dict[str, dict[str, list[Departure]]]]):
    """Coordinator that keeps a rolling per-platform list of upcoming departures.

    `data` is keyed as `{station_code: {platform_stop_id: [Departure, ...]}}`.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: FgcApiClient,
        stations: dict[str, StationInfo],
        station_codes: list[str],
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL
        )
        self._client = client
        self._stations = stations
        self.station_codes = station_codes
        self._schedules: dict[str, _CachedSchedule] = {}
        # station_code -> {platform_stop_id: direction label}
        self.platform_labels: dict[str, dict[str, str]] = {}

    async def _async_update_data(self) -> dict[str, dict[str, list[Departure]]]:
        now = dt_util.now()
        today = now.date()
        result: dict[str, dict[str, list[Departure]]] = {}

        for code in self.station_codes:
            cached = self._schedules.get(code)
            if cached is None or cached["day"] != today:
                stop_ids = self._stations.get(code, {}).get("stop_ids", [code])
                try:
                    rows = await self._client.async_get_day_schedule(stop_ids)
                except FgcApiError as err:
                    raise UpdateFailed(
                        f"Error fetching FGC schedule for station {code}: {err}"
                    ) from err
                departures = _parse_departures(rows, today)
                cached = _CachedSchedule(
                    day=today,
                    departures=departures,
                    platform_labels=_compute_platform_labels(departures),
                )
                self._schedules[code] = cached
                self.platform_labels[code] = cached["platform_labels"]

            by_platform: dict[str, list[Departure]] = {}
            for dep in cached["departures"]:
                if dep["datetime"] >= now:
                    by_platform.setdefault(dep["stop_id"], []).append(dep)
            result[code] = {
                stop_id: deps[:5] for stop_id, deps in by_platform.items()
            }

        return result
