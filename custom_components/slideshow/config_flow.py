"""Config flow for the SlideShow Digital Signage integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    SlideshowAuthError,
    SlideshowClient,
    SlideshowConnectionError,
    SlideshowError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_PASSWORD,
    DEFAULT_PORT_HTTP,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import SlideshowConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT_HTTP): int,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
        vol.Required(CONF_SSL, default=False): bool,
        vol.Required(CONF_VERIFY_SSL, default=False): bool,
    }
)


async def _async_validate(hass, data: Mapping[str, Any]) -> dict[str, Any]:
    """Connect to the player and return its device info."""
    client = SlideshowClient(
        async_get_clientsession(hass),
        data[CONF_HOST],
        data[CONF_PORT],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        use_ssl=data.get(CONF_SSL, False),
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )
    return await client.async_get_device_info()


class SlideshowConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user-initiated setup of a player."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the player's address and credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _async_validate(self.hass, user_input)
            except SlideshowAuthError:
                errors["base"] = "invalid_auth"
            except SlideshowConnectionError:
                errors["base"] = "cannot_connect"
            except SlideshowError:
                _LOGGER.exception("Unexpected error talking to SlideShow")
                errors["base"] = "unknown"
            else:
                device_id = info.get("deviceId")
                if not device_id:
                    errors["base"] = "no_device_id"
                else:
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured(updates=dict(user_input))
                    return self.async_create_entry(
                        title=info.get("deviceName") or user_input[CONF_HOST],
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the re-authentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for fresh credentials for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await _async_validate(self.hass, data)
            except SlideshowAuthError:
                errors["base"] = "invalid_auth"
            except SlideshowConnectionError:
                errors["base"] = "cannot_connect"
            except SlideshowError:
                _LOGGER.exception("Unexpected error talking to SlideShow")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: SlideshowConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SlideshowOptionsFlow()


class SlideshowOptionsFlow(OptionsFlow):
    """Let the user tune the polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
