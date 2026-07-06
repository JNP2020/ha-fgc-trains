"""Coordinators for the optional, off-by-default data sources: air quality
near train stations, ski resort parking, and FGC's yearly carbon-footprint
report. All three change slowly, so each polls on its own long interval.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FgcApiClient, FgcApiError
from .const import (
    AIR_QUALITY_SCAN_INTERVAL,
    CARBON_FOOTPRINT_SCAN_INTERVAL,
    DOMAIN,
    SKI_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class AirQualityReading(TypedDict):
    station_name: str
    index: str | None
    no2: float | None
    o3: float | None
    pm10: float | None
    monitoring_station: str | None


class AirQualityCoordinator(DataUpdateCoordinator[dict[str, AirQualityReading]]):
    """Latest air-quality reading near each train station, keyed by station name."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_air_quality", update_interval=AIR_QUALITY_SCAN_INTERVAL
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, AirQualityReading]:
        try:
            rows = await self._client.async_get_air_quality()
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC air quality data: {err}") from err

        readings: dict[str, AirQualityReading] = {}
        for row in rows:
            name = row.get("stop_name")
            if not name:
                continue
            pm10_raw = row.get("data_pm10")
            try:
                pm10 = float(pm10_raw) if pm10_raw not in (None, "") else None
            except (TypeError, ValueError):
                pm10 = None
            readings[name] = AirQualityReading(
                station_name=name,
                index=row.get("iqam"),
                no2=row.get("data_no2"),
                o3=row.get("data_o3"),
                pm10=pm10,
                monitoring_station=row.get("nom_estaci"),
            )
        return readings


class ParkingFacility(TypedDict):
    name: str
    total_spaces: int | None


class SkiParkingCoordinator(DataUpdateCoordinator[dict[str, list[ParkingFacility]]]):
    """Parking facilities at each ski resort, keyed by resort name."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_ski_parking", update_interval=SKI_SCAN_INTERVAL
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, list[ParkingFacility]]:
        try:
            rows = await self._client.async_get_ski_parking()
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC ski parking data: {err}") from err

        by_resort: dict[str, list[ParkingFacility]] = {}
        for row in rows:
            resort = row.get("name_bu")
            name = row.get("name_ca")
            if not resort or not name:
                continue
            spaces_raw = row.get("total_spaces")
            try:
                spaces = int(spaces_raw) if spaces_raw not in (None, "") else None
            except (TypeError, ValueError):
                spaces = None
            by_resort.setdefault(resort, []).append(
                ParkingFacility(name=name, total_spaces=spaces)
            )
        return by_resort


class CarbonFootprint(TypedDict):
    year: str
    total_tco2e: float
    mobility_tco2e: float
    tourism_tco2e: float
    by_scope: dict[str, float]


class CarbonFootprintCoordinator(DataUpdateCoordinator[CarbonFootprint | None]):
    """FGC's most recent yearly greenhouse-gas emissions report."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_carbon_footprint",
            update_interval=CARBON_FOOTPRINT_SCAN_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> CarbonFootprint | None:
        try:
            rows = await self._client.async_get_carbon_footprint()
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC carbon footprint data: {err}") from err

        years = {row["any"] for row in rows if row.get("any")}
        if not years:
            return None
        latest_year = max(years)

        by_scope: dict[str, float] = {}
        mobility_total = 0.0
        tourism_total = 0.0
        grand_total = 0.0
        for row in rows:
            if row.get("any") != latest_year:
                continue
            scope = row.get("abast") or "?"
            total = row.get("total") or 0.0
            by_scope[scope] = by_scope.get(scope, 0.0) + total
            mobility_total += row.get("mobilitat") or 0.0
            tourism_total += row.get("turisme") or 0.0
            grand_total += total

        return CarbonFootprint(
            year=latest_year,
            total_tco2e=round(grand_total, 2),
            mobility_tco2e=round(mobility_total, 2),
            tourism_tco2e=round(tourism_total, 2),
            by_scope={k: round(v, 2) for k, v in by_scope.items()},
        )


class Webcam(TypedDict):
    webcam_id: str
    resort_name: str
    name: str
    url: str


class WebcamCoordinator(DataUpdateCoordinator[dict[str, Webcam]]):
    """The list of currently-active ski resort webcams and their image URLs.

    Only refreshes the *list* (which webcams exist and their URL) on this
    interval; the actual image is fetched on demand by each camera entity
    whenever something asks to view it, not on a schedule.
    """

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_webcams", update_interval=SKI_SCAN_INTERVAL
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, Webcam]:
        try:
            rows = await self._client.async_get_ski_webcams()
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC webcams: {err}") from err

        webcams: dict[str, Webcam] = {}
        for row in rows:
            if row.get("is_active") != 1:
                continue
            webcam_id = row.get("id")
            resort = row.get("name_bu")
            url = row.get("url")
            if webcam_id is None or not resort or not url:
                continue
            webcam_id = str(webcam_id)
            webcams[webcam_id] = Webcam(
                webcam_id=webcam_id,
                resort_name=resort,
                name=row.get("nom_servei") or webcam_id,
                url=url,
            )
        return webcams
