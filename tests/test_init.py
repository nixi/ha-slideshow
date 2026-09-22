"""Tests for setting the integration up and tearing it down."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.slideshow.const import CONF_PANEL_SECRET, DOMAIN

from .const import BASE, CONTENT, DEVICE_INFO, HOST, PORT, USER_INPUT


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
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
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


async def test_a_single_rejection_does_not_start_reauth(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """One rejection is retried rather than prompting the user.

    A player rejects valid credentials for a moment while it restarts or is
    reconfigured. Asking for a password that never changed is worse than
    waiting a couple of polls.
    """
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    ]


async def test_rejection_becomes_reauth_only_after_the_grace_period(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A rejection is retried for a while, then asks the user.

    Exercised on the coordinator directly: a failing setup never assigns
    runtime_data, so there would be no coordinator to reach afterwards.
    """
    from homeassistant.exceptions import ConfigEntryAuthFailed
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.slideshow.api import SlideshowClient
    from custom_components.slideshow.const import AUTH_GRACE_PERIOD
    from custom_components.slideshow.coordinator import SlideshowCoordinator

    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    client = SlideshowClient(
        async_get_clientsession(hass), HOST, PORT, "admin", "admin"
    )
    coordinator = SlideshowCoordinator(hass, entry, client)

    # Inside the grace period: retried, and the user is left alone.
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # Past it, still rejected: now worth asking.
    coordinator._auth_rejected_since -= AUTH_GRACE_PERIOD
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_recovery_clears_the_rejection(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A player that starts accepting again resets the clock."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.slideshow.api import SlideshowClient
    from custom_components.slideshow.coordinator import SlideshowCoordinator

    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_INFO["deviceId"], data=dict(USER_INPUT)
    )
    entry.add_to_hass(hass)
    coordinator = SlideshowCoordinator(
        hass, entry,
        SlideshowClient(async_get_clientsession(hass), HOST, PORT, "admin", "admin"),
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert coordinator._auth_rejected_since is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    await coordinator._async_update_data()
    assert coordinator._auth_rejected_since is None


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
