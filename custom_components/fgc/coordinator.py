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

On top of the static schedule, every tick also fetches FGC's live GTFS-RT
Trip Updates feed and overlays real predicted departure times where
available (see `_apply_realtime`) — this is what makes a delayed train
keep showing up as "still coming" past its scheduled time, and a train
that actually left early or on time promptly drop off the list instead of
lingering with a stale scheduled time.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FgcApiClient, FgcApiError, StationInfo
from .const import DOMAIN, REALTIME_MATCH_MAX_DELTA, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Same-day schedule corrections (e.g. a same-day cancellation or an added
# service) are rare but do happen; refreshing every few hours regardless of
# the day-rollover check catches those without materially affecting API
# usage (a handful of extra requests per station per day).
_CACHE_MAX_AGE = timedelta(hours=3)


class Departure(TypedDict):
    """A single upcoming departure."""

    datetime: datetime
    stop_id: str
    line: str | None
    line_color: str | None
    line_text_color: str | None
    destination: str
    platform: str | None
    station_name: str | None
    realtime: bool


class _CachedSchedule(TypedDict):
    day: date
    fetched_at: datetime
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
        stop_id = row.get("stop_id")
        if not raw_time or not destination or not stop_id:
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
                stop_id=stop_id,
                line=row.get("route_short_name"),
                line_color=row.get("route_color"),
                line_text_color=row.get("route_text_color"),
                destination=destination,
                platform=row.get("platform_code"),
                station_name=stop_name,
                realtime=False,
            )
        )
    departures.sort(key=lambda dep: dep["datetime"])
    return departures


def _apply_realtime(
    departures: list[Departure], realtime_index: dict[str, list[int]], tz
) -> list[Departure]:
    """Overlay live GTFS-RT predicted departure times where a confident match
    exists, leaving everything else on its static scheduled time.

    The realtime feed doesn't expose a trip_id shared with the static
    schedule (not selectable through this API), so matching is done per
    stop_id by nearest scheduled-vs-predicted time instead, within
    `REALTIME_MATCH_MAX_DELTA`. Each predicted time is used at most once so
    two close-together departures can't both grab the same prediction.
    """
    # Candidates per stop_id, consumed greedily in scheduled-time order so
    # the earliest static departure gets first pick of the closest prediction.
    candidates: dict[str, list[int]] = {
        stop_id: list(epochs) for stop_id, epochs in realtime_index.items()
    }
    max_delta = REALTIME_MATCH_MAX_DELTA.total_seconds()

    adjusted: list[Departure] = []
    for dep in departures:
        pool = candidates.get(dep["stop_id"])
        if pool:
            scheduled_epoch = dep["datetime"].timestamp()
            best_idx, best_delta = None, None
            for idx, epoch in enumerate(pool):
                delta = abs(epoch - scheduled_epoch)
                if delta <= max_delta and (best_delta is None or delta < best_delta):
                    best_idx, best_delta = idx, delta
            if best_idx is not None:
                epoch = pool.pop(best_idx)
                dep = {
                    **dep,
                    "datetime": datetime.fromtimestamp(epoch, tz=tz),
                    "realtime": True,
                }
        adjusted.append(dep)
    adjusted.sort(key=lambda dep: dep["datetime"])
    return adjusted


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

        try:
            realtime_index = await self._client.async_get_realtime_departures()
        except FgcApiError as err:
            # Non-fatal: fall back to the static schedule for this tick, as
            # if no realtime data existed at all.
            _LOGGER.debug("Could not fetch realtime departures, using schedule only: %s", err)
            realtime_index = {}

        for code in self.station_codes:
            cached = self._schedules.get(code)
            is_stale = (
                cached is None
                or cached["day"] != today
                or now - cached["fetched_at"] > _CACHE_MAX_AGE
            )
            if is_stale:
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
                    fetched_at=now,
                    departures=departures,
                    destinations=sorted({dep["destination"] for dep in departures}),
                )
                self._schedules[code] = cached
                self.destinations[code] = cached["destinations"]

            # Widen the pre-filter so a delayed train whose *scheduled* time
            # has already passed is still considered — realtime matching
            # below may reveal it hasn't actually left yet.
            candidates = [
                dep
                for dep in cached["departures"]
                if dep["datetime"] >= now - REALTIME_MATCH_MAX_DELTA
            ]
            adjusted = _apply_realtime(candidates, realtime_index, now.tzinfo)

            by_destination: dict[str, list[Departure]] = {}
            for dep in adjusted:
                if dep["datetime"] >= now:
                    by_destination.setdefault(dep["destination"], []).append(dep)
            result[code] = {
                dest: deps[:5] for dest, deps in by_destination.items()
            }

        return result
