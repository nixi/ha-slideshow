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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import (
    SlideshowAuthError,
    SlideshowClient,
    SlideshowConnectionError,
    SlideshowError,
)
from .const import (
    CONF_PANEL_TEMPLATE,
    CONF_PANEL_TITLE,
    CONF_SCAN_INTERVAL,
    CONF_SCREEN_OFF_LAYOUT,
    CONF_VERIFY_SSL,
    DEFAULT_PANEL_TEMPLATE,
    DEFAULT_PANEL_TITLE,
    DEFAULT_PASSWORD,
    DEFAULT_PORT_HTTP,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCREEN_OFF_LAYOUT,
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

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Follow a known player to a new address.

        Home Assistant reports address changes for devices already in the
        device registry, including ones learned from a router integration such
        as UniFi. Players usually get their address from DHCP, so without this
        a new lease leaves the entry pointing at an address nobody answers on.
        """
        entry = self._entry_for_mac(discovery_info.macaddress)
        if entry is None:
            # The MAC is often randomised by Android, so there is no vendor
            # prefix to discover new players by; only known ones are followed.
            return self.async_abort(reason="not_supported")

        new_host = discovery_info.ip
        if entry.data.get(CONF_HOST) == new_host:
            return self.async_abort(reason="already_configured")

        # A player that is still answering at its configured address does not
        # need moving, whatever the DHCP server now says.
        try:
            await _async_validate(self.hass, entry.data)
        except SlideshowError:
            pass
        else:
            return self.async_abort(reason="already_configured")

        # Check the new address really is this player before moving to it. If
        # nothing answers there yet -- the app may still be starting -- the MAC
        # match from the device registry is trusted instead.
        try:
            info = await _async_validate(
                self.hass, {**entry.data, CONF_HOST: new_host}
            )
        except SlideshowError:
            info = None
        if info is not None and info.get("deviceId") != entry.unique_id:
            _LOGGER.warning(
                "%s reports a different player (%s) than %s expects; not moving",
                new_host,
                info.get("deviceId"),
                entry.title,
            )
            return self.async_abort(reason="already_configured")

        _LOGGER.info(
            "%s moved from %s to %s", entry.title, entry.data.get(CONF_HOST), new_host
        )
        return self.async_update_reload_and_abort(
            entry,
            data={**entry.data, CONF_HOST: new_host},
            reason="already_configured",
        )

    def _entry_for_mac(self, mac: str) -> SlideshowConfigEntry | None:
        """Return this integration's entry owning the device with this MAC."""
        registry = dr.async_get(self.hass)
        for device in registry.async_get_devices(
            connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))}
        ):
            for entry_id in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry is not None and entry.domain == DOMAIN:
                    return entry
        return None

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address a player is reached at, keeping everything else.

        Removing and re-adding the integration would work too, but it would
        also generate a new panel secret and break every player showing it.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                info = await _async_validate(self.hass, data)
            except SlideshowAuthError:
                errors["base"] = "invalid_auth"
            except SlideshowConnectionError:
                errors["base"] = "cannot_connect"
            except SlideshowError:
                _LOGGER.exception("Unexpected error talking to SlideShow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.get("deviceId"))
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT): int,
                vol.Required(CONF_SSL): bool,
                vol.Required(CONF_VERIFY_SSL): bool,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or entry.data
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the re-authentication flow.

        The player may only have been restarting or mid-reconfiguration when
        it turned the stored credentials away. If they work again by the time
        anyone opens this, there is nothing worth asking.
        """
        entry = self._get_reauth_entry()
        try:
            await _async_validate(self.hass, entry.data)
        except SlideshowError:
            return await self.async_step_reauth_confirm()

        _LOGGER.debug(
            "%s accepted the stored credentials again; no reauthentication needed",
            entry.title,
        )
        return self.async_update_reload_and_abort(entry, data=dict(entry.data))

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

        options = self.config_entry.options
        interval = options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_SCREEN_OFF_LAYOUT,
                        default=options.get(
                            CONF_SCREEN_OFF_LAYOUT, DEFAULT_SCREEN_OFF_LAYOUT
                        ),
                    ): str,
                    vol.Required(
                        CONF_PANEL_TITLE,
                        default=options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
                    ): str,
                    vol.Required(
                        CONF_PANEL_TEMPLATE,
                        default=options.get(
                            CONF_PANEL_TEMPLATE, DEFAULT_PANEL_TEMPLATE
                        ),
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT, multiline=True
                        )
                    ),
                }
            ),
        )
