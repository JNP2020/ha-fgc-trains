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

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FGC Trains from a config entry."""
    session = async_get_clientsession(hass)
    client = FgcApiClient(session, entry.data.get(CONF_API_KEY))

    try:
        station_names = await client.async_get_stations()
    except FgcAuthError as err:
        raise ConfigEntryAuthFailed("Invalid FGC API key") from err
    except FgcApiError as err:
        raise ConfigEntryNotReady(f"Could not reach the FGC API: {err}") from err

    station_codes = entry.options.get(CONF_STATIONS, [])
    coordinator = FgcCoordinator(hass, client, station_codes)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "station_names": station_names,
    }

    _remove_stale_entities(hass, entry, coordinator)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: FgcCoordinator
) -> None:
    """Drop entities for platforms/stations no longer configured.

    Each entity's unique_id is keyed by platform `stop_id`, discovered via
    `coordinator.platform_labels` (populated by the first refresh above).
    """
    registry = er.async_get(hass)
    wanted_stop_ids = {
        stop_id
        for labels in coordinator.platform_labels.values()
        for stop_id in labels
    }
    wanted_unique_ids = {f"{entry.entry_id}_{stop_id}" for stop_id in wanted_stop_ids}
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.unique_id not in wanted_unique_ids:
            registry.async_remove(entity_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
