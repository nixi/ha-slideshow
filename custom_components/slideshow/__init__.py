"""The SlideShow Digital Signage integration."""

from __future__ import annotations

import secrets
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .api import SlideshowClient
from .const import (
    CONF_PANEL_SECRET,
    CONF_PANEL_TEMPLATE,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PANEL_TEMPLATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_GET_PANEL_URL,
)
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .panel import (
    NO_URL_MESSAGE,
    PanelRenderer,
    async_register_views,
    panel_base_url,
    panel_path,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.MEDIA_PLAYER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's admin-only actions."""

    async def async_get_panel_url(call: ServiceCall) -> ServiceResponse:
        """Return a player's panel address.

        The address carries the secret that guards an unauthenticated page,
        so it is only ever handed to an administrator, never kept in a state.
        """
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise ServiceValidationError("That SlideShow player is not loaded")
        try:
            base = panel_base_url(hass)
        except NoURLAvailableError as err:
            raise HomeAssistantError(NO_URL_MESSAGE) from err
        return {"url": f"{base}{panel_path(entry.data[CONF_PANEL_SECRET])}"}

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_GET_PANEL_URL,
        async_get_panel_url,
        vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    return True


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
