"""Playlist selection for a SlideShow player."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the playlist select."""
    async_add_entities([SlideshowPlaylistSelect(entry.runtime_data)])


class SlideshowPlaylistSelect(SlideshowEntity, SelectEntity):
    """Choose which playlist the main zone plays.

    The API has no endpoint that lists playlists, but every content entry
    carries a name and the ID of the playlist it belongs to, so the list is
    built from those.
    """

    _attr_translation_key = "playlist"

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_playlist"

    @property
    def options(self) -> list[str]:
        """Return the playlists the player offers."""
        return sorted(self.coordinator.playlists)

    @property
    def current_option(self) -> str | None:
        """Return the playlist currently playing in the main zone.

        The player can report a playlist that has no content entry of its own,
        so this is deliberately allowed to be absent from the options.
        """
        current = (self.coordinator.data or {}).get("currentPlaylist")
        return current if current in self.coordinator.playlists else None

    async def async_select_option(self, option: str) -> None:
        """Switch the main zone to the chosen playlist."""
        playlist_id = self.coordinator.playlists.get(option)
        if playlist_id is None:
            # The list may be stale if the playlist was added on the device.
            await self.coordinator.async_refresh_playlists()
            playlist_id = self.coordinator.playlists.get(option)
        if playlist_id is None:
            raise HomeAssistantError(f"The player has no playlist named {option!r}")

        await self.client.async_set_playlist(playlist_id=playlist_id)
        await self.coordinator.async_request_refresh()
