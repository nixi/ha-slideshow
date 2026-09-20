"""The SlideShow Digital Signage integration."""

from __future__ import annotations

import secrets
from datetime import timedelta

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SlideshowClient
from .const import (
    CONF_PANEL_SECRET,
    CONF_PANEL_TEMPLATE,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PANEL_TEMPLATE,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .panel import PanelRenderer, async_register_views

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: SlideshowConfigEntry) -> bool:
    """Set up a SlideShow player from a config entry."""
    client = SlideshowClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        use_ssl=entry.data.get(CONF_SSL, False),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, False),
    )

    scan_interval = timedelta(
        seconds=entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
    )
    coordinator = SlideshowCoordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    # The panel is reachable without a Home Assistant login, so its URL carries
    # a secret generated once per player and kept in the entry.
    if not entry.data.get(CONF_PANEL_SECRET):
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_PANEL_SECRET: secrets.token_urlsafe(32)},
        )

    async_register_views(hass)
    panel = PanelRenderer(
        hass,
        entry,
        entry.options.get(CONF_PANEL_TEMPLATE) or DEFAULT_PANEL_TEMPLATE,
    )
    await panel.async_start()
    entry.async_on_unload(panel.async_stop)
    coordinator.panel = panel

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SlideshowConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: SlideshowConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
