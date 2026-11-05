"""Diagnostics support for the SlideShow integration."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import SlideshowError
from .const import CONF_PANEL_SECRET
from .coordinator import SlideshowConfigEntry

# IPv4 and IPv6 literals. A connection error names the address the host
# resolved to, which differs from the configured host when that is a name.
_ADDRESS = re.compile(
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b"
)

TO_REDACT = {
    CONF_HOST,
    CONF_PANEL_SECRET,
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

    def error(err: SlideshowError) -> dict[str, str]:
        # Connection errors name the player's address, which is redacted
        # everywhere else in the report.
        text = str(err).replace(entry.data[CONF_HOST], REDACTED)
        return {"error": _ADDRESS.sub(REDACTED, text)}

    try:
        zones: Any = await coordinator.client.async_get_zones()
    except SlideshowError as err:
        zones = error(err)

    try:
        displays: Any = await coordinator.client.async_get_display_info()
    except SlideshowError as err:
        displays = error(err)

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "device_info": async_redact_data(coordinator.data or {}, TO_REDACT),
        "zones": zones,
        "zone_content": coordinator.zones,
        "layouts": list(coordinator.layouts.values()),
        "displays": displays,
    }
