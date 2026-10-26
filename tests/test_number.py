"""Tests for the screen brightness number."""

import re

import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .common import mock_status_reads
from .const import DEVICE_INFO

ENTITY = "number.frame_screen_brightness"


async def test_brightness_reads_the_device(
    hass: HomeAssistant, init_integration
) -> None:
    """The value is the brightness the player reports."""
    assert float(hass.states.get(ENTITY).state) == DEVICE_INFO["screenBrightness"]


async def test_setting_brightness(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A new value goes to the brightness endpoint as a whole percentage."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(
        re.compile(r"/ajax/screen/brightness"),
        json={"success": True, "result": {"value": "40"}},
    )
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_VALUE: 40},
        blocking=True,
    )

    call = next(
        c for c in aioclient_mock.mock_calls if "screen/brightness" in str(c[1])
    )
    assert call[1].query["value"] == "40"


async def test_unsupported_device_explains_itself(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A device without screen control answers 500, which is surfaced."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(
        re.compile(r"/ajax/screen/brightness"),
        status=500,
        json={"success": False, "errorCode": "INTERNAL_SERVER_ERROR"},
    )

    with pytest.raises(HomeAssistantError, match="cannot set its brightness"):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: ENTITY, ATTR_VALUE: 40},
            blocking=True,
        )
