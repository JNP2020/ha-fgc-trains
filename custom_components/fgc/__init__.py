"""The FGC Trains integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import CONF_API_KEY, CONF_STATIONS, DOMAIN
from .coordinator import FgcCoordinator
from .util import slugify
from .vehicle_coordinator import FgcVehicleCoordinator

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FGC Trains from a config entry."""
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

    vehicle_coordinator = FgcVehicleCoordinator(hass, client)
    await vehicle_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "vehicle_coordinator": vehicle_coordinator,
        "client": client,
        "stations": stations,
    }

    _remove_stale_entities(hass, entry, coordinator)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: FgcCoordinator
) -> None:
    """Drop *sensor* entities for stations/destinations no longer configured.

    Each sensor's unique_id is keyed by station code + destination slug,
    discovered via `coordinator.destinations` (populated by the first
    refresh above). Device trackers (live train positions) have their own
    unrelated unique_id scheme and lifecycle (they go unavailable rather
    than get removed when a unit drops out of the feed), so this only ever
    touches the `sensor` domain.
    """
    registry = er.async_get(hass)
    wanted_unique_ids = {
        f"{entry.entry_id}_{code}_{slugify(destination)}"
        for code, destinations in coordinator.destinations.items()
        for destination in destinations
    }
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.domain == "sensor"
            and entity_entry.unique_id not in wanted_unique_ids
        ):
            registry.async_remove(entity_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
