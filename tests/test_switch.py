"""Tests for the screen power switch."""

import re

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

from .common import mock_status_reads
from .const import DEVICE_INFO, LAYOUTS

ENTITY = "switch.frame_screen"


def _calls(aioclient_mock, endpoint: str) -> list:
    return [c for c in aioclient_mock.mock_calls if f"/ajax/{endpoint}" in str(c[1])]


def _mock_commands(aioclient_mock, screen_power_status: int = 200) -> None:
    """Answer the commands the switch may send, and the refresh after them."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(
        re.compile(r"/ajax/screen/power"),
        status=screen_power_status,
        json={"success": screen_power_status == 200, "result": {}},
    )
    aioclient_mock.put(re.compile(r"/ajax/layout/set"), json={"success": True})
    aioclient_mock.put(re.compile(r"/ajax/layout/clear"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
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
