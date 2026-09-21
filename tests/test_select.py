"""Tests for the playlist select."""

import re

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DEVICE_INFO

ENTITY = "select.frame_playlist"


async def test_options_come_from_content_entries(
    hass: HomeAssistant, init_integration
) -> None:
    """There is no list-playlists endpoint; the names come from content."""
    state = hass.states.get(ENTITY)
    assert state.attributes["options"] == ["All files in cycle", "HA Template"]
    assert state.state == "All files in cycle"


async def test_selecting_uses_the_playlist_id(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A name is resolved to its playlist ID before switching."""
    aioclient_mock.clear_requests()
    aioclient_mock.put(re.compile(r"/ajax/playlist/set"), json={"success": True})
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), json=DEVICE_INFO)

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "HA Template"},
        blocking=True,
    )

    call = next(c for c in aioclient_mock.mock_calls if "playlist/set" in str(c[1]))
    assert call[1].query["playlistId"] == "34"


async def test_unknown_playlist_is_reported(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Selecting something the player does not have fails loudly."""
    with pytest.raises((HomeAssistantError, ValueError)):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "Does not exist"},
            blocking=True,
        )


async def test_unlisted_playlist_reads_as_unknown(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A playlist with no content entry must not be reported as selected."""
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        {**DEVICE_INFO, "currentPlaylist": "Something else"}
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "unknown"


async def test_source_list_matches_the_select(
    hass: HomeAssistant, init_integration
) -> None:
    """The media player offers the same playlists as a source list."""
    state = hass.states.get("media_player.frame")
    assert state.attributes["source_list"] == ["All files in cycle", "HA Template"]
