"""Media player for the main zone of a SlideShow player."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_CLEAR_FOLDER,
    ATTR_FILE,
    ATTR_HTML,
    ATTR_LAYOUT_ID,
    ATTR_LAYOUT_NAME,
    ATTR_LENGTH,
    ATTR_METHOD,
    ATTR_PLAYLIST_ID,
    ATTR_PLAYLIST_NAME,
    ATTR_PLAYLIST_NUMBER,
    ATTR_TARGET,
    ATTR_URL,
    ATTR_ZONE_ID,
    ATTR_ZONE_NAME,
    SERVICE_SET_LAYOUT,
    SERVICE_SET_PLAYLIST,
    SERVICE_SHOW_FILE,
    SERVICE_SHOW_HTML,
    SERVICE_SHOW_STREAM,
    SERVICE_SYNCHRONIZE,
)
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity

ZONE_SCHEMA = {
    vol.Optional(ATTR_ZONE_ID): cv.string,
    vol.Optional(ATTR_ZONE_NAME): cv.string,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow media player and its entity services."""
    async_add_entities([SlideshowMediaPlayer(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SHOW_FILE,
        {
            vol.Required(ATTR_FILE): cv.string,
            vol.Required(ATTR_LENGTH): vol.All(vol.Coerce(int), vol.Range(min=1)),
            **ZONE_SCHEMA,
        },
        "async_show_file",
    )
    platform.async_register_entity_service(
        SERVICE_SHOW_HTML,
        {
            vol.Required(ATTR_HTML): cv.string,
            vol.Required(ATTR_LENGTH): vol.All(vol.Coerce(int), vol.Range(min=1)),
            **ZONE_SCHEMA,
        },
        "async_show_html",
    )
    platform.async_register_entity_service(
        SERVICE_SHOW_STREAM,
        {
            vol.Required(ATTR_URL): cv.string,
            vol.Required(ATTR_LENGTH): vol.All(vol.Coerce(int), vol.Range(min=1)),
            **ZONE_SCHEMA,
        },
        "async_show_stream",
    )
    platform.async_register_entity_service(
        SERVICE_SET_PLAYLIST,
        vol.All(
            cv.make_entity_service_schema(
                {
                    vol.Optional(ATTR_PLAYLIST_ID): vol.Coerce(int),
                    vol.Optional(ATTR_PLAYLIST_NAME): cv.string,
                    vol.Optional(ATTR_PLAYLIST_NUMBER): vol.Coerce(int),
                    vol.Optional(ATTR_LENGTH): vol.All(
                        vol.Coerce(int), vol.Range(min=1)
                    ),
                    **ZONE_SCHEMA,
                }
            ),
            cv.has_at_least_one_key(
                ATTR_PLAYLIST_ID, ATTR_PLAYLIST_NAME, ATTR_PLAYLIST_NUMBER
            ),
        ),
        "async_set_playlist",
    )
    platform.async_register_entity_service(
        SERVICE_SET_LAYOUT,
        vol.All(
            cv.make_entity_service_schema(
                {
                    vol.Optional(ATTR_LAYOUT_ID): vol.Coerce(int),
                    vol.Optional(ATTR_LAYOUT_NAME): cv.string,
                    vol.Optional(ATTR_LENGTH): vol.All(
                        vol.Coerce(int), vol.Range(min=1)
                    ),
                }
            ),
            cv.has_at_least_one_key(ATTR_LAYOUT_ID, ATTR_LAYOUT_NAME),
        ),
        "async_set_layout",
    )
    platform.async_register_entity_service(
        SERVICE_SYNCHRONIZE,
        {
            vol.Required(ATTR_URL): cv.string,
            vol.Optional(ATTR_METHOD, default="GET"): vol.In(["GET", "POST"]),
            vol.Optional(ATTR_TARGET): cv.string,
            vol.Optional(ATTR_CLEAR_FOLDER, default=False): cv.boolean,
        },
        "async_synchronize",
    )


class SlideshowMediaPlayer(SlideshowEntity, MediaPlayerEntity):
    """Transport controls for the player's main zone."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_media_content_type = MediaType.IMAGE
    _attr_supported_features = (
        MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the media player."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_media_player"
        self._volume_before_mute: int | None = None

    @property
    def _data(self) -> dict[str, Any]:
        """Return the latest device status."""
        return self.coordinator.data or {}

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state.

        The device reports the screen's power state separately from playback,
        so a powered-down screen is surfaced as ``off`` even though the app
        keeps running behind it.
        """
        if self._data.get("screenPower") is False:
            return MediaPlayerState.OFF
        if self._data.get("paused"):
            return MediaPlayerState.PAUSED
        return MediaPlayerState.PLAYING

    @property
    def media_content_id(self) -> str | None:
        """Return the path of the file currently on screen."""
        return self._data.get("lastDisplayedFile")

    @property
    def media_title(self) -> str | None:
        """Return the file name currently on screen."""
        if not (path := self._data.get("lastDisplayedFile")):
            return None
        return path.rsplit("/", 1)[-1]

    @property
    def source(self) -> str | None:
        """Return the playlist the main zone is playing."""
        return self._data.get("currentPlaylist")

    @property
    def app_name(self) -> str | None:
        """Return the active screen layout."""
        return self._data.get("currentScreenLayout")

    @property
    def volume_level(self) -> float | None:
        """Return the device volume as a fraction."""
        if (volume := self._data.get("currentVolume")) is None:
            return None
        return volume / 100

    @property
    def is_volume_muted(self) -> bool:
        """Return whether the device is muted."""
        return self._data.get("currentVolume") == 0

    async def async_media_pause(self) -> None:
        """Pause the main zone."""
        await self.client.async_pause()
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        """Resume the main zone."""
        await self.client.async_resume()
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        """Show the next file."""
        await self.client.async_next()
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        """Show the previous file."""
        await self.client.async_previous()
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the device volume."""
        await self.client.async_set_volume(round(volume * 100))
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or restore the device volume."""
        if mute:
            self._volume_before_mute = self._data.get("currentVolume") or 0
            await self.client.async_set_volume(0)
        else:
            await self.client.async_set_volume(self._volume_before_mute or 20)
        await self.coordinator.async_request_refresh()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Display a file from the player's storage, or a stream URL."""
        length = int(kwargs.get("extra", {}).get("length", 30))
        if media_id.startswith(("http://", "https://", "rtsp://", "rtmp://")):
            await self.client.async_show_stream(media_id, length)
        else:
            await self.client.async_show_file(media_id, length)
        await self.coordinator.async_request_refresh()

    # -- Entity services -----------------------------------------------------

    async def async_show_file(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.show_file`` service."""
        await self.client.async_show_file(
            kwargs[ATTR_FILE],
            kwargs[ATTR_LENGTH],
            zone_id=kwargs.get(ATTR_ZONE_ID),
            zone_name=kwargs.get(ATTR_ZONE_NAME),
        )
        await self.coordinator.async_request_refresh()

    async def async_show_html(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.show_html`` service."""
        await self.client.async_show_html(
            kwargs[ATTR_HTML],
            kwargs[ATTR_LENGTH],
            zone_id=kwargs.get(ATTR_ZONE_ID),
            zone_name=kwargs.get(ATTR_ZONE_NAME),
        )
        await self.coordinator.async_request_refresh()

    async def async_show_stream(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.show_stream`` service."""
        await self.client.async_show_stream(
            kwargs[ATTR_URL],
            kwargs[ATTR_LENGTH],
            zone_id=kwargs.get(ATTR_ZONE_ID),
            zone_name=kwargs.get(ATTR_ZONE_NAME),
        )
        await self.coordinator.async_request_refresh()

    async def async_set_playlist(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.set_playlist`` service."""
        await self.client.async_set_playlist(
            playlist_id=kwargs.get(ATTR_PLAYLIST_ID),
            playlist_name=kwargs.get(ATTR_PLAYLIST_NAME),
            playlist_number=kwargs.get(ATTR_PLAYLIST_NUMBER),
            length=kwargs.get(ATTR_LENGTH),
            zone_id=kwargs.get(ATTR_ZONE_ID),
            zone_name=kwargs.get(ATTR_ZONE_NAME),
        )
        await self.coordinator.async_request_refresh()

    async def async_set_layout(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.set_layout`` service."""
        await self.client.async_set_layout(
            layout_id=kwargs.get(ATTR_LAYOUT_ID),
            layout_name=kwargs.get(ATTR_LAYOUT_NAME),
            length=kwargs.get(ATTR_LENGTH),
        )
        await self.coordinator.async_request_refresh()

    async def async_synchronize(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.synchronize`` service."""
        await self.client.async_synchronize(
            kwargs[ATTR_URL],
            method=kwargs.get(ATTR_METHOD, "GET"),
            target=kwargs.get(ATTR_TARGET),
            clear_folder=kwargs.get(ATTR_CLEAR_FOLDER, False),
        )
