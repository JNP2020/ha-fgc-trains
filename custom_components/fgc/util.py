"""Small shared helpers for the FGC integration."""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Turn arbitrary text into a stable, unique_id-safe slug."""
    return _SLUG_RE.sub("_", text.lower()).strip("_")
