"""DataUpdateCoordinator for the FGC integration.

The `viajes-de-hoy` dataset holds the *whole day's* static timetable per
station, so instead of asking the API "what's next" on every poll (which
that dataset can't answer server-side for text-typed time fields anyway),
we fetch and cache each station's full remaining schedule once per day and
then just re-filter that cached list against the current time on every
(cheap, network-free) update.

A "station" (as picked in the config/options flow) can have several
platforms/`stop_id`s, but which physical platform a train uses is mostly an
operational/capacity detail, not a meaningful "direction" — a busy terminus
like Plaça Catalunya spreads several different lines/destinations across
its platforms without a clean one-platform-per-destination mapping.
Departures are instead grouped by their final destination (`trip_headsign`),
which is what a rider actually cares about ("next train to X"), so each
distinct destination gets its own sensor. Rows where the destination is
this very stop are trains ending their trip here, not a departure a rider
could board, so they're dropped rather than turned into a Departure; a
plain terminus then naturally collapses down to a single destination/sensor.
"""
from __future__ import annotations

import logging
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
    line: str | None
    line_color: str | None
    line_text_color: str | None
    destination: str
    platform: str | None
    station_name: str | None


class _CachedSchedule(TypedDict):
    day: date
    departures: list[Departure]
    destinations: list[str]


def _parse_departures(rows: list[dict[str, Any]], today: date) -> list[Departure]:
    """Turn raw API rows into sorted, tz-aware Departure dicts.

    GTFS allows `departure_time` past "24:00:00" for trips that run into the
    next service day (e.g. "24:26:00" == 00:26 the next calendar day).
    """
    tzinfo = dt_util.now().tzinfo
    departures: list[Departure] = []
    for row in rows:
        raw_time = row.get("departure_time")
        destination = row.get("trip_headsign")
        stop_name = row.get("stop_name")
        if not raw_time or not destination:
            continue
        if destination == stop_name:
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
                line=row.get("route_short_name"),
                line_color=row.get("route_color"),
                line_text_color=row.get("route_text_color"),
                destination=destination,
                platform=row.get("platform_code"),
                station_name=stop_name,
            )
        )
    departures.sort(key=lambda dep: dep["datetime"])
    return departures


class FgcCoordinator(DataUpdateCoordinator[dict[str, dict[str, list[Departure]]]]):
    """Coordinator that keeps a rolling per-destination list of upcoming departures.

    `data` is keyed as `{station_code: {destination: [Departure, ...]}}`.
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
        # station_code -> list of distinct destinations served from it today
        self.destinations: dict[str, list[str]] = {}

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
                    destinations=sorted({dep["destination"] for dep in departures}),
                )
                self._schedules[code] = cached
                self.destinations[code] = cached["destinations"]

            by_destination: dict[str, list[Departure]] = {}
            for dep in cached["departures"]:
                if dep["datetime"] >= now:
                    by_destination.setdefault(dep["destination"], []).append(dep)
            result[code] = {
                dest: deps[:5] for dest, deps in by_destination.items()
            }

        return result
