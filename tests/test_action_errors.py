"""Tests for how a failing player is reported back to the user."""

import re

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.slideshow.const import DOMAIN

from .const import HOST


async def test_offline_player_is_a_home_assistant_error(
    hass: HomeAssistant, hass_ws_client, aioclient_mock, init_integration
) -> None:
    """A press that times out is an ordinary action failure, not a crash.

    Anything else is logged with a traceback and shown as an unknown error,
    and a script's continue_on_error does not cover it.
    """
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/next"), exc=TimeoutError())
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "call_service",
            "domain": BUTTON_DOMAIN,
            "service": SERVICE_PRESS,
            "target": {ATTR_ENTITY_ID: "button.frame_next"},
        }
    )
    response = await client.receive_json()

    assert not response["success"]
    error = response["error"]
    assert error["code"] == "home_assistant_error"
    assert error["translation_domain"] == DOMAIN
    assert error["translation_key"] == "cannot_connect"
    # The translated message the UI shows does not name the player's address.
    assert HOST not in str(error.get("translation_placeholders"))


@pytest.mark.parametrize(
    ("domain", "service", "data", "endpoint"),
    [
        (SWITCH_DOMAIN, SERVICE_TURN_OFF, {}, r"/ajax/(screen/power|layout/set)"),
        (NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_VALUE: 40}, r"/ajax/screen/"),
        (
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_OPTION: "HA Template"},
            r"/ajax/playlist/set",
        ),
    ],
)
async def test_entity_actions_raise_home_assistant_errors(
    hass: HomeAssistant,
    aioclient_mock,
    init_integration,
    domain: str,
    service: str,
    data: dict,
    endpoint: str,
) -> None:
    """Switch, number and select report an unreachable player properly too."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(endpoint), exc=TimeoutError())
    entity = {
        SWITCH_DOMAIN: "switch.frame_screen",
        NUMBER_DOMAIN: "number.frame_screen_brightness",
        SELECT_DOMAIN: "select.frame_playlist",
    }[domain]

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: entity, **data}, blocking=True
        )

    assert err.value.translation_key == "cannot_connect"


async def test_device_rejection_carries_its_reason(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A command the player refuses explains why, in the translated message."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(
        re.compile(r"/ajax/next"),
        json={"success": False, "errorMessage": "Zone not found"},
    )

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.frame_next"},
            blocking=True,
        )

    assert err.value.translation_key == "api_error"
    assert "Zone not found" in err.value.translation_placeholders["reason"]
