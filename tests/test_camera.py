"""Tests for the screenshot camera."""

import asyncio
import base64
import re
from unittest.mock import patch

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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


async def test_slow_screenshot_is_kept_for_the_next_request(
    hass: HomeAssistant, init_integration
) -> None:
    """A screenshot slower than Home Assistant's wait still gets used.

    Home Assistant gives up on a camera image after ten seconds, but the
    player may take longer. The screenshot carries on in the background, no
    second one is started meanwhile, and the next request gets it.
    """
    entity = hass.data["camera"].get_entity("camera.frame_screenshot")
    taken = asyncio.Event()
    calls = 0

    async def slow_screenshot() -> bytes:
        nonlocal calls
        calls += 1
        await taken.wait()
        return JPEG

    with (
        patch.object(entity.client, "async_get_screenshot", slow_screenshot),
        patch("custom_components.slideshow.camera.SCREENSHOT_WAIT", 0.01),
    ):
        # Nothing to show yet, but the caller is answered in time.
        with pytest.raises(HomeAssistantError):
            await async_get_image(hass, "camera.frame_screenshot")

        # A caller cancelled mid-wait does not take the screenshot with it.
        waiting = hass.async_create_task(entity.async_camera_image())
        await asyncio.sleep(0)
        waiting.cancel()
        await asyncio.sleep(0)
        assert calls == 1

        taken.set()
        await asyncio.sleep(0)
        image = await async_get_image(hass, "camera.frame_screenshot")

    assert image.content == JPEG
    assert calls == 1
