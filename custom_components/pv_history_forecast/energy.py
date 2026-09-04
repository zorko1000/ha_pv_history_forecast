"""Energy dashboard solar forecast platform.

Home Assistant's ``energy`` component discovers forecast providers by looking
for an ``energy`` platform (this module) on every set-up integration and picking
up its ``async_get_solar_forecast``. Every domain that has one is returned to
the frontend as ``solar_forecast_domains``, which is what makes this
integration's config entry selectable under
**Settings -> Dashboards -> Energy -> Solar panels -> Forecast production** —
no PV plant geometry to configure, unlike Forecast.Solar.

The energy dashboard then draws ``wh_hours`` as the forecast line on the solar
production card.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def build_wh_hours(forecast_entries: Any) -> dict[str, float]:
    """Convert ``HourlyForecastSensor``'s entries into the energy ``wh_hours`` map.

    Each entry covers exactly one whole hour and carries the average power in W,
    so its value already *is* the Wh produced in that hour — only the shape
    changes: ``[{"start": iso, "end": iso, "value": w}, ...]`` becomes
    ``{iso: wh}``. Keys keep the local-time ISO strings the sensor produced;
    the frontend parses them with ``new Date()`` and buckets them by hour.
    """
    wh_hours: dict[str, float] = {}

    for entry in forecast_entries or []:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start")
        value = entry.get("value")
        if not start or value is None:
            continue
        try:
            wh_hours[str(start)] = float(value)
        except (TypeError, ValueError):
            continue

    return wh_hours


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float]] | None:
    """Return ``{"wh_hours": {...}}`` for the Energy dashboard, or None.

    Serves the series the hourly sensor already computed on its own 10-minute
    cycle; this never triggers a query of its own, so the dashboard opening does
    not cost an SQL run.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry_id) or {}
    hourly_sensor = entry_data.get("hourly_sensor")

    if hourly_sensor is None:
        return None

    wh_hours = build_wh_hours(getattr(hourly_sensor, "forecast_entries", None))

    if not wh_hours:
        return None

    return {"wh_hours": wh_hours}
