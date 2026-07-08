"""The FGC Trains integration."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .alerts_coordinator import AlertsCoordinator
from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import (
    CARD_JS_FILENAME,
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

    vehicle_coordinator = (
        FgcVehicleCoordinator(hass, client, coordinator)
        if entry.options.get(CONF_ENABLE_MAP, True)
        else None
    )
    ski_coordinator = (
        SkiCoordinator(hass, client) if entry.options.get(CONF_ENABLE_SKI, True) else None
    )
    alerts_coordinator = (
        AlertsCoordinator(hass, client)
        if entry.options.get(CONF_ENABLE_ALERTS, True)
        else None
    )
    # Off by default: niche/low-demand data sources added after the core
    # feature set, kept opt-in so most users don't pay their (small) API
    # cost for entities they'll never look at.
    air_quality_coordinator = (
        AirQualityCoordinator(hass, client)
        if entry.options.get(CONF_ENABLE_AIR_QUALITY, False)
        else None
    )
    ski_parking_coordinator = (
        SkiParkingCoordinator(hass, client)
        if entry.options.get(CONF_ENABLE_SKI_PARKING, False)
        else None
    )
    webcam_coordinator = (
        WebcamCoordinator(hass, client)
        if entry.options.get(CONF_ENABLE_WEBCAMS, False)
        else None
    )
    carbon_footprint_coordinator = (
        CarbonFootprintCoordinator(hass, client)
        if entry.options.get(CONF_ENABLE_CARBON_FOOTPRINT, False)
        else None
    )

    # These are all secondary to the core departure-tracking feature, so a
    # hiccup fetching any one of them shouldn't stop the whole integration
    # (including the departure sensors) from loading — each just retries on
    # its own normal schedule instead. Refreshed concurrently since they're
    # independent of each other and of varying speed (e.g. the ski bundle
    # makes four separate API calls).
    await asyncio.gather(
        *(
            _first_refresh_non_blocking(name, opt_coordinator, empty_default)
            for name, opt_coordinator, empty_default in (
                ("live map", vehicle_coordinator, {}),
                ("ski resorts", ski_coordinator, {}),
                ("service alerts", alerts_coordinator, []),
                ("air quality", air_quality_coordinator, {}),
                ("ski parking", ski_parking_coordinator, {}),
                ("webcams", webcam_coordinator, {}),
                ("carbon footprint", carbon_footprint_coordinator, None),
            )
            if opt_coordinator is not None
        )
    )

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


async def _first_refresh_non_blocking(
    name: str, coordinator: DataUpdateCoordinator, empty_default
) -> None:
    """Do an optional coordinator's first refresh without letting a failure
    block the rest of setup (including the core departure sensors) — it'll
    just retry on its own schedule instead.

    `DataUpdateCoordinator.async_config_entry_first_refresh` raises
    `ConfigEntryNotReady` on failure, which is right for the primary data
    source but wrong for these secondary features. If it fails before ever
    succeeding, `coordinator.data` is left as `None`; the platform setup
    code that iterates it (sensor.py/camera.py/device_tracker.py) expects
    an empty-but-iterable value instead, hence `empty_default`.
    """
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        _LOGGER.warning(
            "Initial refresh of %s failed; it will keep retrying on its own "
            "schedule instead of blocking the rest of the integration from "
            "loading.",
            name,
        )
        if coordinator.data is None:
            coordinator.data = empty_default


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve custom_components/fgc/www/ at FRONTEND_URL_BASE and register the
    timetable card as a Lovelace resource automatically, once per run.

    This lets the fgc-timetable-card.js Lovelace card be added from any
    dashboard without a HACS "plugin" repo (the integration serves its own
    static file directly) and without the user having to add it by hand
    under Settings -> Dashboards -> Resources.
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
        add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{CARD_JS_FILENAME}")
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

    Ski and ski-parking sensors are additionally keyed off their
    coordinator's *data* (one sensor per resort actually reported), which
    is only trustworthy after a successful fetch — a coordinator whose
    first refresh failed and is sitting on the empty-dict fallback (see
    `_first_refresh_non_blocking`) would otherwise look identical to "this
    feature has no resorts", and wipe out every real sensor from a previous
    successful run over what's just a transient hiccup. So those two are
    skipped from this sweep entirely whenever their last update failed,
    leaving existing entities alone until a real refresh succeeds.

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
    ski_prefix = f"{entry.entry_id}_ski_"
    ski_data_trustworthy = ski_coordinator is not None and ski_coordinator.last_update_success
    if ski_data_trustworthy:
        wanted_sensor_ids |= {
            f"{entry.entry_id}_ski_{slugify(name)}" for name in ski_coordinator.data
        }
    if alerts_enabled:
        wanted_sensor_ids.add(f"{entry.entry_id}_service_alerts")
    if air_quality_coordinator is not None:
        wanted_sensor_ids |= {
            f"{entry.entry_id}_airquality_{code}" for code in station_codes
        }
    ski_parking_prefix = f"{entry.entry_id}_skiparking_"
    ski_parking_data_trustworthy = (
        ski_parking_coordinator is not None and ski_parking_coordinator.last_update_success
    )
    if ski_parking_data_trustworthy:
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
            if unique_id.startswith(ski_prefix) and not ski_data_trustworthy:
                continue
            if unique_id.startswith(ski_parking_prefix) and not ski_parking_data_trustworthy:
                continue
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
