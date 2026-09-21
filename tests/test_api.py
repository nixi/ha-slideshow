"""Tests for the SlideShow API client.

Several of these pin down behaviour that differs from the published OpenAPI
specification and was only found by driving a real player.
"""

import re

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.slideshow.api import (
    SlideshowApiError,
    SlideshowAuthError,
    SlideshowClient,
    SlideshowConnectionError,
)

from .const import BASE, DEVICE_INFO, HOST, PORT


def _client(hass: HomeAssistant) -> SlideshowClient:
    return SlideshowClient(
        async_get_clientsession(hass), HOST, PORT, "admin", "admin"
    )


async def test_device_info_is_a_bare_object(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """DeviceInfo has no success/result wrapper and must pass straight through."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    assert await _client(hass).async_get_device_info() == DEVICE_INFO


async def test_wrapped_payload_is_unwrapped(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Endpoints that wrap their payload return only the inner result."""
    aioclient_mock.get(
        f"{BASE}/ajax/volume/get",
        json={"success": True, "result": {"currentVolume": 20}},
    )
    assert await _client(hass).async_get_volume() == 20


async def test_redirect_to_login_is_an_auth_error(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Bad credentials answer 303 to /login, not 401.

    A client that followed redirects would land on the login page with a 200
    and conclude that everything was fine.
    """
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo",
        status=303,
        headers={"Location": "/login?redirect=%2Fajax%2FdeviceInfo"},
    )
    with pytest.raises(SlideshowAuthError):
        await _client(hass).async_get_device_info()


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_status_is_an_auth_error(
    hass: HomeAssistant, aioclient_mock, status: int
) -> None:
    """A conventional auth rejection is handled too."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", status=status)
    with pytest.raises(SlideshowAuthError):
        await _client(hass).async_get_device_info()


async def test_error_message_is_surfaced(hass: HomeAssistant, aioclient_mock) -> None:
    """The device explains failures in errorMessage, not error."""
    aioclient_mock.get(
        f"{BASE}/ajax/zones",
        json={
            "success": False,
            "errorCode": "BAD_REQUEST",
            "errorMessage": "Missing address",
        },
    )
    with pytest.raises(SlideshowApiError, match="Missing address"):
        await _client(hass).async_get_zones()


async def test_show_stream_uses_address_and_duration(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """ShowStream is the one endpoint taking address/duration.

    Sending url/length, as every other endpoint uses, is rejected outright.
    """
    aioclient_mock.post(re.compile(r"/ajax/showStream"), json={"success": True})
    await _client(hass).async_show_stream("http://ha.local/x.mp3", 30, zone_id="audio")

    query = aioclient_mock.mock_calls[0][1].query
    assert query["address"] == "http://ha.local/x.mp3"
    assert query["duration"] == "30"
    assert query["zoneId"] == "audio"
    assert "url" not in query
    assert "length" not in query


async def test_unset_parameters_are_dropped(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Optional parameters left as None must not be sent at all."""
    aioclient_mock.put(re.compile(r"/ajax/next"), json={"success": True})
    await _client(hass).async_next()
    assert dict(aioclient_mock.mock_calls[0][1].query) == {}


async def test_booleans_are_lowercased(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Python's True would be sent as 'True' without conversion."""
    aioclient_mock.post(re.compile(r"/ajax/synchronize"), json={"success": True})
    await _client(hass).async_synchronize(
        "https://example.com/a.zip", "target", clear_folder=True
    )
    assert aioclient_mock.mock_calls[0][1].query["clearFolder"] == "true"


async def test_screenshot_is_decoded(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The screenshot arrives base64 encoded inside JSON."""
    aioclient_mock.get(
        f"{BASE}/ajax/screenshot",
        json={"success": True, "result": {"data": "/9j/4AAQ"}},
    )
    assert (await _client(hass).async_get_screenshot()).startswith(b"\xff\xd8")


async def test_unreachable_host_is_a_connection_error(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Transport failures surface as a connection error."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", exc=TimeoutError())
    with pytest.raises(SlideshowConnectionError):
        await _client(hass).async_get_device_info()
