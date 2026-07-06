"""DataUpdateCoordinator for the FGC integration.

The `viajes-de-hoy` dataset holds the *whole day's* static timetable per
station, so instead of asking the API "what's next" on every poll (which
that dataset can't answer server-side for text-typed time fields anyway),
we fetch and cache each station's full remaining schedule once per day and
then just re-filter that cached list against the current time on every
(cheap, network-free) update.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FgcApiClient, FgcApiError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class Departure(TypedDict):
    """A single upcoming departure."""

    datetime: datetime
    line: str | None
    destination: str | None
    platform: str | None
    station_name: str | None


class _CachedSchedule(TypedDict):
    day: date
    departures: list[Departure]


def _parse_departures(rows: list[dict[str, Any]], today: date) -> list[Departure]:
    """Turn raw API rows into sorted, tz-aware Departure dicts.

    GTFS allows `departure_time` past "24:00:00" for trips that run into the
    next service day (e.g. "24:26:00" == 00:26 the next calendar day).
    """
    tzinfo = dt_util.now().tzinfo
    departures: list[Departure] = []
    for row in rows:
        raw_time = row.get("departure_time")
        if not raw_time:
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
                destination=row.get("trip_headsign"),
                platform=row.get("platform_code"),
                station_name=row.get("stop_name"),
            )
        )
    departures.sort(key=lambda dep: dep["datetime"])
    return departures


class FgcCoordinator(DataUpdateCoordinator[dict[str, list[Departure]]]):
    """Coordinator that keeps a rolling per-station list of upcoming departures."""

    def __init__(
        self, hass: HomeAssistant, client: FgcApiClient, station_codes: list[str]
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL
        )
        self._client = client
        self.station_codes = station_codes
        self._schedules: dict[str, _CachedSchedule] = {}

    async def _async_update_data(self) -> dict[str, list[Departure]]:
        now = dt_util.now()
        today = now.date()
        result: dict[str, list[Departure]] = {}

        for code in self.station_codes:
            cached = self._schedules.get(code)
            if cached is None or cached["day"] != today:
                try:
                    rows = await self._client.async_get_day_schedule(code)
                except FgcApiError as err:
                    raise UpdateFailed(
                        f"Error fetching FGC schedule for station {code}: {err}"
                    ) from err
                cached = _CachedSchedule(
                    day=today, departures=_parse_departures(rows, today)
                )
                self._schedules[code] = cached

            result[code] = [
                dep for dep in cached["departures"] if dep["datetime"] >= now
            ][:5]

        return result
