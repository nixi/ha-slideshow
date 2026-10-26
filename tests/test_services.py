"""Tests for the integration's own actions."""

import re
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers.network import NoURLAvailableError

from custom_components.slideshow.const import DOMAIN

from .common import mock_status_reads
from .const import DEVICE_INFO

ENTITY = "media_player.frame"


async def test_show_html(hass: HomeAssistant, aioclient_mock, init_integration) -> None:
    """HTML is sent verbatim; the integration must not restyle it."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showSentHtml"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)

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
    mock_status_reads(aioclient_mock, None)

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
    mock_status_reads(aioclient_mock, None)

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
    mock_status_reads(aioclient_mock, None)

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


async def test_create_content_returns_the_new_ids(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Creating content answers with its content and playlist IDs."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        re.compile(r"/ajax/content/create"),
        json={"success": True, "result": {"id": 34, "playlistId": 35}},
    )
    aioclient_mock.get(
        re.compile(r"/ajax/content/get"),
        json={"success": True, "result": {"content": [
            {"id": 34, "playlistId": 35, "name": "Holiday photos",
             "path": "photos/holiday", "type": "ALPHABETICALLY"},
        ]}},
    )
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)

    response = await hass.services.async_call(
        DOMAIN,
        "create_content",
        {ATTR_ENTITY_ID: ENTITY, "content_name": "Holiday photos",
         "path": "photos/holiday"},
        blocking=True,
        return_response=True,
    )

    assert response[ENTITY] == {"content_id": 34, "playlist_id": 35}
    call = next(c for c in aioclient_mock.mock_calls if "content/create" in str(c[1]))
    assert call[1].query["type"] == "ALPHABETICALLY"
    # The new playlist becomes selectable without waiting for the slow refresh.
    assert "Holiday photos" in init_integration.runtime_data.playlists


async def test_delete_content(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Deleting passes the content ID through."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/content/delete"), json={"success": True})
    aioclient_mock.get(
        re.compile(r"/ajax/content/get"),
        json={"success": True, "result": {"content": []}},
    )
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)

    await hass.services.async_call(
        DOMAIN, "delete_content", {ATTR_ENTITY_ID: ENTITY, "content_id": 34},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "content/delete" in str(c[1]))
    assert call[1].query["id"] == "34"


async def test_unknown_content_type_is_rejected(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Only the types the device accepts are allowed through."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "create_content",
            {ATTR_ENTITY_ID: ENTITY, "content_name": "x", "path": "y",
             "content_type": "WEBPAGE"},
            blocking=True,
        )


async def test_get_panel_url_answers_an_administrator(
    hass: HomeAssistant, init_integration, hass_admin_user
) -> None:
    """An administrator can read the panel address to add it by hand."""
    hass.config.internal_url = "http://10.0.0.5:8123"

    response = await hass.services.async_call(
        DOMAIN,
        "get_panel_url",
        {"config_entry_id": init_integration.entry_id},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )

    assert response == {"url": "http://10.0.0.5:8123/api/slideshow/panel/test-secret"}


async def test_get_panel_url_refuses_other_users(
    hass: HomeAssistant, init_integration, hass_read_only_user
) -> None:
    """The address carries the panel secret, so only administrators get it."""
    hass.config.internal_url = "http://10.0.0.5:8123"

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "get_panel_url",
            {"config_entry_id": init_integration.entry_id},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_get_panel_url_rejects_an_unknown_entry(
    hass: HomeAssistant, init_integration
) -> None:
    """An ID that is not a SlideShow entry is refused, and named."""
    with pytest.raises(ServiceValidationError, match="not-an-entry"):
        await hass.services.async_call(
            DOMAIN,
            "get_panel_url",
            {"config_entry_id": "not-an-entry"},
            blocking=True,
            return_response=True,
        )


async def test_get_panel_url_rejects_an_unloaded_player(
    hass: HomeAssistant, init_integration
) -> None:
    """A player whose entry is not loaded has no panel to point at."""
    await hass.config_entries.async_unload(init_integration.entry_id)

    with pytest.raises(ServiceValidationError, match="Frame is not loaded"):
        await hass.services.async_call(
            DOMAIN,
            "get_panel_url",
            {"config_entry_id": init_integration.entry_id},
            blocking=True,
            return_response=True,
        )


async def test_get_panel_url_needs_a_known_address(
    hass: HomeAssistant, init_integration
) -> None:
    """Without any Home Assistant URL the action explains what to set."""
    with (
        patch(
            "custom_components.slideshow.panel.get_url",
            side_effect=NoURLAvailableError,
        ),
        pytest.raises(HomeAssistantError, match="internal URL"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "get_panel_url",
            {"config_entry_id": init_integration.entry_id},
            blocking=True,
            return_response=True,
        )


def _mock_refresh(aioclient_mock) -> None:
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)
    mock_status_reads(aioclient_mock, None)


async def test_show_file_can_wait(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A file can follow the one on screen instead of interrupting it."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showFile"), json={"success": True})
    _mock_refresh(aioclient_mock)

    await hass.services.async_call(
        DOMAIN,
        "show_file",
        {ATTR_ENTITY_ID: ENTITY, "file": "film.mp4", "length": 60, "wait": True,
         "audio_track_id": "2"},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "showFile" in str(c[1]))
    assert call[1].query["wait"] == "true"
    assert call[1].query["audioTrackId"] == "2"
    assert "subtitleTrackId" not in call[1].query


async def test_permanent_layout_is_scheduled(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A permanent layout is stored as a schedule, not set as an override."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/schedule/layout/set"), json={"success": True})
    _mock_refresh(aioclient_mock)

    await hass.services.async_call(
        DOMAIN,
        "set_layout",
        {ATTR_ENTITY_ID: ENTITY, "layout_name": "Test", "permanent": True},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "schedule/layout" in str(c[1]))
    assert call[1].query["layoutName"] == "Test"
    assert not any("/ajax/layout/set" in str(c[1]) for c in aioclient_mock.mock_calls)


async def test_permanent_layout_has_no_length(
    hass: HomeAssistant, init_integration
) -> None:
    """A layout meant to stay cannot also be timed."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_layout",
            {ATTR_ENTITY_ID: ENTITY, "layout_id": 33, "permanent": True,
             "length": 60},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("service", "data", "endpoint", "query"),
    [
        ("send_key", {"key_code": "KEYCODE_ENTER"}, "control/key",
         {"keyCode": "KEYCODE_ENTER"}),
        ("tap", {"x": 640, "y": 400}, "control/click", {"x": "640", "y": "400"}),
        ("start_app", {"package_name": "com.android.chrome"}, "system/startApp",
         {"packageName": "com.android.chrome"}),
    ],
)
async def test_remote_control(
    hass: HomeAssistant,
    aioclient_mock,
    init_integration,
    service: str,
    data: dict,
    endpoint: str,
    query: dict,
) -> None:
    """Key presses, taps and app starts pass straight through."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(rf"/ajax/{endpoint}"), json={"success": True})

    await hass.services.async_call(
        DOMAIN, service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
    )

    call = next(c for c in aioclient_mock.mock_calls if endpoint in str(c[1]))
    assert dict(call[1].query) == query
