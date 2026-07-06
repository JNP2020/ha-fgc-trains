"""The FGC Trains integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .alerts_coordinator import AlertsCoordinator
from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import (
    CONF_API_KEY,
    CONF_ENABLE_AIR_QUALITY,
    CONF_ENABLE_ALERTS,
    CONF_ENABLE_CARBON_FOOTPRINT,
    CONF_ENABLE_MAP,
    CONF_ENABLE_SKI,
    CONF_ENABLE_SKI_PARKING,
    CONF_ENABLE_WEBCAMS,
    CONF_STATIONS,
    DOMAIN,
    FRONTEND_URL_BASE,
)
from .coordinator import FgcCoordinator
from .extra_coordinators import (
    AirQualityCoordinator,
    CarbonFootprintCoordinator,
    SkiParkingCoordinator,
    WebcamCoordinator,
)
from .ski_coordinator import SkiCoordinator
from .util import slugify
from .vehicle_coordinator import FgcVehicleCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.CAMERA]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FGC Trains from a config entry."""
    await _async_register_frontend_resources(hass)

    session = async_get_clientsession(hass)
    client = FgcApiClient(session, entry.data.get(CONF_API_KEY))

    try:
        stations = await client.async_get_stations()
    except FgcAuthError as err:
        raise ConfigEntryAuthFailed("Invalid FGC API key") from err
    except FgcApiError as err:
        raise ConfigEntryNotReady(f"Could not reach the FGC API: {err}") from err

    station_codes = entry.options.get(CONF_STATIONS, [])
    coordinator = FgcCoordinator(hass, client, stations, station_codes)
    await coordinator.async_config_entry_first_refresh()

    vehicle_coordinator = None
    if entry.options.get(CONF_ENABLE_MAP, True):
        vehicle_coordinator = FgcVehicleCoordinator(hass, client)
        await vehicle_coordinator.async_config_entry_first_refresh()

    ski_coordinator = None
    if entry.options.get(CONF_ENABLE_SKI, True):
        ski_coordinator = SkiCoordinator(hass, client)
        await ski_coordinator.async_config_entry_first_refresh()

    alerts_coordinator = None
    if entry.options.get(CONF_ENABLE_ALERTS, True):
        alerts_coordinator = AlertsCoordinator(hass, client)
        await alerts_coordinator.async_config_entry_first_refresh()

    # Off by default: niche/low-demand data sources added after the core
    # feature set, kept opt-in so most users don't pay their (small) API
    # cost for entities they'll never look at.
    air_quality_coordinator = None
    if entry.options.get(CONF_ENABLE_AIR_QUALITY, False):
        air_quality_coordinator = AirQualityCoordinator(hass, client)
        await air_quality_coordinator.async_config_entry_first_refresh()

    ski_parking_coordinator = None
    if entry.options.get(CONF_ENABLE_SKI_PARKING, False):
        ski_parking_coordinator = SkiParkingCoordinator(hass, client)
        await ski_parking_coordinator.async_config_entry_first_refresh()

    webcam_coordinator = None
    if entry.options.get(CONF_ENABLE_WEBCAMS, False):
        webcam_coordinator = WebcamCoordinator(hass, client)
        await webcam_coordinator.async_config_entry_first_refresh()

    carbon_footprint_coordinator = None
    if entry.options.get(CONF_ENABLE_CARBON_FOOTPRINT, False):
        carbon_footprint_coordinator = CarbonFootprintCoordinator(hass, client)
        await carbon_footprint_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "vehicle_coordinator": vehicle_coordinator,
        "ski_coordinator": ski_coordinator,
        "alerts_coordinator": alerts_coordinator,
        "air_quality_coordinator": air_quality_coordinator,
        "ski_parking_coordinator": ski_parking_coordinator,
        "webcam_coordinator": webcam_coordinator,
        "carbon_footprint_coordinator": carbon_footprint_coordinator,
        "client": client,
        "stations": stations,
    }

    _remove_stale_entities(
        hass,
        entry,
        coordinator,
        map_enabled=vehicle_coordinator is not None,
        webcams_enabled=webcam_coordinator is not None,
        ski_coordinator=ski_coordinator,
        alerts_enabled=alerts_coordinator is not None,
        air_quality_coordinator=air_quality_coordinator,
        ski_parking_coordinator=ski_parking_coordinator,
        carbon_footprint_coordinator=carbon_footprint_coordinator,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve custom_components/fgc/www/ at FRONTEND_URL_BASE, once per run.

    This lets the fgc-timetable-card.js Lovelace card be added from any
    dashboard without a HACS "plugin" repo — the integration serves its own
    static file directly.
    """
    if hass.data.get(DOMAIN, {}).get("_frontend_registered"):
        return
    www_dir = str(Path(__file__).parent / "www")
    try:
        try:
            # Modern, non-deprecated API (HA 2024.7+).
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [StaticPathConfig(FRONTEND_URL_BASE, www_dir, False)]
            )
        except ImportError:
            hass.http.register_static_path(FRONTEND_URL_BASE, www_dir, False)
    except Exception:  # noqa: BLE001 - never let a card-serving hiccup break setup
        _LOGGER.warning(
            "Could not register the fgc-timetable-card frontend resource; "
            "the sensors/map will still work, but the Lovelace card won't "
            "be available until this succeeds on a future reload.",
            exc_info=True,
        )
    hass.data.setdefault(DOMAIN, {})["_frontend_registered"] = True


def _remove_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: FgcCoordinator,
    map_enabled: bool,
    webcams_enabled: bool,
    ski_coordinator: SkiCoordinator | None,
    alerts_enabled: bool,
    air_quality_coordinator: AirQualityCoordinator | None,
    ski_parking_coordinator: SkiParkingCoordinator | None,
    carbon_footprint_coordinator: CarbonFootprintCoordinator | None,
) -> None:
    """Drop entities no longer relevant to the current configuration.

    Each optional feature's sensors have their own unique_id scheme, keyed
    off whichever of their coordinators is currently non-None (i.e. that
    feature is enabled) — an entity whose id doesn't show up in any of
    these is either for a removed station/destination or a feature that's
    now turned off, either way no longer wanted.

    Device trackers (live train positions) and webcam cameras have their
    own unrelated unique_id scheme and dynamic lifecycle — while enabled
    they go unavailable rather than get removed when a unit/webcam drops
    out of its feed, so each is only swept here as a whole when its
    feature is turned off. Board-image cameras, by contrast, are static
    (one per configured station, like the departure sensors), so they get
    the same "wanted set" treatment as sensors rather than an on/off sweep.
    """
    registry = er.async_get(hass)
    station_codes = entry.options.get(CONF_STATIONS, [])
    wanted_sensor_ids = {
        f"{entry.entry_id}_{code}_{slugify(destination)}"
        for code, destinations in coordinator.destinations.items()
        for destination in destinations
    }
    if ski_coordinator is not None:
        wanted_sensor_ids |= {
            f"{entry.entry_id}_ski_{slugify(name)}" for name in ski_coordinator.data
        }
    if alerts_enabled:
        wanted_sensor_ids.add(f"{entry.entry_id}_service_alerts")
    if air_quality_coordinator is not None:
        wanted_sensor_ids |= {
            f"{entry.entry_id}_airquality_{code}" for code in station_codes
        }
    if ski_parking_coordinator is not None:
        wanted_sensor_ids |= {
            f"{entry.entry_id}_skiparking_{slugify(name)}"
            for name in ski_parking_coordinator.data
        }
    if carbon_footprint_coordinator is not None:
        wanted_sensor_ids.add(f"{entry.entry_id}_carbon_footprint")

    board_prefix = f"{entry.entry_id}_board_"
    webcam_prefix = f"{entry.entry_id}_webcam_"
    wanted_board_ids = {f"{board_prefix}{code}" for code in station_codes}

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = entity_entry.unique_id or ""
        if entity_entry.domain == "sensor":
            if unique_id not in wanted_sensor_ids:
                registry.async_remove(entity_entry.entity_id)
        elif entity_entry.domain == "device_tracker" and not map_enabled:
            registry.async_remove(entity_entry.entity_id)
        elif entity_entry.domain == "camera":
            if unique_id.startswith(board_prefix):
                if unique_id not in wanted_board_ids:
                    registry.async_remove(entity_entry.entity_id)
            elif unique_id.startswith(webcam_prefix) and not webcams_enabled:
                registry.async_remove(entity_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
