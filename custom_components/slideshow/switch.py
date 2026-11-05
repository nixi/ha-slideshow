"""Screen power switch for a SlideShow player."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow switches."""
    async_add_entities([SlideshowScreenSwitch(entry.runtime_data)])


class SlideshowScreenSwitch(SlideshowEntity, SwitchEntity):
    """Turn the player's display on and off.

    Uses the screen power endpoint where the device supports it, and the
    screen off layout elsewhere; see ``async_set_screen_power``. The state is
    read back from the player: ``screenPower``, and off while a power-off
    layout is on screen.
    """

    _attr_translation_key = "screen"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_screen"

    @property
    def is_on(self) -> bool | None:
        """Return whether the display is showing anything."""
        return self.coordinator.screen_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power the display on."""
        await self.coordinator.async_set_screen_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power the display down."""
        await self.coordinator.async_set_screen_power(False)
