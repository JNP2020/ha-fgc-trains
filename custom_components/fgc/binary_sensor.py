"""Binary sensor for FGC network-wide service disruptions."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alerts_coordinator import AlertsCoordinator
from .const import ATTR_ALERTS, DOMAIN

if TYPE_CHECKING:
    from . import FgcConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: FgcConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the disruption sensor if the service-alerts feature is enabled."""
    coordinator: AlertsCoordinator | None = entry.runtime_data["alerts_coordinator"]
    if coordinator is not None:
        async_add_entities([ServiceDisruptionBinarySensor(coordinator, entry)])


class ServiceDisruptionBinarySensor(
    CoordinatorEntity[AlertsCoordinator], BinarySensorEntity
):
    """On while FGC has at least one active service alert.

    The "FGC Service Alerts" sensor already carries the alert count and
    texts; this is the same information as a plain on/off problem state,
    which is easier to use in automations and on dashboards.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: AlertsCoordinator, entry: FgcConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "FGC Service Disruption"
        self._attr_unique_id = f"{entry.entry_id}_service_disruption"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict:
        return {ATTR_ALERTS: self.coordinator.data or []}
