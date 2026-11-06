"""End-to-end tests: the integration set up inside a real Home Assistant
test instance, with the FGC API replaced by `FakeClient` (see conftest)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.fgc.api import FgcApiError
from custom_components.fgc.const import CONF_API_KEY, DOMAIN
from custom_components.fgc.diagnostics import async_get_config_entry_diagnostics


async def _setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _sensor_ids(hass, entry):
    registry = er.async_get(hass)
    return {
        e.unique_id: e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "sensor"
    }


async def test_setup_creates_minutes_and_timestamp_sensors(hass, entry, fake_client):
    await _setup(hass, entry)
    ids = _sensor_ids(hass, entry)
    base = f"{entry.entry_id}_SC_"
    assert {uid for uid in ids if uid.startswith(base)} == {
        f"{base}barcelona_pla_a_catalunya",
        f"{base}barcelona_pla_a_catalunya_next_departure",
        f"{base}terrassa",
        f"{base}terrassa_next_departure",
    }

    minutes = hass.states.get(ids[f"{base}terrassa"].entity_id)
    assert minutes.state.isdigit() and 70 <= int(minutes.state) <= 80
    stamp = hass.states.get(ids[f"{base}terrassa_next_departure"].entity_id)
    assert stamp.attributes["device_class"] == "timestamp"
    assert dt_util.parse_datetime(stamp.state) > dt_util.utcnow()


async def test_station_sensors_survive_a_day_without_that_destination(hass, entry, fake_client):
    """A sensor for a destination missing from today's timetable (weekday-only
    branch on a weekend) must not be pruned; one for a removed station must."""
    registry = er.async_get(hass)
    weekday_only = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_SC_weekday_branch",
        config_entry=entry, suggested_object_id="weekday_branch",
    )
    removed_station = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_XX_somewhere",
        config_entry=entry, suggested_object_id="removed_station",
    )
    await _setup(hass, entry)
    assert registry.async_get(weekday_only.entity_id) is not None
    assert registry.async_get(removed_station.entity_id) is None


async def test_failed_refresh_keeps_todays_schedule(hass, entry, fake_client):
    await _setup(hass, entry)
    client = fake_client.instances[-1]
    coordinator = entry.runtime_data["coordinator"]
    sensor = _sensor_ids(hass, entry)[f"{entry.entry_id}_SC_terrassa"]

    client.fail_schedule = True
    cached = coordinator._schedules["SC"]
    cached["fetched_at"] -= timedelta(hours=4)  # force a refresh attempt
    calls = client.schedule_calls
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert client.schedule_calls == calls + 1
    assert coordinator.last_update_success is True
    assert hass.states.get(sensor.entity_id).state != "unavailable"

    # ...and it doesn't hammer the API on the very next tick.
    await coordinator.async_refresh()
    assert client.schedule_calls == calls + 1


async def test_failed_first_load_is_not_swallowed(hass, entry, fake_client):
    original = fake_client.async_get_day_schedule

    async def failing(self, stop_ids):
        raise FgcApiError("down")

    fake_client.async_get_day_schedule = failing
    try:
        assert not await hass.config_entries.async_setup(entry.entry_id)
    finally:
        fake_client.async_get_day_schedule = original
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_get_departures_action(hass, entry, fake_client):
    await _setup(hass, entry)
    result = await hass.services.async_call(
        DOMAIN, "get_departures", {"station": "sant cugat centre", "destination": "terr"},
        blocking=True, return_response=True,
    )
    assert result["station_code"] == "SC"
    [dep] = result["departures"]
    assert dep["destination"] == "Terrassa" and dep["line"] == "S1"

    by_code = await hass.services.async_call(
        DOMAIN, "get_departures", {"station": "sc", "limit": 1},
        blocking=True, return_response=True,
    )
    assert len(by_code["departures"]) == 1

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_departures", {"station": "Nowhere"},
            blocking=True, return_response=True,
        )


async def test_disruption_binary_sensor_follows_alerts(hass, entry, fake_client):
    await _setup(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_service_disruption"
    )
    assert hass.states.get(entity_id).state == "off"

    fake_client.instances[-1].alerts = [{"textca": "Obres", "notificationid": 1}]
    await entry.runtime_data["alerts_coordinator"].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"


async def test_diagnostics_redacts_the_api_key(hass, entry, fake_client):
    await _setup(hass, entry)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["entry"]["data"][CONF_API_KEY] == "**REDACTED**"
    assert "super-secret" not in str(data)
    assert data["stations"]["SC"]["name"] == "Sant Cugat Centre"


async def test_reconfigure_updates_the_api_key(hass, entry, fake_client):
    await _setup(hass, entry)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] == "abort" and result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
