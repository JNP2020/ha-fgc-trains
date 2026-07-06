"""Camera entity that renders a Geotren-style departure board as an image,
one per configured station — for use as a companion-app home-screen
widget (Android/iOS widgets can't run the fgc-timetable-card.js Lovelace
card's JS, but they can show a `camera` entity's snapshot).
"""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .board_renderer import render_board
from .const import DOMAIN
from .coordinator import FgcCoordinator


class FgcBoardCamera(CoordinatorEntity[FgcCoordinator], Camera):
    """A departure board, rendered as a still image, for one station."""

    _attr_icon = "mdi:train-variant"

    def __init__(
        self,
        coordinator: FgcCoordinator,
        entry: ConfigEntry,
        station_code: str,
        station_name: str,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._station_code = station_code
        self._station_name = station_name
        self._attr_name = f"FGC {station_name} Board"
        self._attr_unique_id = f"{entry.entry_id}_board_{station_code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        departures = self.coordinator.get_board(self._station_code)
        # Pillow rendering is synchronous/CPU-bound: run off the event loop.
        return await self.hass.async_add_executor_job(
            render_board, departures, self._station_name
        )
