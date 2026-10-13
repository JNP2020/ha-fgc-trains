"""Unit tests for the pure, side-effect-free scheduling logic in
`coordinator.py` — the most complex/fragile part of this integration
(realtime-matching heuristics, dedup, GTFS >24h time handling).

These exercise `_parse_departures`, `_apply_realtime` and
`_dedupe_departures` directly with plain dicts, independent of any live
Home Assistant instance or network access.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.fgc.coordinator import (
    Departure,
    _apply_realtime,
    _dedupe_departures,
    _parse_departures,
)

UTC = UTC


def _row(
    *,
    departure_time="08:15:00",
    trip_headsign="Terrassa",
    stop_name="Sant Cugat",
    stop_id="SC1",
    route_short_name="S1",
    route_color="FF0000",
    route_text_color="FFFFFF",
    platform_code="1",
):
    return {
        "departure_time": departure_time,
        "trip_headsign": trip_headsign,
        "stop_name": stop_name,
        "stop_id": stop_id,
        "route_short_name": route_short_name,
        "route_color": route_color,
        "route_text_color": route_text_color,
        "platform_code": platform_code,
    }


def _dep(dt: datetime, **overrides) -> Departure:
    base = Departure(
        datetime=dt,
        stop_id="SC1",
        line="S1",
        line_color="FF0000",
        line_text_color="FFFFFF",
        destination="Terrassa",
        platform="1",
        station_name="Sant Cugat",
        realtime=False,
    )
    base.update(overrides)
    return base


class TestParseDepartures:
    def test_parses_a_normal_row(self):
        today = date(2026, 3, 1)
        [dep] = _parse_departures([_row()], today)
        assert dep["destination"] == "Terrassa"
        assert dep["stop_id"] == "SC1"
        assert dep["line"] == "S1"
        assert dep["realtime"] is False
        assert dep["datetime"].hour == 8 and dep["datetime"].minute == 15

    def test_gtfs_time_past_24h_rolls_to_next_day(self):
        today = date(2026, 3, 1)
        [dep] = _parse_departures([_row(departure_time="24:26:00")], today)
        assert dep["datetime"].date() == date(2026, 3, 2)
        assert dep["datetime"].hour == 0 and dep["datetime"].minute == 26

    def test_drops_rows_ending_their_trip_here(self):
        """A row whose headsign equals the stop name is a train terminating
        here, not a boardable departure, and must be dropped."""
        today = date(2026, 3, 1)
        rows = [_row(trip_headsign="Sant Cugat", stop_name="Sant Cugat")]
        assert _parse_departures(rows, today) == []

    @pytest.mark.parametrize(
        "missing_field",
        ["departure_time", "trip_headsign", "stop_id"],
    )
    def test_drops_rows_missing_required_fields(self, missing_field):
        today = date(2026, 3, 1)
        row = _row()
        row[missing_field] = None
        assert _parse_departures([row], today) == []

    def test_drops_rows_with_unparsable_time(self):
        today = date(2026, 3, 1)
        assert _parse_departures([_row(departure_time="not-a-time")], today) == []

    def test_results_sorted_by_time(self):
        today = date(2026, 3, 1)
        rows = [
            _row(departure_time="09:00:00", stop_id="A"),
            _row(departure_time="08:00:00", stop_id="B"),
        ]
        deps = _parse_departures(rows, today)
        assert [d["stop_id"] for d in deps] == ["B", "A"]


class TestApplyRealtime:
    def test_matches_within_delta_and_marks_realtime(self):
        scheduled = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        predicted = datetime(2026, 3, 1, 8, 17, tzinfo=UTC)
        departures = [_dep(scheduled)]
        realtime_index = {"SC1": [predicted.timestamp()]}
        [adjusted] = _apply_realtime(departures, realtime_index, UTC)
        assert adjusted["realtime"] is True
        assert adjusted["datetime"] == predicted

    def test_ignores_predictions_outside_max_delta(self):
        scheduled = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        far_prediction = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        departures = [_dep(scheduled)]
        realtime_index = {"SC1": [far_prediction.timestamp()]}
        [adjusted] = _apply_realtime(departures, realtime_index, UTC)
        assert adjusted["realtime"] is False
        assert adjusted["datetime"] == scheduled

    def test_best_delta_wins_when_two_departures_compete_for_one_prediction(self):
        """Regression test for the greedy-matching behaviour described in
        `_apply_realtime`'s docstring: with two close-together scheduled
        departures and only one nearby prediction, the prediction must go
        to whichever departure it's actually closest to, not whichever
        comes first in schedule order."""
        dep_a = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)  # closer to the prediction
        dep_b = datetime(2026, 3, 1, 8, 10, tzinfo=UTC)  # earlier in schedule order
        prediction = datetime(2026, 3, 1, 8, 16, tzinfo=UTC)
        departures = [_dep(dep_b, stop_id="SC1"), _dep(dep_a, stop_id="SC1")]
        realtime_index = {"SC1": [prediction.timestamp()]}
        adjusted = _apply_realtime(departures, realtime_index, UTC)
        matched = [d for d in adjusted if d["realtime"]]
        assert len(matched) == 1
        assert matched[0]["datetime"] == prediction
        # It must have been applied to dep_a (originally 8:15), not dep_b.
        unmatched = [d for d in adjusted if not d["realtime"]]
        assert unmatched[0]["datetime"] == dep_b

    def test_each_prediction_used_at_most_once(self):
        dep1 = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        dep2 = datetime(2026, 3, 1, 8, 16, tzinfo=UTC)
        prediction = datetime(2026, 3, 1, 8, 15, 30, tzinfo=UTC)
        departures = [_dep(dep1, stop_id="SC1"), _dep(dep2, stop_id="SC1")]
        realtime_index = {"SC1": [prediction.timestamp()]}
        adjusted = _apply_realtime(departures, realtime_index, UTC)
        matched = [d for d in adjusted if d["realtime"]]
        assert len(matched) == 1

    def test_no_predictions_for_stop_leaves_departures_untouched(self):
        scheduled = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        departures = [_dep(scheduled)]
        [adjusted] = _apply_realtime(departures, {}, UTC)
        assert adjusted == departures[0]


class TestDedupeDepartures:
    def test_collapses_near_identical_entries_preferring_realtime(self):
        t1 = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 8, 15, 30, tzinfo=UTC)  # 30s apart, same train
        departures = [_dep(t1, realtime=False), _dep(t2, realtime=True)]
        [kept] = _dedupe_departures(departures)
        assert kept["realtime"] is True
        assert kept["datetime"] == t2

    def test_keeps_distinct_trains_on_same_line_and_destination(self):
        t1 = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 8, 45, tzinfo=UTC)  # far apart: different trains
        departures = [_dep(t1), _dep(t2)]
        kept = _dedupe_departures(departures)
        assert len(kept) == 2

    def test_keeps_same_time_different_destination(self):
        t1 = datetime(2026, 3, 1, 8, 15, tzinfo=UTC)
        departures = [
            _dep(t1, destination="Terrassa"),
            _dep(t1, destination="Igualada"),
        ]
        kept = _dedupe_departures(departures)
        assert len(kept) == 2
