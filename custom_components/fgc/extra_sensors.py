"""Sensor entities for the optional, off-by-default data sources: air
quality near train stations, ski resort parking, and FGC's yearly
carbon-footprint report.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_EMISSIONS_BY_SCOPE,
    ATTR_MOBILITY_EMISSIONS,
    ATTR_MONITORING_STATION,
    ATTR_NO2,
    ATTR_O3,
    ATTR_PARKING_FACILITIES,
    ATTR_PM10,
    ATTR_STATION_CODE,
    ATTR_STATION_NAME,
    ATTR_TOURISM_EMISSIONS,
    ATTR_YEAR,
    DOMAIN,
)
from .extra_coordinators import (
    AirQualityCoordinator,
    CarbonFootprintCoordinator,
    SkiParkingCoordinator,
)
from .util import slugify


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="FGC Trains",
        manufacturer="Ferrocarrils de la Generalitat de Catalunya",
        entry_type=DeviceEntryType.SERVICE,
    )


class AirQualitySensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """Air-quality index near one train station."""

    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        entry: ConfigEntry,
        station_code: str,
        station_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_code = station_code
        self._station_name = station_name
        self._attr_name = f"FGC {station_name} Air Quality"
        self._attr_unique_id = f"{entry.entry_id}_airquality_{station_code}"
        self._attr_device_info = _device_info(entry)

    @property
    def _reading(self) -> dict | None:
        return self.coordinator.data.get(self._station_name)

    @property
    def available(self) -> bool:
        return super().available and self._reading is not None

    @property
    def native_value(self) -> str | None:
        reading = self._reading
        return reading["index"] if reading else None

    @property
    def extra_state_attributes(self) -> dict:
        reading = self._reading
        attrs = {
            ATTR_STATION_NAME: self._station_name,
            ATTR_STATION_CODE: self._station_code,
        }
        if reading:
            attrs.update(
                {
                    ATTR_NO2: reading["no2"],
                    ATTR_O3: reading["o3"],
                    ATTR_PM10: reading["pm10"],
                    ATTR_MONITORING_STATION: reading["monitoring_station"],
                }
            )
        return attrs


class SkiParkingSensor(CoordinatorEntity[SkiParkingCoordinator], SensorEntity):
    """Total parking spaces at one ski resort."""

    _attr_icon = "mdi:parking"
    _attr_native_unit_of_measurement = "spaces"

    def __init__(
        self, coordinator: SkiParkingCoordinator, entry: ConfigEntry, resort_name: str
    ) -> None:
        super().__init__(coordinator)
        self._resort_name = resort_name
        self._attr_name = f"FGC Ski {resort_name} Parking"
        self._attr_unique_id = f"{entry.entry_id}_skiparking_{slugify(resort_name)}"
        self._attr_device_info = _device_info(entry)

    @property
    def _facilities(self) -> list[dict] | None:
        return self.coordinator.data.get(self._resort_name)

    @property
    def available(self) -> bool:
        return super().available and self._facilities is not None

    @property
    def native_value(self) -> int | None:
        facilities = self._facilities
        if facilities is None:
            return None
        known = [f["total_spaces"] for f in facilities if f["total_spaces"] is not None]
        return sum(known) if known else None

    @property
    def extra_state_attributes(self) -> dict:
        facilities = self._facilities or []
        return {ATTR_PARKING_FACILITIES: facilities}


class CarbonFootprintSensor(CoordinatorEntity[CarbonFootprintCoordinator], SensorEntity):
    """FGC's total greenhouse-gas emissions for the most recent reported year."""

    _attr_icon = "mdi:molecule-co2"
    _attr_native_unit_of_measurement = "t CO2e"

    def __init__(self, coordinator: CarbonFootprintCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "FGC Carbon Footprint"
        self._attr_unique_id = f"{entry.entry_id}_carbon_footprint"
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return data["total_tco2e"] if data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        return {
            ATTR_YEAR: data["year"],
            ATTR_MOBILITY_EMISSIONS: data["mobility_tco2e"],
            ATTR_TOURISM_EMISSIONS: data["tourism_tco2e"],
            ATTR_EMISSIONS_BY_SCOPE: data["by_scope"],
        }
