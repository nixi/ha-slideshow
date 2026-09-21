"""Tests for the media player."""

import re

import pytest
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    SERVICE_PLAY_MEDIA,
    MediaType,
)
from homeassistant.components.media_player import (
    DOMAIN as MP_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.slideshow.const import DOMAIN

from .const import BASE, DEVICE_INFO, USER_INPUT

ENTITY = "media_player.frame"


async def _setup(hass: HomeAssistant, aioclient_mock, **overrides) -> None:
    """Set the integration up with a tweaked device status."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json={**DEVICE_INFO, **overrides})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frame",
        unique_id=DEVICE_INFO["deviceId"],
        data={**USER_INPUT, "panel_secret": "test-secret"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, STATE_PLAYING),
        ({"paused": True}, STATE_PAUSED),
        # A powered-down screen wins: the app keeps running behind it, but
        # nothing is on the display.
        ({"screenPower": False}, STATE_OFF),
        ({"screenPower": False, "paused": True}, STATE_OFF),
    ],
)
async def test_state_mapping(
    hass: HomeAssistant, aioclient_mock, overrides: dict, expected: str
) -> None:
    """Playback state combines the paused flag and screen power."""
    await _setup(hass, aioclient_mock, **overrides)
    assert hass.states.get(ENTITY).state == expected


async def test_reported_attributes(hass: HomeAssistant, aioclient_mock) -> None:
    """Volume, title and playlist come from the polled status."""
    await _setup(hass, aioclient_mock)
    state = hass.states.get(ENTITY)
    assert state.attributes["volume_level"] == 0.2
    assert state.attributes["media_title"] == "room.url"
    assert state.attributes["source"] == "All files in cycle"
    assert state.attributes["is_volume_muted"] is False


async def test_audio_plays_in_the_audio_zone(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Music goes to the audio zone so it does not take over the screen.

    The device accepts only the literal zone ID for this; it rejects the
    zone's name.
    """
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showStream"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY,
            ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
            ATTR_MEDIA_CONTENT_ID: "http://ha.local:8123/media/song.mp3",
        },
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "showStream" in str(c[1]))
    assert call[1].query["zoneId"] == "audio"
    assert call[1].query["address"] == "http://ha.local:8123/media/song.mp3"


async def test_video_takes_the_main_zone(hass: HomeAssistant, aioclient_mock) -> None:
    """Video has no zone override, so it lands in the main zone."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.post(re.compile(r"/ajax/showStream"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        MP_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: ENTITY,
            ATTR_MEDIA_CONTENT_TYPE: MediaType.VIDEO,
            ATTR_MEDIA_CONTENT_ID: "rtsp://camera/stream",
        },
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "showStream" in str(c[1]))
    assert "zoneId" not in call[1].query
