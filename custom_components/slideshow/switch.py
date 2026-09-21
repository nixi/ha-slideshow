"""Screen power switch for a SlideShow player."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SCREEN_OFF_LAYOUT, DEFAULT_SCREEN_OFF_LAYOUT
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

    The public API has no screen power endpoint. What it does have is the
    layout SlideShow switches to when a screen layout schedule powers the
    display down, so selecting that layout turns the screen off and clearing
    the override turns it back on. ``screenPower`` reports the real state, so
    this is a read-back switch rather than an assumed one.
    """

    _attr_translation_key = "screen"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_screen"

    @property
    def _screen_off_layout(self) -> str:
        """Return the layout name that powers the screen down."""
        return self.coordinator.config_entry.options.get(
            CONF_SCREEN_OFF_LAYOUT, DEFAULT_SCREEN_OFF_LAYOUT
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the display is powered."""
        return (self.coordinator.data or {}).get("screenPower")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power the display back on by dropping the layout override."""
        await self.client.async_clear_layout()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power the display down."""
        await self.client.async_set_layout(layout_name=self._screen_off_layout)
        await self.coordinator.async_request_refresh()
