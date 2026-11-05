"""Tests for the polling coordinator."""

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .common import mock_status_reads
from .const import BASE, DEVICE_INFO, SECONDS_SINCE_USER_ACTIVITY, ZONES


async def test_another_player_at_the_address_is_not_adopted(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A player answering with another device ID fails the poll.

    Two players can trade addresses after a router restart. Carrying on would
    rename this device after the other player and control the wrong screen.
    """
    coordinator = init_integration.runtime_data
    registry = dr.async_get(hass)
    (device,) = dr.async_entries_for_config_entry(registry, init_integration.entry_id)

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo",
        json={**DEVICE_INFO, "deviceId": "someone-else", "deviceName": "Kitchen"},
    )
    mock_status_reads(aioclient_mock)
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert "different SlideShow player" in str(coordinator.last_exception)
    assert registry.async_get(device.id).name == "Frame"
    assert hass.states.get("switch.frame_screen").state == "unavailable"


async def test_last_activity_is_counted_from_the_answer(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock,
    init_integration,
) -> None:
    """Slow reads earlier in the poll do not move the last activity.

    The player counts the seconds when it answers, so counting them back from
    the start of the poll would place the same touch earlier each time.
    """
    coordinator = init_integration.runtime_data
    touched = coordinator.last_user_activity
    assert touched is not None

    freezer.tick(timedelta(minutes=1))
    elapsed = SECONDS_SINCE_USER_ACTIVITY + 60 + 20

    async def slow_zone_read() -> list:
        freezer.tick(timedelta(seconds=20))
        return ZONES

    with (
        patch.object(coordinator.client, "async_get_zone_content", slow_zone_read),
        patch.object(
            coordinator.client,
            "async_get_seconds_since_user_activity",
            return_value=elapsed,
        ),
    ):
        await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.last_user_activity == touched


async def test_missing_activity_value_does_not_fail_the_poll(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """An activity answer without the value skips that read only."""
    coordinator = init_integration.runtime_data
    touched = coordinator.last_user_activity

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    aioclient_mock.get(
        f"{BASE}/ajax/zone/content", json={"success": True, "result": {"zones": []}}
    )
    aioclient_mock.get(
        f"{BASE}/ajax/lastUserActivity",
        json={"success": True, "result": {"secondsSinceLastActivity": None}},
    )
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.last_user_activity == touched
