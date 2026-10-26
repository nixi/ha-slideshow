"""Playlist and screen layout selection for a SlideShow player."""

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
    """Set up the playlist select, and the layout select where layouts are listed."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [SlideshowPlaylistSelect(coordinator)]
    if coordinator.supports("layout/get"):
        entities.append(SlideshowLayoutSelect(coordinator))
    async_add_entities(entities)


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


class SlideshowLayoutSelect(SlideshowEntity, SelectEntity):
    """Choose the screen layout, from the list SlideShow offers from 4.13.0.

    The choice is an override, like ``slideshow.set_layout``: the player's
    own layout schedule takes over again at its next change.
    """

    _attr_translation_key = "screen_layout"

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the select."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_screen_layout"

    @property
    def options(self) -> list[str]:
        """Return the player's screen layouts."""
        return sorted(self.coordinator.layouts)

    @property
    def current_option(self) -> str | None:
        """Return the screen layout on screen."""
        current = (self.coordinator.data or {}).get("currentScreenLayout")
        return current if current in self.coordinator.layouts else None

    async def async_select_option(self, option: str) -> None:
        """Switch to the chosen screen layout."""
        layout = self.coordinator.layouts.get(option)
        if layout is None:
            await self.coordinator.async_refresh_layouts()
            layout = self.coordinator.layouts.get(option)
        if layout is None:
            raise HomeAssistantError(
                f"The player has no screen layout named {option!r}"
            )

        if (layout_id := layout.get("id")) is not None:
            await self.client.async_set_layout(layout_id=layout_id)
        else:
            await self.client.async_set_layout(layout_name=option)
        await self.coordinator.async_request_refresh()
