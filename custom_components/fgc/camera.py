"""Camera platform for FGC: ski resort webcams, and per-station departure
board images (for companion-app home-screen widgets).

Webcams are off by default (Configure -> Settings -> "Show ski resort
webcams as cameras"); each fetches its still image on demand. Board
cameras are created automatically for every configured station (same
footprint as the departure sensors — no extra API calls, just rendered
from data already being fetched).
"""
from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .board_camera import FgcBoardCamera
from .const import CONF_STATIONS, DOMAIN
from .extra_coordinators import Webcam, WebcamCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the board-image camera for every configured station, plus
    webcam cameras for every currently-known active webcam (keeping adding
    new webcams as they appear). Webcams are skipped entirely if that
    feature is off (`webcam_coordinator` is None in that case)."""
    data = hass.data[DOMAIN][entry.entry_id]

    coordinator = data["coordinator"]
    stations = data["stations"]
    board_entities = [
        FgcBoardCamera(coordinator, entry, code, stations.get(code, {}).get("name", code))
        for code in entry.options.get(CONF_STATIONS, [])
    ]
    if board_entities:
        async_add_entities(board_entities)

    webcam_coordinator: WebcamCoordinator | None = data.get("webcam_coordinator")
    if webcam_coordinator is None:
        return
    known_ids: set[str] = set()

    @callback
    def _add_new_webcams() -> None:
        new_entities = [
            FgcWebcamCamera(webcam_coordinator, entry, webcam_id)
            for webcam_id in webcam_coordinator.data
            if webcam_id not in known_ids
        ]
        if new_entities:
            known_ids.update(entity.webcam_id for entity in new_entities)
            async_add_entities(new_entities)

    entry.async_on_unload(webcam_coordinator.async_add_listener(_add_new_webcams))
    _add_new_webcams()


class FgcWebcamCamera(CoordinatorEntity[WebcamCoordinator], Camera):
    """A still-image camera fed by one FGC ski resort webcam."""

    _attr_icon = "mdi:webcam"

    def __init__(
        self, coordinator: WebcamCoordinator, entry: ConfigEntry, webcam_id: str
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self.webcam_id = webcam_id
        webcam = coordinator.data.get(webcam_id)
        self._attr_name = (
            f"FGC Ski {webcam['resort_name']} {webcam['name']}"
            if webcam
            else f"FGC Webcam {webcam_id}"
        )
        self._attr_unique_id = f"{entry.entry_id}_webcam_{webcam_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _webcam(self) -> Webcam | None:
        return self.coordinator.data.get(self.webcam_id)

    @property
    def available(self) -> bool:
        return super().available and self._webcam is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        webcam = self._webcam
        if not webcam:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(webcam["url"]) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
        except Exception:  # noqa: BLE001 - a fetch failure just means no snapshot
            _LOGGER.debug(
                "Could not fetch webcam image for %s", self.webcam_id, exc_info=True
            )
            return None
