"""Tests for the screen power switch."""

import re

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

ENTITY = "switch.frame_screen"


async def test_screen_reports_device_state(
    hass: HomeAssistant, init_integration
) -> None:
    """The switch reads screenPower rather than assuming."""
    assert hass.states.get(ENTITY).state == STATE_ON


async def test_turning_off_selects_the_power_off_layout(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """There is no screen power endpoint, so the layout is the lever."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/layout/set"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json={"deviceId": "x"})

    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )

    call = next(c for c in aioclient_mock.mock_calls if "layout/set" in str(c[1]))
    assert call[1].query["layoutName"] == "Screen power off"


async def test_turning_on_clears_the_layout(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Turning the screen back on drops the override."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/layout/clear"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json={"deviceId": "x"})

    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )

    assert any("layout/clear" in str(c[1]) for c in aioclient_mock.mock_calls)
