"""Diagnostics for FGC Trains (Settings -> Devices & services -> Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import FgcConfigEntry
from .const import CONF_API_KEY

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FgcConfigEntry
) -> dict[str, Any]:
    """Return what a bug report needs, without the API key.

    Departure data is summarised (counts and the next time per destination)
    rather than dumped, to keep the file small and readable.
    """
    runtime = entry.runtime_data
    coordinator = runtime["coordinator"]
    now = dt_util.now()

    stations: dict[str, Any] = {}
    for code in coordinator.station_codes:
        info = runtime["stations"].get(code, {})
        board = (coordinator.data or {}).get(code, {})
        stations[code] = {
            "name": info.get("name"),
            "stop_ids": info.get("stop_ids"),
            "known_destinations": coordinator.destinations.get(code, []),
            "next_departures": {
                destination: [dep["datetime"].isoformat() for dep in deps[:2]]
                for destination, deps in board.items()
            },
        }

    features = {
        key: {
            "enabled": value is not None,
            "last_update_success": getattr(value, "last_update_success", None),
        }
        for key, value in runtime.items()
        if key.endswith("_coordinator") and key != "coordinator"
    }

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "now": now.isoformat(),
        "timezone": str(now.tzinfo),
        "schedule": {
            "last_update_success": coordinator.last_update_success,
            "is_quiet": coordinator.is_quiet(now),
        },
        "stations": stations,
        "optional_features": features,
    }
