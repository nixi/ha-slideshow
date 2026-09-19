"""Binary sensors for a SlideShow player."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity


@dataclass(frozen=True, kw_only=True)
class SlideshowBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a SlideShow binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[SlideshowBinarySensorDescription, ...] = (
    SlideshowBinarySensorDescription(
        key="screen_power",
        translation_key="screen_power",
        value_fn=lambda data: data.get("screenPower"),
    ),
    SlideshowBinarySensorDescription(
        key="paused",
        translation_key="paused",
        value_fn=lambda data: data.get("paused"),
    ),
    SlideshowBinarySensorDescription(
        key="rooted",
        translation_key="rooted",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("rooted"),
    ),
    SlideshowBinarySensorDescription(
        key="device_owner",
        translation_key="device_owner",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("deviceOwner"),
    ),
    SlideshowBinarySensorDescription(
        key="lock_task_mode",
        translation_key="lock_task_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("lockTaskMode"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        SlideshowBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class SlideshowBinarySensor(SlideshowEntity, BinarySensorEntity):
    """A boolean value read from ``/ajax/deviceInfo``."""

    entity_description: SlideshowBinarySensorDescription

    def __init__(
        self,
        coordinator: SlideshowCoordinator,
        description: SlideshowBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator.data or {})
