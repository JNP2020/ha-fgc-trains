"""Shared fixtures: a fake FGC API client so the integration can be set up
inside a real (test) Home Assistant instance without any network access."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fgc.api import FgcApiError
from custom_components.fgc.const import (
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
)

STATIONS = {"SC": {"name": "Sant Cugat Centre", "stop_ids": ["SC1", "SC2"]}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/fgc in every test."""
    return


class FakeClient:
    """Stands in for FgcApiClient; tests tweak its attributes to steer it."""

    instances: list[FakeClient] = []

    def __init__(self, session=None, api_key=None) -> None:
        self.api_key = api_key
        self.on_low_quota = None
        self.on_quota_recovered = None
        self.fail_schedule = False
        self.schedule_calls = 0
        self.alerts: list[dict] = []
        FakeClient.instances.append(self)

    async def async_get_stations(self):
        return STATIONS

    async def async_get_day_schedule(self, stop_ids):
        self.schedule_calls += 1
        if self.fail_schedule:
            raise FgcApiError("boom")
        base = dt_util.now() + timedelta(hours=1)
        rows = []
        for minutes, headsign, line in ((0, "Barcelona - Plaça Catalunya", "S1"), (20, "Terrassa", "S1")):
            when = base + timedelta(minutes=minutes)
            rows.append(
                {
                    "stop_id": "SC1",
                    "departure_time": when.strftime("%H:%M:00"),
                    "route_short_name": line,
                    "trip_headsign": headsign,
                    "platform_code": 1.0,
                    "stop_name": "Sant Cugat Centre",
                    "route_color": "EF7900",
                    "route_text_color": "FFFFFF",
                }
            )
        return rows

    async def async_get_realtime_departures(self):
        return {}

    async def async_get_service_alerts(self):
        return self.alerts


@pytest.fixture
def fake_client():
    FakeClient.instances.clear()
    with (
        patch("custom_components.fgc.FgcApiClient", FakeClient),
        patch("custom_components.fgc.config_flow.FgcApiClient", FakeClient),
        patch("custom_components.fgc._async_register_frontend_resources"),
    ):
        yield FakeClient


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    # The manifest depends on frontend/http (for the bundled Lovelace card);
    # mark them as already set up rather than booting a whole frontend.
    for component in ("frontend", "http", "lovelace"):
        hass.config.components.add(component)
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="FGC Trains",
        unique_id=DOMAIN,
        data={CONF_API_KEY: "super-secret"},
        options={
            CONF_STATIONS: ["SC"],
            CONF_ENABLE_MAP: False,
            CONF_ENABLE_SKI: False,
            CONF_ENABLE_ALERTS: True,
            CONF_ENABLE_AIR_QUALITY: False,
            CONF_ENABLE_SKI_PARKING: False,
            CONF_ENABLE_WEBCAMS: False,
            CONF_ENABLE_CARBON_FOOTPRINT: False,
        },
    )
    config_entry.add_to_hass(hass)
    return config_entry
