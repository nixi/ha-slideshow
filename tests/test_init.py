"""Tests for setting the integration up and tearing it down."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.slideshow.const import CONF_PANEL_SECRET, DOMAIN

from .const import BASE, DEVICE_INFO, USER_INPUT


async def test_setup_and_unload(hass: HomeAssistant, init_integration) -> None:
    """The entry loads and unloads cleanly."""
    assert init_integration.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_panel_secret_is_generated_once(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """An entry made before the panel existed gets a secret on first load."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    assert CONF_PANEL_SECRET not in entry.data

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    secret = entry.data[CONF_PANEL_SECRET]
    assert len(secret) > 20

    # Reloading must not rotate it, or every reload would break the player.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_PANEL_SECRET] == secret


async def test_rejected_credentials_start_reauth(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A 303 to the login page must trigger reauth, not a silent success."""
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_unreachable_player_retries(hass: HomeAssistant, aioclient_mock) -> None:
    """A player that is merely offline should be retried, not failed."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", exc=TimeoutError())
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
