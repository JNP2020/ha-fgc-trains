"""Unit tests for the small pure helpers in `api.py` that enforce the
network-hardening added for the security audit: query-string injection
guarding, https-only secondary downloads, and bounded error messages.
"""
from __future__ import annotations

import pytest

from custom_components.fgc.api import (
    _CODE_RE,
    _ERROR_BODY_MAX_CHARS,
    FgcApiError,
    _require_https,
    _truncate_body,
)


class TestCodeRegex:
    @pytest.mark.parametrize("code", ["PC", "abc123", "A-1", "a_b"])
    def test_accepts_plain_alphanumeric_codes(self, code):
        assert _CODE_RE.match(code)

    @pytest.mark.parametrize(
        "code",
        [
            "a)=1 or 1=1",  # OData-style injection attempt
            "a'; DROP TABLE x;--",
            "a b",
            "a/b",
            "",
        ],
    )
    def test_rejects_anything_with_odata_special_characters(self, code):
        assert not _CODE_RE.match(code)


class TestRequireHttps:
    def test_accepts_https(self):
        _require_https("https://example.fgc.cat/feed.pb", "feed")  # no raise

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.fgc.cat/feed.pb",
            "ftp://example.fgc.cat/feed.pb",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "",
        ],
    )
    def test_rejects_non_https_schemes(self, url):
        with pytest.raises(FgcApiError):
            _require_https(url, "feed")


class TestTruncateBody:
    def test_short_body_untouched(self):
        assert _truncate_body("short error") == "short error"

    def test_long_body_truncated_with_ellipsis(self):
        body = "x" * (_ERROR_BODY_MAX_CHARS + 500)
        result = _truncate_body(body)
        assert len(result) == _ERROR_BODY_MAX_CHARS + 1  # + ellipsis char
        assert result.endswith("…")

    def test_non_string_payload_stringified_first(self):
        payload = {"error": "boom"}
        assert _truncate_body(payload) == str(payload)


class TestParseTripUpdates:
    @staticmethod
    def _feed():
        from google.transit import gtfs_realtime_pb2

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        return feed

    def test_reads_departure_time_and_route(self):
        from custom_components.fgc.api import _parse_trip_updates

        feed = self._feed()
        entity = feed.entity.add()
        entity.id = "1"
        entity.trip_update.trip.route_id = "S1"
        stu = entity.trip_update.stop_time_update.add()
        stu.stop_id = "SC1"
        stu.departure.time = 1000
        result = _parse_trip_updates(feed)
        assert result == {"SC1": [(1000, "S1", False)]}

    def test_cancelled_trip_uses_arrival_time_when_no_departure(self):
        from google.transit import gtfs_realtime_pb2

        from custom_components.fgc.api import _parse_trip_updates

        feed = self._feed()
        entity = feed.entity.add()
        entity.id = "1"
        entity.trip_update.trip.schedule_relationship = (
            gtfs_realtime_pb2.TripDescriptor.CANCELED
        )
        stu = entity.trip_update.stop_time_update.add()
        stu.stop_id = "SC1"
        stu.arrival.time = 2000
        assert _parse_trip_updates(feed) == {"SC1": [(2000, None, True)]}

    def test_skipped_stop_is_flagged_but_rest_of_trip_is_not(self):
        from google.transit import gtfs_realtime_pb2

        from custom_components.fgc.api import _parse_trip_updates

        feed = self._feed()
        entity = feed.entity.add()
        entity.id = "1"
        skipped = entity.trip_update.stop_time_update.add()
        skipped.stop_id = "A1"
        skipped.departure.time = 100
        skipped.schedule_relationship = (
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.SKIPPED
        )
        normal = entity.trip_update.stop_time_update.add()
        normal.stop_id = "B1"
        normal.departure.time = 200
        result = _parse_trip_updates(feed)
        assert result["A1"][0].canceled is True
        assert result["B1"][0].canceled is False

    def test_delay_only_updates_are_ignored(self):
        from custom_components.fgc.api import _parse_trip_updates

        feed = self._feed()
        entity = feed.entity.add()
        entity.id = "1"
        stu = entity.trip_update.stop_time_update.add()
        stu.stop_id = "SC1"
        stu.departure.delay = 120
        assert _parse_trip_updates(feed) == {}
