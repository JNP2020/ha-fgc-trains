"""Sensor platform for FGC Trains."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

try:  # UnitOfTime.MINUTES landed in newer HA cores; fall back for older ones.
    from homeassistant.const import UnitOfTime

    _MINUTES = UnitOfTime.MINUTES
except ImportError:  # pragma: no cover
    _MINUTES = "min"

from .const import (
    ATTR_DESTINATION,
    ATTR_LINE,
    ATTR_NEXT_DEPARTURE,
    ATTR_PLATFORM,
    ATTR_STATION_NAME,
    ATTR_UPCOMING,
    CONF_STATIONS,
    DOMAIN,
)
from .coordinator import FgcCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up FGC sensors for the stations configured on this entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FgcCoordinator = data["coordinator"]
    station_names: dict[str, str] = data["station_names"]

    async_add_entities(
        FgcDepartureSensor(coordinator, entry, code, station_names.get(code, code))
        for code in entry.options.get(CONF_STATIONS, [])
    )


class FgcDepartureSensor(CoordinatorEntity[FgcCoordinator], SensorEntity):
    """Minutes remaining until the next train departure from a station."""

    _attr_icon = "mdi:train"
    _attr_native_unit_of_measurement = _MINUTES

    def __init__(
        self,
        coordinator: FgcCoordinator,
        entry: ConfigEntry,
        station_code: str,
        station_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_code = station_code
        self._station_name = station_name
        self._attr_name = f"FGC {station_name}"
        self._attr_unique_id = f"{entry.entry_id}_{station_code}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _upcoming(self) -> list[dict]:
        return self.coordinator.data.get(self._station_code) or []

    @property
    def native_value(self) -> int | None:
        upcoming = self._upcoming
        if not upcoming:
            return None
        delta = upcoming[0]["datetime"] - dt_util.now()
        return max(0, int(delta.total_seconds() // 60))

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {ATTR_STATION_NAME: self._station_name}
        upcoming = self._upcoming
        if not upcoming:
            return attrs
        next_dep = upcoming[0]
        attrs.update(
            {
                ATTR_LINE: next_dep["line"],
                ATTR_DESTINATION: next_dep["destination"],
                ATTR_PLATFORM: next_dep["platform"],
                ATTR_NEXT_DEPARTURE: next_dep["datetime"].isoformat(),
                ATTR_UPCOMING: [
                    {
                        ATTR_LINE: dep["line"],
                        ATTR_DESTINATION: dep["destination"],
                        ATTR_PLATFORM: dep["platform"],
                        ATTR_NEXT_DEPARTURE: dep["datetime"].isoformat(),
                    }
                    for dep in upcoming[1:]
                ],
            }
        )
        return attrs
