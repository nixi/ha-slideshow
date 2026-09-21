"""Media player for the main zone of a SlideShow player."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import media_source
from homeassistant.components.camera import async_get_stream_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    ATTR_CAMERA_ENTITY_ID,
    ATTR_CLEAR_FOLDER,
    ATTR_CONTENT_ID,
    ATTR_CONTENT_NAME,
    ATTR_CONTENT_TYPE,
    ATTR_DURATION,
    ATTR_FILE,
    ATTR_FILENAME,
    ATTR_HTML,
    ATTR_LAYOUT_ID,
    ATTR_LAYOUT_NAME,
    ATTR_LENGTH,
    ATTR_METHOD,
    ATTR_PATH,
    ATTR_PLAYLIST_ID,
    ATTR_PLAYLIST_NAME,
    ATTR_PLAYLIST_NUMBER,
    ATTR_TARGET,
    ATTR_URL,
    ATTR_ZONE_ID,
    ATTR_ZONE_NAME,
    AUDIO_ZONE_ID,
    CONF_PANEL_SECRET,
    CONF_SCREEN_OFF_LAYOUT,
    CONTENT_TYPES,
    DEFAULT_MEDIA_DURATION,
    DEFAULT_PANEL_CONTENT_NAME,
    DEFAULT_PANEL_FILENAME,
    DEFAULT_SCREEN_OFF_LAYOUT,
    SERVICE_CREATE_CONTENT,
    SERVICE_DELETE_CONTENT,
    SERVICE_INSTALL_PANEL,
    SERVICE_SET_LAYOUT,
    SERVICE_SET_PLAYLIST,
    SERVICE_SHOW_CAMERA,
    SERVICE_SHOW_FILE,
    SERVICE_SHOW_HTML,
    SERVICE_SHOW_STREAM,
    SERVICE_SYNCHRONIZE,
)
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity
from .panel import panel_url_file_path

_LOGGER = logging.getLogger(__name__)

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
        SERVICE_SHOW_CAMERA,
        {
            vol.Required(ATTR_CAMERA_ENTITY_ID): cv.entity_id,
            vol.Optional(ATTR_DURATION, default=DEFAULT_MEDIA_DURATION): vol.All(
                vol.Coerce(int), vol.Range(min=1)
            ),
            **ZONE_SCHEMA,
        },
        "async_show_camera",
    )
    platform.async_register_entity_service(
        SERVICE_CREATE_CONTENT,
        {
            vol.Required(ATTR_CONTENT_NAME): cv.string,
            vol.Required(ATTR_PATH): cv.string,
            vol.Optional(ATTR_CONTENT_TYPE, default="ALPHABETICALLY"): vol.In(
                CONTENT_TYPES
            ),
        },
        "async_create_content",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_CONTENT,
        {vol.Required(ATTR_CONTENT_ID): vol.Coerce(int)},
        "async_delete_content",
    )
    platform.async_register_entity_service(
        SERVICE_INSTALL_PANEL,
        {
            vol.Optional(
                ATTR_CONTENT_NAME, default=DEFAULT_PANEL_CONTENT_NAME
            ): cv.string,
            vol.Optional(ATTR_FILENAME, default=DEFAULT_PANEL_FILENAME): cv.string,
        },
        "async_install_panel",
    )
    platform.async_register_entity_service(
        SERVICE_SYNCHRONIZE,
        {
            vol.Required(ATTR_URL): cv.string,
            vol.Required(ATTR_TARGET): cv.string,
            vol.Optional(ATTR_METHOD, default="GET"): vol.In(["GET", "POST", "PUT"]),
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
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
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
    def source_list(self) -> list[str]:
        """Return the playlists the player offers."""
        return sorted(self.coordinator.playlists)

    async def async_select_source(self, source: str) -> None:
        """Switch the main zone to a playlist by name."""
        playlist_id = self.coordinator.playlists.get(source)
        if playlist_id is None:
            await self.coordinator.async_refresh_playlists()
            playlist_id = self.coordinator.playlists.get(source)
        if playlist_id is None:
            raise HomeAssistantError(f"The player has no playlist named {source!r}")

        await self.client.async_set_playlist(playlist_id=playlist_id)
        await self.coordinator.async_request_refresh()

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

    async def async_turn_on(self) -> None:
        """Power the display on by dropping the layout override."""
        await self.client.async_clear_layout()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Power the display down via the screen-off layout."""
        layout = self.coordinator.config_entry.options.get(
            CONF_SCREEN_OFF_LAYOUT, DEFAULT_SCREEN_OFF_LAYOUT
        )
        await self.client.async_set_layout(layout_name=layout)
        await self.coordinator.async_request_refresh()

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

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Home Assistant's media sources."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith(
                ("audio/", "video/", "image/")
            ),
        )

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play media on the player.

        Home Assistant media (the media library, text-to-speech) arrives as a
        ``media_source://`` ID which resolves to an HTTP URL served by Home
        Assistant itself, so the player has to be able to reach Home Assistant
        on the network.
        """
        mime_type: str | None = None
        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_id = play_item.url
            mime_type = play_item.mime_type

        media_id = async_process_play_media_url(self.hass, media_id)
        duration = int(kwargs.get("extra", {}).get("duration", DEFAULT_MEDIA_DURATION))
        zone_id = kwargs.get("extra", {}).get("zone_id")

        is_audio = (mime_type or "").startswith("audio/") or media_type in (
            MediaType.MUSIC,
            "audio",
        )
        is_image = (mime_type or "").startswith("image/") or (
            media_type == MediaType.IMAGE
        )

        if is_image:
            # There is no endpoint that displays a remote image, but an HTML
            # fragment pointing at the URL achieves the same thing.
            await self.client.async_show_html(
                _fullscreen_image_html(media_id), duration, zone_id=zone_id
            )
        elif is_audio:
            # Playing into the audio zone leaves whatever is on screen alone.
            await self.client.async_show_stream(
                media_id, duration, zone_id=zone_id or AUDIO_ZONE_ID
            )
        else:
            await self.client.async_show_stream(media_id, duration, zone_id=zone_id)

        await self.coordinator.async_request_refresh()

    async def async_show_camera(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.show_camera`` service.

        Prefers the camera's own RTSP source, which the player can render
        directly, and falls back to Home Assistant's still image.
        """
        camera_entity_id = kwargs[ATTR_CAMERA_ENTITY_ID]
        duration = kwargs.get(ATTR_DURATION, DEFAULT_MEDIA_DURATION)
        zone_id = kwargs.get(ATTR_ZONE_ID)
        zone_name = kwargs.get(ATTR_ZONE_NAME)

        try:
            stream_source = await async_get_stream_source(self.hass, camera_entity_id)
        except HomeAssistantError as err:
            raise HomeAssistantError(
                f"Could not read a stream from {camera_entity_id}: {err}"
            ) from err

        if stream_source:
            await self.client.async_show_stream(
                stream_source, duration, zone_id=zone_id, zone_name=zone_name
            )
        else:
            # No stream: fall back to the camera's still image, refreshed by
            # the page itself so it does not freeze on a single frame.
            state = self.hass.states.get(camera_entity_id)
            if state is None or not (path := state.attributes.get("entity_picture")):
                raise HomeAssistantError(
                    f"{camera_entity_id} offers neither a stream nor a still image"
                )
            await self.client.async_show_html(
                _refreshing_image_html(async_process_play_media_url(self.hass, path)),
                duration,
                zone_id=zone_id,
                zone_name=zone_name,
            )

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

    async def async_create_content(self, **kwargs: Any) -> ServiceResponse:
        """Handle the ``slideshow.create_content`` action.

        Returns the new content and playlist IDs, and refreshes the playlist
        list so the entry is selectable straight away.
        """
        result = await self.client.async_create_content(
            kwargs[ATTR_CONTENT_NAME],
            kwargs[ATTR_PATH],
            kwargs[ATTR_CONTENT_TYPE],
        )
        await self.coordinator.async_refresh_playlists()
        return {
            "content_id": result.get("id"),
            "playlist_id": result.get("playlistId"),
        }

    async def async_delete_content(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.delete_content`` action."""
        await self.client.async_delete_content(kwargs[ATTR_CONTENT_ID])
        await self.coordinator.async_refresh_playlists()

    async def async_install_panel(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.install_panel`` action.

        Puts the live dashboard into a playlist of its own, so it can be
        chosen like any other. The player has no upload endpoint, so it is
        told to synchronize a one-line .url file that Home Assistant serves,
        and a content entry is created pointing at it.
        """
        secret = self.coordinator.config_entry.data.get(CONF_PANEL_SECRET)
        if not secret:
            raise HomeAssistantError("This player has no panel secret yet")

        try:
            base = get_url(self.hass, allow_external=False, allow_cloud=False)
        except NoURLAvailableError:
            try:
                base = get_url(self.hass, allow_cloud=False)
            except NoURLAvailableError as err:
                raise HomeAssistantError(
                    "Home Assistant does not know its own address. Set the internal "
                    "URL under Settings, System, Network."
                ) from err

        filename = kwargs[ATTR_FILENAME]
        await self.client.async_synchronize(
            f"{base}{panel_url_file_path(secret)}", filename
        )
        result = await self.client.async_create_content(
            kwargs[ATTR_CONTENT_NAME], filename
        )
        # So the new playlist shows up in the select without waiting.
        await self.coordinator.async_refresh_playlists()
        _LOGGER.debug("Installed panel as content %s", result)

    async def async_synchronize(self, **kwargs: Any) -> None:
        """Handle the ``slideshow.synchronize`` service."""
        await self.client.async_synchronize(
            kwargs[ATTR_URL],
            kwargs[ATTR_TARGET],
            method=kwargs.get(ATTR_METHOD, "GET"),
            clear_folder=kwargs.get(ATTR_CLEAR_FOLDER, False),
        )


def _fullscreen_image_html(url: str) -> str:
    """Return HTML that shows one image filling the zone."""
    return (
        '<div style="position:absolute;inset:0;background:#000">'
        f'<img src="{url}" '
        'style="width:100%;height:100%;object-fit:contain"></div>'
    )


def _refreshing_image_html(url: str) -> str:
    """Return HTML that reloads a still image once a second."""
    separator = "&" if "?" in url else "?"
    return (
        '<div style="position:absolute;inset:0;background:#000">'
        f'<img id="c" src="{url}" '
        'style="width:100%;height:100%;object-fit:contain">'
        "<script>setInterval(function(){document.getElementById('c').src="
        f"'{url}{separator}t='+Date.now();}}, 1000);</script></div>"
    )
