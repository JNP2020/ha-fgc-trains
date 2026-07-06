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
from .const import CONF_API_KEY, CONF_STATION_CODE, CONF_STATIONS, DOMAIN


def _station_options(stations: dict[str, dict]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=code, label=info["name"])
        for code, info in sorted(stations.items(), key=lambda kv: kv[1]["name"])
    ]


class FgcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup: validate the API key, pick the first station."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._stations: dict[str, dict] = {}

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
            step_id="init", menu_options=["add_station", "remove_station"]
        )

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
                vol.Required(CONF_STATION_CODE): SelectSelector(
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
                vol.Required(CONF_STATION_CODE): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_station", data_schema=schema)
