"""Screenshot camera for a SlideShow player."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.camera import Camera, CameraEntityFeature
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
        self._cached_at = None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a JPEG of the player's current screen."""
        now = dt_util.utcnow()
        if (
            self._cached_image is not None
            and self._cached_at is not None
            and now - self._cached_at < CACHE_TTL
        ):
            return self._cached_image

        try:
            image = await self.client.async_get_screenshot()
        except SlideshowError as err:
            _LOGGER.debug("Could not fetch screenshot: %s", err)
            return self._cached_image

        self._cached_image = image
        self._cached_at = now
        return image
