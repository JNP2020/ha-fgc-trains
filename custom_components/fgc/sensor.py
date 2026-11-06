"""Sensor platform for FGC Trains."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

try:  # UnitOfTime.MINUTES landed in newer HA cores; fall back for older ones.
    from homeassistant.const import UnitOfTime

    _MINUTES = UnitOfTime.MINUTES
except ImportError:  # pragma: no cover
    _MINUTES = "min"

if TYPE_CHECKING:
    from . import FgcConfigEntry

from .alerts_sensor import ServiceAlertsSensor
from .const import (
    ATTR_DESTINATION,
    ATTR_DIRECTION,
    ATTR_LINE,
    ATTR_LINE_COLOR,
    ATTR_LINE_TEXT_COLOR,
    ATTR_NEXT_DEPARTURE,
    ATTR_PLATFORM,
    ATTR_REALTIME,
    ATTR_STATION_CODE,
    ATTR_STATION_NAME,
    ATTR_UPCOMING,
    CONF_STATIONS,
    DOMAIN,
)
from .coordinator import FgcCoordinator
from .extra_sensors import AirQualitySensor, CarbonFootprintSensor, SkiParkingSensor
from .ski_coordinator import SkiCoordinator
from .ski_sensor import SkiResortSensor
from .util import slugify


async def async_setup_entry(
    hass: HomeAssistant, entry: FgcConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one sensor per destination for each configured station, plus
    the optional ski/air-quality/parking/carbon-footprint sensors for
    whichever of those features are enabled.

    A station with trains heading to several distinct destinations (e.g. an
    intermediate stop, or a hub terminus spreading lines across platforms)
    gets one sensor per destination; a station with a single destination all
    day just gets one sensor. The coordinator has already done its first
    refresh by the time this runs, so `destinations` is populated for every
    configured station.
    """
    data = entry.runtime_data
    coordinator: FgcCoordinator = data["coordinator"]
    stations: dict[str, dict] = data["stations"]

    def _departure_entities() -> list[SensorEntity]:
        """A minutes sensor and a next-departure timestamp sensor for every
        destination currently known at every configured station."""
        found: list[SensorEntity] = []
        for code in entry.options.get(CONF_STATIONS, []):
            station_name = stations.get(code, {}).get("name", code)
            destinations = coordinator.destinations.get(code, [])
            single_destination = len(destinations) <= 1
            for destination in destinations:
                args = (
                    coordinator,
                    entry,
                    code,
                    destination,
                    station_name,
                    None if single_destination else destination,
                )
                found.append(FgcDepartureSensor(*args))
                found.append(FgcNextDepartureSensor(*args))
        return found

    entities: list[SensorEntity] = _departure_entities()

    alerts_coordinator = data.get("alerts_coordinator")
    if alerts_coordinator is not None:
        entities.append(ServiceAlertsSensor(alerts_coordinator, entry))

    ski_coordinator: SkiCoordinator | None = data.get("ski_coordinator")
    if ski_coordinator is not None:
        for resort_name in ski_coordinator.data:
            entities.append(SkiResortSensor(ski_coordinator, entry, resort_name))

    air_quality_coordinator = data.get("air_quality_coordinator")
    if air_quality_coordinator is not None:
        for code in entry.options.get(CONF_STATIONS, []):
            station_name = stations.get(code, {}).get("name", code)
            if station_name in air_quality_coordinator.data:
                entities.append(
                    AirQualitySensor(air_quality_coordinator, entry, code, station_name)
                )

    ski_parking_coordinator = data.get("ski_parking_coordinator")
    if ski_parking_coordinator is not None:
        for resort_name in ski_parking_coordinator.data:
            entities.append(SkiParkingSensor(ski_parking_coordinator, entry, resort_name))

    carbon_footprint_coordinator = data.get("carbon_footprint_coordinator")
    if carbon_footprint_coordinator is not None and carbon_footprint_coordinator.data is not None:
        entities.append(CarbonFootprintSensor(carbon_footprint_coordinator, entry))

    async_add_entities(entities)

    known_optional_ids = {entity.unique_id for entity in entities}

    def _add_optional(new_entities: list[SensorEntity]) -> None:
        new_entities = [
            entity
            for entity in new_entities
            if entity.unique_id not in known_optional_ids
        ]
        if new_entities:
            known_optional_ids.update(entity.unique_id for entity in new_entities)
            async_add_entities(new_entities)

    # A destination can show up after startup (a branch that only runs at
    # weekends, a works diversion, ...): give it its sensors when it does.
    @callback
    def _add_departure_entities() -> None:
        _add_optional(_departure_entities())

    entry.async_on_unload(coordinator.async_add_listener(_add_departure_entities))

    if ski_coordinator is not None:

        @callback
        def _add_ski_entities() -> None:
            _add_optional(
                [
                    SkiResortSensor(ski_coordinator, entry, resort_name)
                    for resort_name in ski_coordinator.data
                ]
            )

        entry.async_on_unload(ski_coordinator.async_add_listener(_add_ski_entities))

    if air_quality_coordinator is not None:

        @callback
        def _add_air_quality_entities() -> None:
            _add_optional(
                [
                    AirQualitySensor(
                        air_quality_coordinator,
                        entry,
                        code,
                        stations.get(code, {}).get("name", code),
                    )
                    for code in entry.options.get(CONF_STATIONS, [])
                    if stations.get(code, {}).get("name", code)
                    in air_quality_coordinator.data
                ]
            )

        entry.async_on_unload(
            air_quality_coordinator.async_add_listener(_add_air_quality_entities)
        )

    if ski_parking_coordinator is not None:

        @callback
        def _add_parking_entities() -> None:
            _add_optional(
                [
                    SkiParkingSensor(ski_parking_coordinator, entry, resort_name)
                    for resort_name in ski_parking_coordinator.data
                ]
            )

        entry.async_on_unload(
            ski_parking_coordinator.async_add_listener(_add_parking_entities)
        )

    if carbon_footprint_coordinator is not None:

        @callback
        def _add_carbon_entity() -> None:
            if carbon_footprint_coordinator.data is not None:
                _add_optional(
                    [CarbonFootprintSensor(carbon_footprint_coordinator, entry)]
                )

        entry.async_on_unload(
            carbon_footprint_coordinator.async_add_listener(_add_carbon_entity)
        )


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
                ATTR_REALTIME: next_dep["realtime"],
                ATTR_UPCOMING: [
                    {
                        ATTR_LINE: dep["line"],
                        ATTR_LINE_COLOR: dep["line_color"],
                        ATTR_LINE_TEXT_COLOR: dep["line_text_color"],
                        ATTR_DESTINATION: dep["destination"],
                        ATTR_PLATFORM: dep["platform"],
                        ATTR_NEXT_DEPARTURE: dep["datetime"].isoformat(),
                        ATTR_REALTIME: dep["realtime"],
                    }
                    for dep in upcoming[1:]
                ],
            }
        )
        return attrs


class FgcNextDepartureSensor(FgcDepartureSensor):
    """When the next train to one destination leaves, as a timestamp.

    Same data as the minutes sensor, but a real `timestamp` is what
    automations and templates want ("notify me 10 minutes before") and what
    the UI renders as a relative time. It has a separate unique id, so it
    sits alongside the original sensor without touching it.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:train-variant"

    def __init__(
        self,
        coordinator: FgcCoordinator,
        entry: ConfigEntry,
        station_code: str,
        destination: str,
        station_name: str,
        direction_label: str | None,
    ) -> None:
        super().__init__(
            coordinator, entry, station_code, destination, station_name, direction_label
        )
        self._attr_name = f"{self._attr_name} next departure"
        self._attr_unique_id = f"{self._attr_unique_id}_next_departure"

    @property
    def native_value(self):
        upcoming = self._upcoming
        return upcoming[0]["datetime"] if upcoming else None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            ATTR_STATION_NAME: self._station_name,
            ATTR_STATION_CODE: self._station_code,
        }
        upcoming = self._upcoming
        if upcoming:
            attrs[ATTR_REALTIME] = upcoming[0]["realtime"]
        return attrs
