"""Buttons for a SlideShow player."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import SlideshowClient
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity


@dataclass(frozen=True, kw_only=True)
class SlideshowButtonDescription(ButtonEntityDescription):
    """Describes a SlideShow button."""

    press_fn: Callable[[SlideshowClient], Coroutine[Any, Any, None]]
    refresh: bool = True


BUTTONS: tuple[SlideshowButtonDescription, ...] = (
    SlideshowButtonDescription(
        key="next",
        translation_key="next",
        press_fn=lambda client: client.async_next(),
    ),
    SlideshowButtonDescription(
        key="previous",
        translation_key="previous",
        press_fn=lambda client: client.async_previous(),
    ),
    SlideshowButtonDescription(
        key="audio_next",
        translation_key="audio_next",
        entity_registry_enabled_default=False,
        press_fn=lambda client: client.async_audio_next(),
    ),
    SlideshowButtonDescription(
        key="toggle_fullscreen",
        translation_key="toggle_fullscreen",
        press_fn=lambda client: client.async_toggle_fullscreen(),
    ),
    SlideshowButtonDescription(
        key="clear_playlist",
        translation_key="clear_playlist",
        press_fn=lambda client: client.async_clear_playlist(),
    ),
    SlideshowButtonDescription(
        key="clear_layout",
        translation_key="clear_layout",
        press_fn=lambda client: client.async_clear_layout(),
    ),
    SlideshowButtonDescription(
        key="activate_screensaver",
        translation_key="activate_screensaver",
        press_fn=lambda client: client.async_activate_screensaver(),
    ),
    SlideshowButtonDescription(
        key="deactivate_screensaver",
        translation_key="deactivate_screensaver",
        press_fn=lambda client: client.async_deactivate_screensaver(),
    ),
    SlideshowButtonDescription(
        key="beep",
        translation_key="beep",
        entity_registry_enabled_default=False,
        refresh=False,
        press_fn=lambda client: client.async_beep(),
    ),
    SlideshowButtonDescription(
        key="reload_app",
        translation_key="reload_app",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        refresh=False,
        press_fn=lambda client: client.async_reload(),
    ),
    SlideshowButtonDescription(
        key="reboot_device",
        translation_key="reboot_device",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        refresh=False,
        press_fn=lambda client: client.async_reboot(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        SlideshowButton(coordinator, description) for description in BUTTONS
    )


class SlideshowButton(SlideshowEntity, ButtonEntity):
    """A one-shot command sent to the player."""

    entity_description: SlideshowButtonDescription

    def __init__(
        self,
        coordinator: SlideshowCoordinator,
        description: SlideshowButtonDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    async def async_press(self) -> None:
        """Send the command."""
        await self.entity_description.press_fn(self.client)
        if self.entity_description.refresh:
            await self.coordinator.async_request_refresh()
