"""Sensor entity for one FGC mountain resort's status.

Covers FGC's mountain "tourism facilities" feed generally — lifts,
conveyors, hiking/bike circuits, parking, etc. — so a resort reads "open"
in both the winter ski season and the summer hiking/bike season whenever
at least one of its facilities is running.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ALERTS,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_OPEN_FACILITIES,
    ATTR_TEMPERATURE,
    ATTR_TOTAL_FACILITIES,
    ATTR_WEBCAM_URL,
    ATTR_WIND_SPEED,
    DOMAIN,
)
from .ski_coordinator import SkiCoordinator, SkiResort
from .util import slugify


class SkiResortSensor(CoordinatorEntity[SkiCoordinator], SensorEntity):
    """Whether a resort is currently open, with weather/alerts/webcam info."""

    _attr_icon = "mdi:ski"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["open", "closed"]

    def __init__(
        self, coordinator: SkiCoordinator, entry: ConfigEntry, resort_name: str
    ) -> None:
        super().__init__(coordinator)
        self._resort_name = resort_name
        self._attr_name = f"FGC Ski {resort_name}"
        self._attr_unique_id = f"{entry.entry_id}_ski_{slugify(resort_name)}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _resort(self) -> SkiResort | None:
        return self.coordinator.data.get(self._resort_name)

    @property
    def available(self) -> bool:
        return super().available and self._resort is not None

    @property
    def native_value(self) -> str | None:
        resort = self._resort
        if not resort:
            return None
        return "open" if resort["is_open"] else "closed"

    @property
    def extra_state_attributes(self) -> dict:
        resort = self._resort
        if not resort:
            return {}
        return {
            ATTR_OPEN_FACILITIES: resort["open_facilities"],
            ATTR_TOTAL_FACILITIES: resort["total_facilities"],
            ATTR_TEMPERATURE: resort["temperature"],
            ATTR_WIND_SPEED: resort["wind_speed"],
            ATTR_ALERTS: resort["alerts"],
            ATTR_WEBCAM_URL: resort["webcam_url"],
            ATTR_LATITUDE: resort["latitude"],
            ATTR_LONGITUDE: resort["longitude"],
        }
