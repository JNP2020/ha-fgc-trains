"""Live map of FGC train positions.

Creates one device_tracker per active physical train unit; Home Assistant's
built-in Map (which renders on OpenStreetMap tiles) picks these up
automatically like any other GPS-source device_tracker — no custom card
needed, just add a Map card/dashboard and these show up on it.

Trains appear and disappear from the feed as service starts/stops through
the day, so entities are added dynamically as new unit ids show up; a unit
no longer present in the feed is marked unavailable rather than removed,
since it usually reappears later the same day.
"""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DESTINATION,
    ATTR_DIRECTION,
    ATTR_LINE,
    DOMAIN,
)
from .vehicle_coordinator import FgcVehicleCoordinator, VehiclePosition


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up device trackers for every currently-known train, and keep
    adding new ones as they appear in later coordinator refreshes.

    No-op if the live map has been turned off in the integration's options
    (`vehicle_coordinator` is None in that case).
    """
    coordinator: FgcVehicleCoordinator | None = hass.data[DOMAIN][entry.entry_id][
        "vehicle_coordinator"
    ]
    if coordinator is None:
        return
    known_units: set[str] = set()

    @callback
    def _add_new_vehicles() -> None:
        new_entities = [
            FgcTrainTracker(coordinator, entry, unit_id)
            for unit_id in coordinator.data
            if unit_id not in known_units
        ]
        if new_entities:
            known_units.update(entity.unit_id for entity in new_entities)
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_vehicles))
    _add_new_vehicles()


class FgcTrainTracker(CoordinatorEntity[FgcVehicleCoordinator], TrackerEntity):
    """A single physical train's live position."""

    _attr_icon = "mdi:train"

    def __init__(
        self, coordinator: FgcVehicleCoordinator, entry: ConfigEntry, unit_id: str
    ) -> None:
        super().__init__(coordinator)
        self.unit_id = unit_id
        self._attr_name = f"FGC Train {unit_id}"
        self._attr_unique_id = f"{entry.entry_id}_train_{unit_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _vehicle(self) -> VehiclePosition | None:
        return self.coordinator.data.get(self.unit_id)

    @property
    def available(self) -> bool:
        return super().available and self._vehicle is not None

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle["latitude"] if vehicle else None

    @property
    def longitude(self) -> float | None:
        vehicle = self._vehicle
        return vehicle["longitude"] if vehicle else None

    @property
    def extra_state_attributes(self) -> dict:
        vehicle = self._vehicle
        if not vehicle:
            return {}
        return {
            ATTR_LINE: vehicle["line"],
            ATTR_DIRECTION: vehicle["direction"],
            "origin": vehicle["origin_name"] or vehicle["origin"],
            ATTR_DESTINATION: vehicle["destination_name"] or vehicle["destination"],
            "next_stops": vehicle["next_stop_names"] or vehicle["next_stops"],
            "stopped_at": vehicle["stopped_at_name"] or vehicle["stopped_at"],
            "on_time": vehicle["on_time"],
            "unit_type": vehicle["unit_type"],
        }
