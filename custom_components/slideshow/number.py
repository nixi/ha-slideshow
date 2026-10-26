"""Screen brightness for a SlideShow player."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import SlideshowApiError
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up brightness control for players that report their brightness."""
    coordinator = entry.runtime_data
    if "screenBrightness" in (coordinator.data or {}):
        async_add_entities([SlideshowBrightnessNumber(coordinator)])


class SlideshowBrightnessNumber(SlideshowEntity, NumberEntity):
    """Set the screen brightness.

    Only devices whose hardware SlideShow can drive accept a new value; the
    rest still report their brightness, so the entity exists but setting it
    fails with the device's reason.
    """

    _attr_translation_key = "screen_brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the number."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_screen_brightness_control"

    @property
    def native_value(self) -> int | None:
        """Return the current brightness."""
        return (self.coordinator.data or {}).get("screenBrightness")

    async def async_set_native_value(self, value: float) -> None:
        """Set a new brightness."""
        try:
            await self.client.async_set_screen_brightness(round(value))
        except SlideshowApiError as err:
            raise HomeAssistantError(
                f"{self.coordinator.config_entry.title} cannot set its "
                f"brightness: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
