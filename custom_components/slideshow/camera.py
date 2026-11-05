"""Screenshot camera for a SlideShow player."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.const import CAMERA_IMAGE_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import SlideshowError
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity

_LOGGER = logging.getLogger(__name__)

# Screenshots are relatively expensive on the low-powered Android devices these
# players tend to run on, so the most recent one is reused briefly.
CACHE_TTL = timedelta(seconds=5)

# Home Assistant gives up on a camera image after CAMERA_IMAGE_TIMEOUT
# seconds, but a screenshot can take longer than that. So the screenshot is
# taken in the background and a caller waits only this long for it, then
# gets the last one instead.
SCREENSHOT_WAIT = CAMERA_IMAGE_TIMEOUT - 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow screenshot camera."""
    async_add_entities([SlideshowScreenshotCamera(entry.runtime_data)])


class SlideshowScreenshotCamera(SlideshowEntity, Camera):
    """Serve ``/ajax/screenshot`` as a camera image."""

    _attr_translation_key = "screenshot"
    _attr_supported_features = CameraEntityFeature(0)
    _attr_frame_interval = 5.0

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the camera."""
        SlideshowEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{self._device_id}_screenshot"
        self._cached_image: bytes | None = None
        self._cached_at: datetime | None = None
        self._fetch: asyncio.Task[None] | None = None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a JPEG of the player's current screen.

        A slow screenshot carries on after the caller has given up, and the
        next caller gets it from the cache. Only one is taken at a time.
        """
        if (
            self._cached_image is not None
            and self._cached_at is not None
            and dt_util.utcnow() - self._cached_at < CACHE_TTL
        ):
            return self._cached_image

        if self._fetch is None or self._fetch.done():
            self._fetch = self.coordinator.config_entry.async_create_background_task(
                self.hass, self._async_fetch_screenshot(), "slideshow screenshot"
            )
        # Unlike wait_for, this neither cancels the fetch on timeout nor
        # when the caller itself is cancelled.
        await asyncio.wait({self._fetch}, timeout=SCREENSHOT_WAIT)
        return self._cached_image

    async def _async_fetch_screenshot(self) -> None:
        """Take a screenshot and keep it for the next callers."""
        try:
            self._cached_image = await self.client.async_get_screenshot()
        except SlideshowError as err:
            _LOGGER.debug("Could not fetch screenshot: %s", err)
            return
        self._cached_at = dt_util.utcnow()
