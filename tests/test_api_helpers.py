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
