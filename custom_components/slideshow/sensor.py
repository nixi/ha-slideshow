"""Sensors for a SlideShow player."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import CONF_PANEL_SECRET
from .coordinator import SlideshowConfigEntry, SlideshowCoordinator
from .entity import SlideshowEntity
from .panel import panel_path


def _timestamp_from_millis(data: dict[str, Any], key: str) -> datetime | None:
    """Convert an epoch-milliseconds field into an aware datetime."""
    value = data.get(key)
    if not value:
        return None
    return dt_util.utc_from_timestamp(value / 1000)


def _device_local_time(data: dict[str, Any], key: str) -> datetime | None:
    """Parse a naive device-local timestamp using the device's own time zone."""
    value = data.get(key)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        return parsed
    try:
        tzinfo = ZoneInfo(data["timeZone"])
    except (KeyError, ZoneInfoNotFoundError, ValueError):
        tzinfo = dt_util.get_default_time_zone()
    return parsed.replace(tzinfo=tzinfo)


def _storage_used_percent(data: dict[str, Any]) -> float | None:
    """Return how much of the internal storage is in use."""
    total = data.get("storageSpaceTotal")
    free = data.get("storageSpaceFree")
    if not total or free is None:
        return None
    return round((total - free) / total * 100, 1)


@dataclass(frozen=True, kw_only=True)
class SlideshowSensorDescription(SensorEntityDescription):
    """Describes a SlideShow sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[SlideshowSensorDescription, ...] = (
    SlideshowSensorDescription(
        key="current_playlist",
        translation_key="current_playlist",
        value_fn=lambda data: data.get("currentPlaylist"),
    ),
    SlideshowSensorDescription(
        key="current_layout",
        translation_key="current_layout",
        value_fn=lambda data: data.get("currentScreenLayout"),
    ),
    SlideshowSensorDescription(
        key="last_displayed_file",
        translation_key="last_displayed_file",
        value_fn=lambda data: data.get("lastDisplayedFile"),
    ),
    SlideshowSensorDescription(
        key="last_displayed_time",
        translation_key="last_displayed_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _device_local_time(data, "lastDisplayedTime"),
    ),
    SlideshowSensorDescription(
        key="volume",
        translation_key="volume",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("currentVolume"),
    ),
    SlideshowSensorDescription(
        key="screen_brightness",
        translation_key="screen_brightness",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("screenBrightness"),
    ),
    SlideshowSensorDescription(
        key="storage_free",
        translation_key="storage_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("storageSpaceFree"),
    ),
    SlideshowSensorDescription(
        key="storage_used_percent",
        translation_key="storage_used_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_storage_used_percent,
    ),
    SlideshowSensorDescription(
        key="storage_total",
        translation_key="storage_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("storageSpaceTotal"),
    ),
    SlideshowSensorDescription(
        key="device_booted",
        translation_key="device_booted",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _timestamp_from_millis(data, "uptime"),
    ),
    SlideshowSensorDescription(
        key="app_started",
        translation_key="app_started",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _timestamp_from_millis(data, "appUptime"),
    ),
    SlideshowSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("ipAddressInternal"),
    ),
    SlideshowSensorDescription(
        key="android_version",
        translation_key="android_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("androidVersion"),
    ),
    SlideshowSensorDescription(
        key="software_version",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("softwareVersion"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SlideshowConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the SlideShow sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        SlideshowSensor(coordinator, description) for description in SENSORS
    ]
    entities.append(SlideshowPanelUrlSensor(coordinator))
    async_add_entities(entities)


class SlideshowSensor(SlideshowEntity, SensorEntity):
    """A single value read from ``/ajax/deviceInfo``."""

    entity_description: SlideshowSensorDescription

    def __init__(
        self,
        coordinator: SlideshowCoordinator,
        description: SlideshowSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data or {})


class SlideshowPanelUrlSensor(SlideshowEntity, SensorEntity):
    """The address the player should load to show the live dashboard."""

    _attr_translation_key = "panel_url"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._device_id}_panel_url"

    @property
    def native_value(self) -> str | None:
        """Return the panel URL, or the path if no base URL is known."""
        secret = self.coordinator.config_entry.data.get(CONF_PANEL_SECRET)
        if not secret:
            return None
        path = panel_path(secret)
        try:
            # The player reaches Home Assistant over the LAN, so prefer the
            # internal URL and do not fall back to a cloud address.
            base = get_url(self.hass, allow_cloud=False, prefer_external=False)
        except NoURLAvailableError:
            return path
        return f"{base}{path}"
