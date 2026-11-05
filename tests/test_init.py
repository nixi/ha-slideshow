"""Tests for setting the integration up and tearing it down."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import slideshow
from custom_components.slideshow.const import (
    AUTH_GRACE_PERIOD,
    CONF_PANEL_SECRET,
    DEFAULT_PANEL_TEMPLATE,
    DOMAIN,
)

from .common import mock_status_reads
from .const import BASE, CONTENT, DEVICE_INFO, USER_INPUT


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
    mock_status_reads(aioclient_mock)
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


async def test_dropping_a_stored_default_does_not_reload(
    hass: HomeAssistant, mock_device, mock_config_entry
) -> None:
    """Setup tidies a stored default template away without a second setup."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={"panel_template": DEFAULT_PANEL_TEMPLATE}
    )
    with patch(
        "custom_components.slideshow.async_setup_entry",
        wraps=slideshow.async_setup_entry,
    ) as setup:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert "panel_template" not in mock_config_entry.options
    assert setup.call_count == 1
    assert mock_config_entry.state is ConfigEntryState.LOADED


def _reauth_flows(hass: HomeAssistant) -> list:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
    ]


async def test_rejection_during_setup_starts_reauth(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A rejection while setting up asks for new credentials straight away.

    Every setup retry builds a new coordinator, so a grace period counted on
    it would start again on each retry and the user would never be asked.
    The reauth flow checks the stored credentials once more before asking.
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

    assert entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = _reauth_flows(hass)
    assert flow["step_id"] == "reauth_confirm"


async def test_rejection_becomes_reauth_only_after_the_grace_period(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Once running, a rejection is retried for a while, then asks the user.

    A player rejects valid credentials for a moment while it restarts or is
    reconfigured. Asking for a password that never changed is worse than
    waiting a couple of polls.
    """
    coordinator = init_integration.runtime_data
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )

    # Inside the grace period: retried, and the user is left alone.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert not _reauth_flows(hass)

    # Past it, still rejected: now worth asking.
    coordinator._auth_rejected_since -= AUTH_GRACE_PERIOD
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _reauth_flows(hass)


async def test_recovery_clears_the_rejection(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A player that starts accepting again resets the clock."""
    coordinator = init_integration.runtime_data
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo", status=303, headers={"Location": "/login"}
    )
    await coordinator.async_refresh()
    assert coordinator._auth_rejected_since is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    mock_status_reads(aioclient_mock)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
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


async def test_device_follows_an_app_update(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A new app version reaches the device page without a reload."""
    registry = dr.async_get(hass)

    def device() -> dr.DeviceEntry:
        (entry,) = dr.async_entries_for_config_entry(
            registry, init_integration.entry_id
        )
        return entry

    assert device().sw_version == "4.12.7"

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo",
        json={**DEVICE_INFO, "softwareVersion": "4.13.0", "deviceName": "Hallway"},
    )
    mock_status_reads(aioclient_mock)
    await init_integration.runtime_data.async_refresh()

    # The update has to arrive through a poll that succeeds, not one that
    # fails after the device page was already touched.
    assert init_integration.runtime_data.last_update_success
    assert device().sw_version == "4.13.0"
    assert device().name == "Hallway"


async def test_older_player_without_new_endpoints(
    hass: HomeAssistant, aioclient_mock, mock_config_entry
) -> None:
    """A player before 4.13.0 loads fine, without what it cannot offer."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    for path in ("layout/get", "zone/content", "lastUserActivity"):
        aioclient_mock.get(
            f"{BASE}/ajax/{path}",
            status=404,
            json={"errorCode": "NOT_FOUND", "success": False},
        )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("select.frame_screen_layout") is None
    assert hass.states.get("sensor.frame_last_user_activity") is None
    assert hass.states.get("select.frame_playlist") is not None

    # Missing endpoints are remembered, not asked for on every poll.
    asked = aioclient_mock.call_count
    await mock_config_entry.runtime_data.async_refresh()
    assert aioclient_mock.call_count == asked + 1
