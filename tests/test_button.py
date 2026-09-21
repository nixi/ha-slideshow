"""Tests for the buttons."""

import re

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .const import DEVICE_INFO


@pytest.mark.parametrize(
    ("entity", "endpoint"),
    [
        ("button.frame_next", "ajax/next"),
        ("button.frame_previous", "ajax/previous"),
        ("button.frame_toggle_fullscreen", "ajax/fullscreen/toggle"),
        ("button.frame_clear_playlist", "ajax/playlist/clear"),
        ("button.frame_clear_screen_layout", "ajax/layout/clear"),
        ("button.frame_activate_screensaver", "ajax/screensaver/activate"),
        ("button.frame_reload_app", "ajax/reload"),
    ],
)
async def test_button_calls_its_endpoint(
    hass: HomeAssistant, aioclient_mock, init_integration, entity: str, endpoint: str
) -> None:
    """Each button maps to one endpoint."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(re.escape(endpoint)), json={"success": True})
    aioclient_mock.get(re.compile(r"ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity}, blocking=True
    )

    assert any(endpoint in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_reboot_is_disabled_by_default(
    hass: HomeAssistant, init_integration
) -> None:
    """Rebooting a wall-mounted player should take a deliberate opt-in."""
    assert hass.states.get("button.frame_reboot_device") is None
