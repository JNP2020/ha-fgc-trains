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
    ATTR_DIRECTION,
    ATTR_LINE,
    ATTR_LINE_COLOR,
    ATTR_LINE_TEXT_COLOR,
    ATTR_NEXT_DEPARTURE,
    ATTR_PLATFORM,
    ATTR_STATION_CODE,
    ATTR_STATION_NAME,
    ATTR_UPCOMING,
    CONF_STATIONS,
    DOMAIN,
)
from .coordinator import FgcCoordinator
from .ski_coordinator import SkiCoordinator
from .ski_sensor import SkiResortSensor
from .util import slugify


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one sensor per destination for each configured station, plus
    one per ski resort if that feature is enabled.

    A station with trains heading to several distinct destinations (e.g. an
    intermediate stop, or a hub terminus spreading lines across platforms)
    gets one sensor per destination; a station with a single destination all
    day just gets one sensor. The coordinator has already done its first
    refresh by the time this runs, so `destinations` is populated for every
    configured station.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FgcCoordinator = data["coordinator"]
    stations: dict[str, dict] = data["stations"]

    entities = []
    for code in entry.options.get(CONF_STATIONS, []):
        station_name = stations.get(code, {}).get("name", code)
        destinations = coordinator.destinations.get(code, [])
        single_destination = len(destinations) <= 1
        for destination in destinations:
            entities.append(
                FgcDepartureSensor(
                    coordinator,
                    entry,
                    code,
                    destination,
                    station_name,
                    None if single_destination else destination,
                )
            )

    ski_coordinator: SkiCoordinator | None = data.get("ski_coordinator")
    if ski_coordinator is not None:
        for resort_name in ski_coordinator.data:
            entities.append(SkiResortSensor(ski_coordinator, entry, resort_name))

    async_add_entities(entities)


class FgcDepartureSensor(CoordinatorEntity[FgcCoordinator], SensorEntity):
    """Minutes remaining until the next train departure to one destination."""

    _attr_icon = "mdi:train"
    _attr_native_unit_of_measurement = _MINUTES

    def __init__(
        self,
        coordinator: FgcCoordinator,
        entry: ConfigEntry,
        station_code: str,
        destination: str,
        station_name: str,
        direction_label: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._station_code = station_code
        self._destination = destination
        self._station_name = station_name
        self._direction_label = direction_label
        self._attr_name = (
            f"FGC {station_name} → {direction_label}"
            if direction_label
            else f"FGC {station_name}"
        )
        self._attr_unique_id = f"{entry.entry_id}_{station_code}_{slugify(destination)}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _upcoming(self) -> list[dict]:
        return self.coordinator.data.get(self._station_code, {}).get(
            self._destination, []
        )

    @property
    def native_value(self) -> int | None:
        upcoming = self._upcoming
        if not upcoming:
            return None
        delta = upcoming[0]["datetime"] - dt_util.now()
        return max(0, int(delta.total_seconds() // 60))

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            ATTR_STATION_NAME: self._station_name,
            ATTR_STATION_CODE: self._station_code,
        }
        if self._direction_label:
            attrs[ATTR_DIRECTION] = self._direction_label
        upcoming = self._upcoming
        if not upcoming:
            return attrs
        next_dep = upcoming[0]
        attrs.update(
            {
                ATTR_LINE: next_dep["line"],
                ATTR_LINE_COLOR: next_dep["line_color"],
                ATTR_LINE_TEXT_COLOR: next_dep["line_text_color"],
                ATTR_DESTINATION: next_dep["destination"],
                ATTR_PLATFORM: next_dep["platform"],
                ATTR_NEXT_DEPARTURE: next_dep["datetime"].isoformat(),
                ATTR_UPCOMING: [
                    {
                        ATTR_LINE: dep["line"],
                        ATTR_LINE_COLOR: dep["line_color"],
                        ATTR_LINE_TEXT_COLOR: dep["line_text_color"],
                        ATTR_DESTINATION: dep["destination"],
                        ATTR_PLATFORM: dep["platform"],
                        ATTR_NEXT_DEPARTURE: dep["datetime"].isoformat(),
                    }
                    for dep in upcoming[1:]
                ],
            }
        )
        return attrs
