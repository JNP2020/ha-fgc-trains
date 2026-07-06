"""Sensor entity for FGC network-wide train service alerts."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alerts_coordinator import AlertsCoordinator
from .const import ATTR_ALERTS, DOMAIN


class ServiceAlertsSensor(CoordinatorEntity[AlertsCoordinator], SensorEntity):
    """How many FGC train service alerts (disruptions, planned works, ...)
    are currently active, network-wide."""

    _attr_native_unit_of_measurement = "alerts"

    def __init__(self, coordinator: AlertsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "FGC Service Alerts"
        self._attr_unique_id = f"{entry.entry_id}_service_alerts"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="FGC Trains",
            manufacturer="Ferrocarrils de la Generalitat de Catalunya",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def icon(self) -> str:
        return "mdi:alert" if self.native_value else "mdi:check-circle-outline"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict:
        return {ATTR_ALERTS: self.coordinator.data or []}
