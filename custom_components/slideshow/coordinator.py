"""Polling coordinator for a SlideShow player."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SlideshowAuthError, SlideshowClient, SlideshowError
from .const import (
    AUTH_GRACE_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLAYLIST_REFRESH_INTERVAL,
)

if TYPE_CHECKING:
    from .panel import PanelRenderer

_LOGGER = logging.getLogger(__name__)

type SlideshowConfigEntry = ConfigEntry[SlideshowCoordinator]


class SlideshowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll ``/ajax/deviceInfo``, which carries the whole device status."""

    config_entry: SlideshowConfigEntry

    #: Set during setup; serves the live dashboard page for this player.
    panel: PanelRenderer

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SlideshowConfigEntry,
        client: SlideshowClient,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        self.client = client
        #: Playlist name to playlist ID, from the player's content entries.
        self.playlists: dict[str, int] = {}
        self._playlists_read: datetime | None = None
        self._auth_rejected_since: datetime | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current device status."""
        try:
            data = await self.client.async_get_device_info()
        except SlideshowAuthError as err:
            # A player can reject perfectly good credentials for a moment --
            # while it is starting up, or being reconfigured. Asking the user
            # to retype a password that never changed is worse than waiting,
            # so a rejection has to persist before reauthentication starts.
            now = dt_util.utcnow()
            if self._auth_rejected_since is None:
                self._auth_rejected_since = now
            rejected_for = now - self._auth_rejected_since
            if rejected_for >= AUTH_GRACE_PERIOD:
                raise ConfigEntryAuthFailed(str(err)) from err
            _LOGGER.warning(
                "%s has rejected the stored credentials for %s; asking for new "
                "ones if this continues past %s: %s",
                self.config_entry.title,
                str(rejected_for).split(".")[0],
                AUTH_GRACE_PERIOD,
                err,
            )
            raise UpdateFailed(str(err)) from err
        except SlideshowError as err:
            raise UpdateFailed(str(err)) from err

        self._auth_rejected_since = None

        # Content entries change rarely and cost an extra request, so they are
        # read on a slower cycle than the device status.
        now = dt_util.utcnow()
        if (
            self._playlists_read is None
            or now - self._playlists_read > PLAYLIST_REFRESH_INTERVAL
        ):
            await self.async_refresh_playlists()

        return data

    async def async_refresh_playlists(self) -> None:
        """Re-read the playlists the player offers.

        A failure here leaves the previous list in place: a momentarily
        unreachable player should not empty the source list.
        """
        try:
            content = await self.client.async_get_content()
        except SlideshowError as err:
            _LOGGER.debug("Could not read content entries: %s", err)
            return

        self.playlists = {
            entry["name"]: entry["playlistId"]
            for entry in content
            if entry.get("name") and entry.get("playlistId") is not None
        }
        self._playlists_read = dt_util.utcnow()
