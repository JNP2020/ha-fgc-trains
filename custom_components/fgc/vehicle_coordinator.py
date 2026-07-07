"""DataUpdateCoordinator for live FGC train positions (Geotren feed).

Unlike the per-station schedule data, vehicle positions are genuinely live
and fleet-wide (one API call returns every active train network-wide), so
this polls frequently and never caches across ticks. Station codes referenced
by the feed (origin/destination/next stops) are translated to display names
using a separate, effectively-static lookup fetched once and kept for the
life of the coordinator.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import DOMAIN, VEHICLE_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class VehiclePosition(TypedDict):
    """Current position and trip info for one physical train unit."""

    unit_id: str
    line: str | None
    direction: str | None
    origin: str | None
    origin_name: str | None
    destination: str | None
    destination_name: str | None
    next_stops: list[str]
    next_stop_names: list[str]
    stopped_at: str | None
    stopped_at_name: str | None
    on_time: bool | None
    unit_type: str | None
    latitude: float
    longitude: float


def _parse_next_stops(raw: str | None) -> list[str]:
    """Parse "properes_parades" (e.g. `{"parada": "PC"};{"parada": "SC"}`)."""
    if not raw:
        return []
    stops = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            stops.append(json.loads(chunk)["parada"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return stops


class FgcVehicleCoordinator(DataUpdateCoordinator[dict[str, VehiclePosition]]):
    """Coordinator that keeps the latest position of every active train."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_vehicles", update_interval=VEHICLE_SCAN_INTERVAL
        )
        self._client = client
        self._station_names: dict[str, str] | None = None

    async def _async_update_data(self) -> dict[str, VehiclePosition]:
        if self._station_names is None:
            try:
                self._station_names = await self._client.async_get_station_names()
            except FgcApiError as err:
                # Non-fatal: fall back to raw codes for this tick and retry
                # on the next one, rather than permanently giving up.
                _LOGGER.debug("Could not fetch FGC station names, will retry: %s", err)

        try:
            rows = await self._client.async_get_vehicle_positions()
        except FgcAuthError as err:
            raise ConfigEntryAuthFailed("Invalid FGC API key") from err
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC vehicle positions: {err}") from err

        names = self._station_names or {}
        vehicles: dict[str, VehiclePosition] = {}
        for row in rows:
            unit_id = row.get("ut")
            point = row.get("geo_point_2d")
            if not unit_id or not point:
                continue
            origin = row.get("origen")
            destination = row.get("desti")
            stopped_at = row.get("estacionat_a")
            next_stops = _parse_next_stops(row.get("properes_parades"))
            en_hora = row.get("en_hora")
            vehicles[unit_id] = VehiclePosition(
                unit_id=unit_id,
                line=row.get("lin"),
                direction=row.get("dir"),
                origin=origin,
                origin_name=names.get(origin) if origin else None,
                destination=destination,
                destination_name=names.get(destination) if destination else None,
                next_stops=next_stops,
                next_stop_names=[names.get(s, s) for s in next_stops],
                stopped_at=stopped_at,
                stopped_at_name=names.get(stopped_at) if stopped_at else None,
                on_time=(str(en_hora) == "True") if en_hora is not None else None,
                unit_type=row.get("tipus_unitat"),
                latitude=point["lat"],
                longitude=point["lon"],
            )
        return vehicles
