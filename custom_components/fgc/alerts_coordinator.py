"""Coordinator for FGC's network/line-wide train service alerts.

Distinct from the GTFS-Realtime "alerts" feed (which is extremely noisy —
mostly routine per-trip annotations like "connects to the Montserrat
funicular", not real disruptions) and from the ski-resort alerts feed —
this is FGC's own small, clean feed of actual service disruptions/planned
works, in plain text.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FgcApiClient, FgcApiError, FgcAuthError
from .const import ALERTS_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ServiceAlert(TypedDict):
    id: int | None
    text: str
    severity: str | None
    alert_type: str | None
    valid_from: str | None
    valid_until: str | None


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class AlertsCoordinator(DataUpdateCoordinator[list[ServiceAlert]]):
    """The list of currently-active FGC train service alerts."""

    def __init__(self, hass: HomeAssistant, client: FgcApiClient) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_alerts", update_interval=ALERTS_SCAN_INTERVAL
        )
        self._client = client

    async def _async_update_data(self) -> list[ServiceAlert]:
        try:
            rows = await self._client.async_get_service_alerts()
        except FgcAuthError as err:
            raise ConfigEntryAuthFailed("Invalid FGC API key") from err
        except FgcApiError as err:
            raise UpdateFailed(f"Error fetching FGC service alerts: {err}") from err

        now = dt_util.now()
        active: list[ServiceAlert] = []
        for row in rows:
            valid_from = _parse_dt(row.get("from"))
            valid_until = _parse_dt(row.get("to"))
            if valid_from and valid_from > now:
                continue  # not started yet
            if valid_until and valid_until < now:
                continue  # already expired
            text = row.get("textca") or row.get("texten") or row.get("textes")
            if not text:
                continue
            active.append(
                ServiceAlert(
                    id=row.get("notificationid"),
                    text=text,
                    severity=row.get("severity"),
                    alert_type=row.get("type"),
                    valid_from=valid_from.isoformat() if valid_from else None,
                    valid_until=valid_until.isoformat() if valid_until else None,
                )
            )
        return active
