"""Tests for the integration's own actions."""

import re
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from custom_components.slideshow.const import DOMAIN

from .const import DEVICE_INFO

ENTITY = "media_player.frame"


async def test_show_html(hass: HomeAssistant, aioclient_mock, init_integration) -> None:
    """HTML is sent verbatim; the integration must not restyle it."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showSentHtml"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    markup = '<div style="color:#fff">Dinner is ready</div>'
    await hass.services.async_call(
        DOMAIN, "show_html", {ATTR_ENTITY_ID: ENTITY, "html": markup, "length": 20},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "showSentHtml" in str(c[1]))
    assert call[1].query["html"] == markup
    assert call[1].query["length"] == "20"


async def test_set_playlist_requires_an_identifier(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """One of playlist id, name or number must be given."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_playlist", {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )


async def test_set_playlist_by_name(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A named playlist is passed through as playlistName."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/playlist/set"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        DOMAIN,
        "set_playlist",
        {ATTR_ENTITY_ID: ENTITY, "playlist_name": "Holiday photos"},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "playlist/set" in str(c[1]))
    assert call[1].query["playlistName"] == "Holiday photos"


async def test_show_camera_prefers_rtsp(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """An RTSP source is handed straight to the player, not proxied."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showStream"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    with patch(
        "custom_components.slideshow.media_player.async_get_stream_source",
        return_value="rtsp://camera.local/stream",
    ):
        await hass.services.async_call(
            DOMAIN,
            "show_camera",
            {ATTR_ENTITY_ID: ENTITY, "camera_entity_id": "camera.front_door",
             "duration": 45},
            blocking=True,
        )

    call = next(c for c in aioclient_mock.mock_calls if "showStream" in str(c[1]))
    assert call[1].query["address"] == "rtsp://camera.local/stream"
    assert call[1].query["duration"] == "45"


async def test_install_panel_pulls_the_url_file_and_creates_content(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """The panel is installed as a playlist of its own.

    The API has no upload endpoint, so the player is told to synchronize a
    one-line .url file that Home Assistant serves.
    """
    hass.config.internal_url = "http://10.0.0.5:8123"

    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/synchronize"), json={"success": True})
    aioclient_mock.post(
        re.compile(r"/ajax/content/create"),
        json={"success": True, "result": {"id": 34, "playlistId": 35}},
    )
    aioclient_mock.get(re.compile(r"/ajax/content/get"), json={
        "success": True, "result": {"content": [
            {"id": 34, "playlistId": 35, "name": "Home Assistant panel",
             "path": "ha_panel.url", "type": "ALPHABETICALLY"},
        ]},
    })
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        DOMAIN, "install_panel", {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )

    sync = next(c for c in aioclient_mock.mock_calls if "synchronize" in str(c[1]))
    assert sync[1].query["url"].startswith("http://10.0.0.5:8123/api/slideshow/panel/")
    assert sync[1].query["url"].endswith("/url")
    assert sync[1].query["target"] == "ha_panel.url"

    create = next(c for c in aioclient_mock.mock_calls if "content/create" in str(c[1]))
    assert create[1].query["name"] == "Home Assistant panel"
    assert create[1].query["path"] == "ha_panel.url"

    # The new playlist is picked up without waiting for the slow refresh.
    assert "Home Assistant panel" in init_integration.runtime_data.playlists
