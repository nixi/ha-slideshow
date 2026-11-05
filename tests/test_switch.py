"""Tests for the screen power switch."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

from .common import mock_status_reads
from .const import DEVICE_INFO, LAYOUTS

ENTITY = "switch.frame_screen"
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _calls(aioclient_mock, endpoint: str) -> list:
    return [c for c in aioclient_mock.mock_calls if f"/ajax/{endpoint}" in str(c[1])]


def _mock_commands(
    aioclient_mock, screen_power_status: int = 200, device_info: dict | None = None
) -> None:
    """Answer the commands the switch may send, and the refresh after them."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(
        re.compile(r"/ajax/screen/power"),
        status=screen_power_status,
        json={"success": screen_power_status == 200, "result": {}},
    )
    aioclient_mock.put(re.compile(r"/ajax/layout/set"), json={"success": True})
    aioclient_mock.put(re.compile(r"/ajax/layout/clear"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=device_info or DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)


async def _switch(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        "switch", service, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )


async def test_screen_reports_device_state(
    hass: HomeAssistant, init_integration
) -> None:
    """The switch reads screenPower rather than assuming."""
    assert hass.states.get(ENTITY).state == STATE_ON


async def test_turning_off_uses_the_power_endpoint(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Where the device can drive its screen, the layout is left alone."""
    _mock_commands(aioclient_mock)

    await _switch(hass, SERVICE_TURN_OFF)

    (call,) = _calls(aioclient_mock, "screen/power")
    assert call[1].query["value"] == "false"
    assert not _calls(aioclient_mock, "layout/set")


async def test_turning_on_uses_the_power_endpoint(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Turning on does not drop a layout the user chose."""
    _mock_commands(aioclient_mock)

    await _switch(hass, SERVICE_TURN_ON)

    (call,) = _calls(aioclient_mock, "screen/power")
    assert call[1].query["value"] == "true"
    assert not _calls(aioclient_mock, "layout/clear")


async def test_turning_on_clears_a_power_off_layout(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A power-off layout would keep the screen dark, so it goes first."""
    init_integration.runtime_data.async_set_updated_data(
        {**DEVICE_INFO, "screenPower": False, "currentScreenLayout": "Screen power off"}
    )
    _mock_commands(aioclient_mock)

    await _switch(hass, SERVICE_TURN_ON)

    assert _calls(aioclient_mock, "layout/clear")
    assert _calls(aioclient_mock, "screen/power")
    # The schedule shows a normal layout once cleared, so none is forced.
    assert not _calls(aioclient_mock, "layout/set")


async def test_falls_back_to_the_power_off_layout(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A device without screen control answers 500; the layout takes over."""
    _mock_commands(aioclient_mock, screen_power_status=500)

    await _switch(hass, SERVICE_TURN_OFF)

    (call,) = _calls(aioclient_mock, "layout/set")
    assert call[1].query["layoutName"] == "Screen power off"

    # Having failed once, it is not tried again.
    _mock_commands(aioclient_mock, screen_power_status=500)
    await _switch(hass, SERVICE_TURN_ON)

    assert not _calls(aioclient_mock, "screen/power")
    assert _calls(aioclient_mock, "layout/clear")


async def test_power_off_layout_is_found_by_its_flag(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """The layout's name follows the app's language; its flag does not."""
    coordinator = init_integration.runtime_data
    coordinator.layouts = {
        "Výchozí rozložení": {**LAYOUTS[0], "name": "Výchozí rozložení"},
        "Vypnutí obrazovky": {**LAYOUTS[1], "name": "Vypnutí obrazovky"},
    }
    _mock_commands(aioclient_mock, screen_power_status=500)

    await _switch(hass, SERVICE_TURN_OFF)

    (call,) = _calls(aioclient_mock, "layout/set")
    assert call[1].query["layoutName"] == "Vypnutí obrazovky"


SCHEDULED_OFF = {
    **DEVICE_INFO,
    "screenPower": True,
    "currentScreenLayout": "Screen power off",
}


async def test_power_off_layout_reads_as_off(
    hass: HomeAssistant, init_integration
) -> None:
    """A touch lights a scheduled power-off layout, but nothing is on show."""
    init_integration.runtime_data.async_set_updated_data(SCHEDULED_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY).state == STATE_OFF
    assert hass.states.get("media_player.frame").state == STATE_OFF
    # The screen power binary sensor still reports the backlight as it is.
    screen_power = next(
        s for s in hass.states.async_all("binary_sensor") if "screen" in s.entity_id
    )
    assert screen_power.state == STATE_ON


# The Frame's own schedule: Default layout 17-21, powered off the rest of the
# day, as /ajax/schedule/layout resolves it.
FRAME_SCHEDULE = [
    {"entityId": 1, "from": "2026-11-05T17:00", "to": "2026-11-05T21:00", "id": 1},
    {"entityId": 2, "from": "2026-11-05T21:01", "to": "2026-11-05T23:59", "id": 34},
    {"entityId": 2, "from": "2026-11-05T00:00", "to": "2026-11-05T16:59", "id": 33},
    {"entityId": 1, "from": "2026-11-06T17:00", "to": "2026-11-06T21:00", "id": 1},
    {"entityId": 2, "from": "2026-11-06T21:01", "to": "2026-11-06T23:59", "id": 34},
    {"entityId": 2, "from": "2026-11-06T00:00", "to": "2026-11-06T16:59", "id": 33},
]


def _mock_schedule(aioclient_mock, schedules=FRAME_SCHEDULE, **kwargs) -> None:
    aioclient_mock.get(
        re.compile(r"/ajax/schedule/layout"),
        **(kwargs or {"json": {"success": True, "result": {"schedules": schedules}}}),
    )


def _requests(aioclient_mock) -> list[str]:
    return [
        f"{c[0]} {c[1].path.removeprefix('/ajax/')}" for c in aioclient_mock.mock_calls
    ]


@pytest.mark.parametrize(
    ("local_time", "expected_length"),
    [
        # Lunchtime: shown until the schedule's own 17:00 switch.
        ("2026-11-05 12:30:00", 4 * 3600 + 30 * 60),
        # Late evening: the power-off split at midnight counts as one stretch.
        ("2026-11-05 22:00:00", 19 * 3600),
    ],
)
async def test_turning_on_overrides_a_scheduled_power_off(
    hass: HomeAssistant,
    aioclient_mock,
    init_integration,
    freezer: FrozenDateTimeFactory,
    local_time: str,
    expected_length: int,
) -> None:
    """Clearing returns to the schedule; if that says off, a layout is shown.

    The layout expires on the player when the schedule would show one anyway,
    so nothing needs remembering to hand the screen back.
    """
    freezer.move_to(datetime.fromisoformat(local_time).replace(tzinfo=STOCKHOLM))
    init_integration.runtime_data.async_set_updated_data(SCHEDULED_OFF)
    _mock_commands(aioclient_mock, device_info=SCHEDULED_OFF)
    _mock_schedule(aioclient_mock)

    await _switch(hass, SERVICE_TURN_ON)

    assert _requests(aioclient_mock)[:5] == [
        "PUT layout/clear",
        "GET deviceInfo",
        "GET schedule/layout",
        "PUT layout/set",
        "PUT screen/power",
    ]
    (call,) = _calls(aioclient_mock, "layout/set")
    assert call[1].query["layoutId"] == "1"
    assert call[1].query["length"] == str(expected_length)

    # Turning off again leaves layouts alone; the override runs out by itself.
    init_integration.runtime_data.async_set_updated_data(DEVICE_INFO)
    _mock_commands(aioclient_mock)
    await _switch(hass, SERVICE_TURN_OFF)
    assert not _calls(aioclient_mock, "layout/clear")
    assert not _calls(aioclient_mock, "layout/set")


async def test_unreadable_schedule_shows_the_layout_for_an_hour(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """The override always runs out, even when the schedule cannot be read."""
    init_integration.runtime_data.async_set_updated_data(SCHEDULED_OFF)
    _mock_commands(aioclient_mock, device_info=SCHEDULED_OFF)
    _mock_schedule(aioclient_mock, exc=TimeoutError())

    await _switch(hass, SERVICE_TURN_ON)

    (call,) = _calls(aioclient_mock, "layout/set")
    assert call[1].query["length"] == "3600"


async def test_failed_layout_read_still_turns_the_screen_on(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A read that fails after the clear skips the override, not the power."""
    init_integration.runtime_data.async_set_updated_data(SCHEDULED_OFF)
    _mock_commands(aioclient_mock, device_info=SCHEDULED_OFF)
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/screen/power"), json={"success": True})
    aioclient_mock.put(re.compile(r"/ajax/layout/clear"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), exc=TimeoutError())

    await _switch(hass, SERVICE_TURN_ON)

    assert not _calls(aioclient_mock, "layout/set")
    (call,) = _calls(aioclient_mock, "screen/power")
    assert call[1].query["value"] == "true"


async def test_no_layout_is_forced_without_a_layout_list(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Before SlideShow 4.13.0 there is no layout list to pick one from."""
    coordinator = init_integration.runtime_data
    coordinator.layouts = {}
    coordinator.async_set_updated_data(SCHEDULED_OFF)
    _mock_commands(aioclient_mock, device_info=SCHEDULED_OFF)

    await _switch(hass, SERVICE_TURN_ON)

    assert _calls(aioclient_mock, "layout/clear")
    assert not _calls(aioclient_mock, "layout/set")
