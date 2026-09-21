"""Tests for the screenshot camera."""

import base64
import re

from homeassistant.components.camera import async_get_image
from homeassistant.core import HomeAssistant

from .const import BASE

JPEG = b"\xff\xd8\xff\xe0 a screenshot"
PAYLOAD = {"success": True, "result": {"data": base64.b64encode(JPEG).decode()}}


async def test_screenshot_is_served(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """The camera decodes the base64 screenshot into image bytes."""
    aioclient_mock.get(f"{BASE}/ajax/screenshot", json=PAYLOAD)
    image = await async_get_image(hass, "camera.frame_screenshot")
    assert image.content == JPEG


async def test_screenshots_are_cached_briefly(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Screenshots are costly on these players, so repeats are served from cache."""
    aioclient_mock.get(re.compile(r"/ajax/screenshot"), json=PAYLOAD)

    await async_get_image(hass, "camera.frame_screenshot")
    await async_get_image(hass, "camera.frame_screenshot")

    requests = [c for c in aioclient_mock.mock_calls if "screenshot" in str(c[1])]
    assert len(requests) == 1


async def test_failure_keeps_the_last_image(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A player that briefly drops out should not blank the card."""
    aioclient_mock.get(re.compile(r"/ajax/screenshot"), json=PAYLOAD)
    first = await async_get_image(hass, "camera.frame_screenshot")

    entity = hass.data["camera"].get_entity("camera.frame_screenshot")
    entity._cached_at = None  # force a refetch
    aioclient_mock.clear_requests()
    aioclient_mock.get(re.compile(r"/ajax/screenshot"), exc=TimeoutError())

    second = await async_get_image(hass, "camera.frame_screenshot")
    assert second.content == first.content
