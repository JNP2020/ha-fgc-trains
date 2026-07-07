"""DataUpdateCoordinator for FGC's ski/mountain resorts.

Combines four small, slow-moving datasets — lift/facility open status,
weather, active alerts, and webcams — into one per-resort snapshot. This
data changes far more slowly than train schedules or positions, so it's
polled on its own, longer interval rather than piggy-backing on either of
the other coordinators.
"""
from __future__ import annotations

import json
import logging
from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import DOMAIN, SKI_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SkiResort(TypedDict):
    """A snapshot of one ski resort's current status."""

    name: str
    is_open: bool
    open_facilities: int
    total_facilities: int
    temperature: float | None
    wind_speed: float | None
    alerts: list[str]
    webcam_url: str | None
    latitude: float | None
    longitude: float | None


def _parse_localized_text(raw: str | None) -> str | None:
    """Parse a `{"ca": "...", "es": "...", ...}` blob, preferring Catalan."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw
    return data.get("ca") or next((v for v in data.values() if v), None)


class SkiCoordinator(DataUpdateCoordinator[dict[str, SkiResort]]):
    """Coordinator that keeps a per-resort snapshot of status/weather/alerts."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_ski", update_interval=SKI_SCAN_INTERVAL
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, SkiResort]:
        try:
            facilities = await self._client.async_get_ski_facilities()
            weather = await self._client.async_get_ski_weather()
            alerts = await self._client.async_get_ski_alerts()
            webcams = await self._client.async_get_ski_webcams()
        except FgcAuthError as err:
            raise ConfigEntryAuthFailed("Invalid FGC API key") from err
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC ski resort data: {err}") from err

        resorts: dict[str, SkiResort] = {}

        def _resort(name: str) -> SkiResort:
            return resorts.setdefault(
                name,
                SkiResort(
                    name=name,
                    is_open=False,
                    open_facilities=0,
                    total_facilities=0,
                    temperature=None,
                    wind_speed=None,
                    alerts=[],
                    webcam_url=None,
                    latitude=None,
                    longitude=None,
                ),
            )

        for row in facilities:
            name = row.get("name_bu")
            if not name:
                continue
            resort = _resort(name)
            resort["total_facilities"] += 1
            if row.get("is_open") == "1":
                resort["open_facilities"] += 1

        for resort in resorts.values():
            resort["is_open"] = resort["open_facilities"] > 0

        for row in weather:
            name = row.get("name_bu")
            if not name or name not in resorts:
                continue
            resort = resorts[name]
            if resort["temperature"] is not None:
                continue  # a resort can have several weather stations; keep the first
            resort["temperature"] = row.get("meteo_data_temperaturaactual_value")
            resort["wind_speed"] = row.get("meteo_data_ventactual_value")
            point = row.get("coordenades")
            if point:
                resort["latitude"] = point.get("lat")
                resort["longitude"] = point.get("lon")

        for row in alerts:
            if str(row.get("is_active")) not in ("1", "1.0"):
                continue
            name = row.get("name_bu")
            if not name or name not in resorts:
                continue
            text = _parse_localized_text(row.get("description_text"))
            if text:
                resorts[name]["alerts"].append(text)

        for row in webcams:
            if row.get("is_active") != 1:
                continue
            name = row.get("name_bu")
            if not name or name not in resorts or resorts[name]["webcam_url"]:
                continue
            resorts[name]["webcam_url"] = row.get("url")

        return resorts
