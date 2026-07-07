"""Config flow for FGC Trains.

One config entry acts as a single "hub" holding the optional API key; the
list of monitored stations lives in the entry's options and is grown or
shrunk afterwards via the options flow (Configure -> add/remove station).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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
    CONF_STATION_CODE,
    CONF_STATIONS,
    DOMAIN,
)


def _station_options(stations: dict[str, dict]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=code, label=info["name"])
        for code, info in sorted(stations.items(), key=lambda kv: kv[1]["name"])
    ]


async def _async_validate_api_key(hass, api_key: str | None) -> str | None:
    """Try the key against the API; return an error code, or None if valid."""
    client = FgcApiClient(async_get_clientsession(hass), api_key)
    try:
        await client.async_get_stations()
    except FgcAuthError:
        return "invalid_auth"
    except FgcApiError:
        return "cannot_connect"
    return None


class FgcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: validate the API key, pick the first station."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._stations: dict[str, dict] = {}
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            api_key = user_input.get(CONF_API_KEY) or None
            client = FgcApiClient(async_get_clientsession(self.hass), api_key)
            try:
                self._stations = await client.async_get_stations()
            except FgcAuthError:
                errors["base"] = "invalid_auth"
            except FgcApiError:
                errors["base"] = "cannot_connect"
            else:
                self._api_key = api_key
                return await self.async_step_station()

        schema = vol.Schema({vol.Optional(CONF_API_KEY): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            return self.async_create_entry(
                title="FGC Trains",
                data={CONF_API_KEY: self._api_key},
                options={CONF_STATIONS: [user_input[CONF_STATION_CODE]]},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_CODE): SelectSelector(
                    SelectSelectorConfig(
                        options=_station_options(self._stations),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="station", data_schema=schema)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Triggered automatically by Home Assistant when the API key stops
        working (ConfigEntryAuthFailed) — lets the user supply a new one
        without losing their configured stations/settings."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY) or None
            error = await _async_validate_api_key(self.hass, api_key)
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_API_KEY: api_key},
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema({vol.Optional(CONF_API_KEY): str})
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FgcOptionsFlow:
        return FgcOptionsFlow()


class FgcOptionsFlow(OptionsFlow):
    """Add or remove monitored stations from an existing entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_station", "remove_station", "api_key", "settings"],
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Update the FGC API key without needing to remove and re-add the
        whole integration (e.g. if it's revoked, or added after starting
        out with anonymous access)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY) or None
            error = await _async_validate_api_key(self.hass, api_key)
            if error:
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_API_KEY: api_key},
                )
                return self.async_create_entry(title="", data=self.config_entry.options)

        schema = vol.Schema({vol.Optional(CONF_API_KEY): str})
        return self.async_show_form(
            step_id="api_key", data_schema=schema, errors=errors
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, **user_input},
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_MAP, default=options.get(CONF_ENABLE_MAP, True)
                ): bool,
                vol.Required(
                    CONF_ENABLE_SKI, default=options.get(CONF_ENABLE_SKI, True)
                ): bool,
                vol.Required(
                    CONF_ENABLE_ALERTS, default=options.get(CONF_ENABLE_ALERTS, True)
                ): bool,
                vol.Required(
                    CONF_ENABLE_AIR_QUALITY,
                    default=options.get(CONF_ENABLE_AIR_QUALITY, False),
                ): bool,
                vol.Required(
                    CONF_ENABLE_SKI_PARKING,
                    default=options.get(CONF_ENABLE_SKI_PARKING, False),
                ): bool,
                vol.Required(
                    CONF_ENABLE_WEBCAMS,
                    default=options.get(CONF_ENABLE_WEBCAMS, False),
                ): bool,
                vol.Required(
                    CONF_ENABLE_CARBON_FOOTPRINT,
                    default=options.get(CONF_ENABLE_CARBON_FOOTPRINT, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_add_station(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        current = self.config_entry.options.get(CONF_STATIONS, [])
        client = FgcApiClient(
            async_get_clientsession(self.hass),
            self.config_entry.data.get(CONF_API_KEY),
        )
        try:
            stations = await client.async_get_stations()
        except FgcApiError:
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            updated = list(dict.fromkeys(current + user_input[CONF_STATION_CODE]))
            return self.async_create_entry(
                title="", data={**self.config_entry.options, CONF_STATIONS: updated}
            )

        available = {code: info for code, info in stations.items() if code not in current}
        if not available:
            return self.async_abort(reason="no_stations_available")

        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_CODE, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=_station_options(available),
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="add_station", data_schema=schema)

    async def async_step_remove_station(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        current = self.config_entry.options.get(CONF_STATIONS, [])
        if not current:
            return self.async_abort(reason="no_stations_configured")

        if user_input is not None:
            to_remove = set(user_input[CONF_STATION_CODE])
            updated = [code for code in current if code not in to_remove]
            return self.async_create_entry(
                title="", data={**self.config_entry.options, CONF_STATIONS: updated}
            )

        stations = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        ).get("stations", {})
        options = [
            SelectOptionDict(value=code, label=stations.get(code, {}).get("name", code))
            for code in current
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_CODE, default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_station", data_schema=schema)
