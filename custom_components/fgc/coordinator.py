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

That realtime feed is skipped outside of service hours (see `is_quiet`):
overnight, with no configured station's next departure due soon, it has
nothing new to report, so there's no point spending an API call on it
every 30 seconds until service is about to resume.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FgcApiClient, FgcApiError, FgcAuthError, RealtimePrediction, StationInfo
from .const import (
    DOMAIN,
    QUIET_HOURS_RESUME_BUFFER,
    REALTIME_MATCH_MAX_DELTA,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Same-day schedule corrections (e.g. a same-day cancellation or an added
# service) are rare but do happen; refreshing every few hours regardless of
# the day-rollover check catches those without materially affecting API
# usage (a handful of extra requests per station per day).
_CACHE_MAX_AGE = timedelta(hours=3)

# If a refresh of an already-cached (same-day) schedule fails, keep serving
# the cache and try again after this long instead of on every 30s tick.
_REFRESH_RETRY_DELAY = timedelta(minutes=5)


def _as_prediction(raw: float | RealtimePrediction) -> RealtimePrediction:
    """Accept a bare epoch (the original index format) as well as a full
    `RealtimePrediction`, so older callers and tests keep working."""
    return raw if isinstance(raw, RealtimePrediction) else RealtimePrediction(raw)


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
    departures: list[Departure],
    realtime_index: dict[str, list[float | RealtimePrediction]],
    tz,
) -> list[Departure]:
    """Overlay live GTFS-RT predicted departure times where a confident match
    exists, leaving everything else on its static scheduled time.

    The realtime feed doesn't expose a trip_id shared with the static
    schedule (not selectable through this API), so matching is done per
    stop_id by nearest scheduled-vs-predicted time instead, within
    `REALTIME_MATCH_MAX_DELTA`.

    Matching is done globally-greedy (best delta first across *all*
    candidate pairs, not departure-by-departure in schedule order): with two
    departures close together at the same platform, naively matching the
    earlier one first can steal the closer prediction from the later one,
    leaving it stuck on a stale static time and showing what looks like a
    duplicate/phantom train alongside the (wrongly) realtime-adjusted one.
    Matching by best-delta-first instead, and each side used at most once,
    avoids that.

    When the feed tells us which route a prediction belongs to, a pairing
    whose route agrees with the departure's line is preferred over a closer
    one that doesn't — that keeps two different lines calling at the same
    platform within a few minutes of each other from swapping predictions.
    It's only a preference, never a hard filter: if the feed's route ids
    don't line up with the timetable's line names, every pairing counts as
    a mismatch equally and the order falls back to pure time distance.

    A prediction flagged as cancelled (cancelled trip or skipped stop) that
    matches a departure removes that departure from the result rather than
    leaving a train on the board that isn't going to run.
    """
    max_delta = REALTIME_MATCH_MAX_DELTA.total_seconds()

    # Every (departure, prediction) pair at the same stop_id within the
    # delta window, best matches first.
    pairs: list[tuple[int, float, int, int]] = []  # (route_mismatch, delta, dep_idx, pred_idx)
    predictions_by_stop: dict[str, list[RealtimePrediction]] = {}
    for dep_idx, dep in enumerate(departures):
        raw_predictions = realtime_index.get(dep["stop_id"])
        if not raw_predictions:
            continue
        predictions = predictions_by_stop.setdefault(
            dep["stop_id"], [_as_prediction(raw) for raw in raw_predictions]
        )
        scheduled_epoch = dep["datetime"].timestamp()
        for pred_idx, prediction in enumerate(predictions):
            delta = abs(prediction.epoch - scheduled_epoch)
            if delta <= max_delta:
                route_mismatch = int(
                    bool(prediction.route_id)
                    and bool(dep["line"])
                    and prediction.route_id != dep["line"]
                )
                pairs.append((route_mismatch, delta, dep_idx, pred_idx))
    pairs.sort(key=lambda p: (p[0], p[1]))

    matched: dict[int, RealtimePrediction] = {}  # dep_idx -> chosen prediction
    used: dict[str, set[int]] = {}  # stop_id -> set of consumed pred_idx
    for _mismatch, _delta, dep_idx, pred_idx in pairs:
        if dep_idx in matched:
            continue
        stop_id = departures[dep_idx]["stop_id"]
        consumed = used.setdefault(stop_id, set())
        if pred_idx in consumed:
            continue
        consumed.add(pred_idx)
        matched[dep_idx] = predictions_by_stop[stop_id][pred_idx]

    adjusted: list[Departure] = []
    for dep_idx, dep in enumerate(departures):
        prediction = matched.get(dep_idx)
        if prediction is not None:
            if prediction.canceled:
                continue
            dep = {
                **dep,
                "datetime": datetime.fromtimestamp(prediction.epoch, tz=tz),
                "realtime": True,
            }
        adjusted.append(dep)
    adjusted.sort(key=lambda dep: dep["datetime"])
    return adjusted


def _dedupe_departures(departures: list[Departure]) -> list[Departure]:
    """Collapse departures that clearly represent the same physical train.

    A backstop against the realtime overlay (or any upstream data quirk)
    producing two entries — one static, one realtime-adjusted — for what a
    rider would perceive as a single train: same line + destination and
    times within a minute of each other. Keeps the realtime-backed one when
    there's a choice, since it's the more accurate of the two.
    """
    kept: list[Departure] = []
    for dep in departures:
        duplicate_idx = None
        for idx, other in enumerate(kept):
            if (
                dep["line"] == other["line"]
                and dep["destination"] == other["destination"]
                and abs((dep["datetime"] - other["datetime"]).total_seconds()) < 60
            ):
                duplicate_idx = idx
                break
        if duplicate_idx is None:
            kept.append(dep)
        elif dep["realtime"] and not kept[duplicate_idx]["realtime"]:
            kept[duplicate_idx] = dep
    return kept


def _carry_over_after_midnight(
    previous: list[Departure], fresh: list[Departure], now: datetime
) -> list[Departure]:
    """Keep yesterday's still-upcoming departures when a new day's schedule loads.

    GTFS lists the small hours as "24:xx" of the *previous* service day, so
    right after midnight yesterday's cached list can still hold trains that
    haven't left yet. Replacing the cache wholesale would drop them if the
    new day's dataset doesn't repeat them; exact duplicates are skipped so
    it doesn't double-list the ones it does.
    """
    seen = {
        (dep["datetime"], dep["stop_id"], dep["line"], dep["destination"]) for dep in fresh
    }
    carried = [
        dep
        for dep in previous
        if dep["datetime"] >= now
        and (dep["datetime"], dep["stop_id"], dep["line"], dep["destination"]) not in seen
    ]
    return sorted([*fresh, *carried], key=lambda dep: dep["datetime"])


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

        # Refresh any stale per-station schedule cache first: besides being
        # needed below, this is also what `is_quiet` relies on to know when
        # the next service day's first departure is. Stations are fetched
        # concurrently - at midnight (or after a restart) every configured
        # station is stale at once, and they're independent requests.
        stale = [
            code
            for code in self.station_codes
            if (cached := self._schedules.get(code)) is None
            or cached["day"] != today
            or now - cached["fetched_at"] > _CACHE_MAX_AGE
        ]
        if stale:
            await asyncio.gather(
                *(self._async_refresh_schedule(code, now, today) for code in stale)
            )

        # The realtime feed is fleet-wide and has nothing useful to say
        # while no configured station has a departure due soon, so it's
        # skipped during that gap rather than polled every tick for
        # nothing — see `is_quiet`.
        if self.is_quiet(now):
            realtime_index: dict[str, list[float | RealtimePrediction]] = {}
        else:
            try:
                realtime_index = await self._client.async_get_realtime_departures()
            except FgcApiError as err:
                # Non-fatal: fall back to the static schedule for this tick,
                # as if no realtime data existed at all.
                _LOGGER.debug(
                    "Could not fetch realtime departures, using schedule only: %s", err
                )
                realtime_index = {}

        for code in self.station_codes:
            cached = self._schedules[code]

            # Widen the pre-filter so a delayed train whose *scheduled* time
            # has already passed is still considered — realtime matching
            # below may reveal it hasn't actually left yet.
            candidates = [
                dep
                for dep in cached["departures"]
                if dep["datetime"] >= now - REALTIME_MATCH_MAX_DELTA
            ]
            adjusted = _apply_realtime(candidates, realtime_index, now.tzinfo)
            adjusted = _dedupe_departures(adjusted)

            by_destination: dict[str, list[Departure]] = {}
            for dep in adjusted:
                if dep["datetime"] >= now:
                    by_destination.setdefault(dep["destination"], []).append(dep)
            result[code] = {
                dest: deps[:5] for dest, deps in by_destination.items()
            }

        return result

    async def _async_refresh_schedule(self, code: str, now: datetime, today: date) -> None:
        """(Re)fetch one station's schedule for today into the cache.

        If the fetch fails but we already hold today's schedule, keep serving
        it and retry in a few minutes: the timetable is static, so a short
        API hiccup shouldn't turn every departure sensor "unavailable". Only
        when there is nothing usable (first load, or the cache is from a
        previous day) does the failure propagate.
        """
        previous = self._schedules.get(code)
        stop_ids = self._stations.get(code, {}).get("stop_ids", [code])
        try:
            rows = await self._client.async_get_day_schedule(stop_ids)
        except FgcAuthError as err:
            raise ConfigEntryAuthFailed("Invalid FGC API key") from err
        except FgcApiError as err:
            if previous is not None and previous["day"] == today:
                _LOGGER.warning(
                    "Could not refresh the FGC schedule for station %s (%s); "
                    "keeping the cached one and retrying in %d minutes",
                    code,
                    err,
                    _REFRESH_RETRY_DELAY.total_seconds() // 60,
                )
                previous["fetched_at"] = now - _CACHE_MAX_AGE + _REFRESH_RETRY_DELAY
                return
            raise UpdateFailed(
                f"Error fetching FGC schedule for station {code}: {err}"
            ) from err

        departures = _parse_departures(rows, today)
        if previous is not None and previous["day"] != today:
            departures = _carry_over_after_midnight(previous["departures"], departures, now)
        self._schedules[code] = _CachedSchedule(
            day=today,
            fetched_at=now,
            departures=departures,
            destinations=sorted({dep["destination"] for dep in departures}),
        )
        # Remember every destination seen since startup, not just today's:
        # a branch that only runs on weekdays still keeps its sensor (it
        # just reads "unknown" on a day with no service) instead of the
        # entity coming and going with the timetable.
        known = self.destinations.setdefault(code, [])
        known[:] = sorted(set(known) | set(self._schedules[code]["destinations"]))

    def is_quiet(self, now: datetime) -> bool:
        """Whether `now` falls in a known service gap — before any
        configured station's next scheduled departure, minus a resume
        buffer — where the realtime/live-position feeds have nothing new
        to report since no train is running yet.

        Cheap and side-effect-free: only looks at already-cached per-station
        schedules, so it's safe to call from other coordinators too (e.g.
        the live map) without triggering any API calls of its own. Errs
        towards "quiet" when a next departure isn't known yet (e.g. late at
        night, before the new day's schedule has been fetched) rather than
        polling needlessly on the assumption service might resume any moment.
        """
        next_departure = min(
            (
                dep["datetime"]
                for cached in self._schedules.values()
                for dep in cached["departures"]
                if dep["datetime"] >= now
            ),
            default=None,
        )
        return next_departure is None or now < next_departure - QUIET_HOURS_RESUME_BUFFER

    def get_board(self, station_code: str) -> list[Departure]:
        """Return every destination's upcoming departures for one station,
        merged into a single chronological list — mirrors what the
        fgc-timetable-card Lovelace card assembles client-side, for the
        board-image camera. Already deduped/realtime-adjusted since it's
        built from `self.data`.
        """
        by_destination = self.data.get(station_code, {})
        merged = [dep for deps in by_destination.values() for dep in deps]
        merged.sort(key=lambda dep: dep["datetime"])
        return merged
