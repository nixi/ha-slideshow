"""Base entity for the SlideShow integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SlideshowCoordinator


class SlideshowEntity(CoordinatorEntity[SlideshowCoordinator]):
    """Common device wiring for every SlideShow entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SlideshowCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._device_id = entry.unique_id or entry.entry_id

    @property
    def client(self):
        """Return the API client."""
        return self.coordinator.client

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the player as a single device."""
        data = self.coordinator.data or {}
        connections = set()
        if mac := data.get("macAddress"):
            connections.add((CONNECTION_NETWORK_MAC, format_mac(mac)))
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            connections=connections,
            manufacturer=MANUFACTURER,
            name=data.get("deviceName"),
            model=data.get("hardwareModel"),
            sw_version=data.get("softwareVersion"),
            serial_number=data.get("serialNumber"),
            configuration_url=self.client.base_url,
        )
