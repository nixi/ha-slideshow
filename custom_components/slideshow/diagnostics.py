"""Diagnostics support for the SlideShow integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import SlideshowError
from .coordinator import SlideshowConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "macAddress",
    "ipAddressInternal",
    "serialNumber",
    "deviceId",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SlideshowConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    try:
        zones: Any = await coordinator.client.async_get_zones()
    except SlideshowError as err:
        zones = {"error": str(err)}

    try:
        displays: Any = await coordinator.client.async_get_display_info()
    except SlideshowError as err:
        displays = {"error": str(err)}

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device_info": async_redact_data(coordinator.data or {}, TO_REDACT),
        "zones": zones,
        "displays": displays,
    }
