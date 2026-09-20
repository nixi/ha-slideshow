"""Polling coordinator for a SlideShow player."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SlideshowAuthError, SlideshowClient, SlideshowError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current device status."""
        try:
            return await self.client.async_get_device_info()
        except SlideshowAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SlideshowError as err:
            raise UpdateFailed(str(err)) from err
