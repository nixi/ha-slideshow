"""Tests for diagnostics."""

import re

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .const import DEVICE_INFO


async def test_identifiers_are_redacted(
    hass: HomeAssistant, hass_client, aioclient_mock, init_integration
) -> None:
    """Diagnostics get attached to public issues, so identifiers must not leak."""
    aioclient_mock.get(re.compile(r"/ajax/zones"), json={"success": True, "result": {}})
    aioclient_mock.get(
        re.compile(r"/ajax/displayInfo"), json={"success": True, "result": {}}
    )

    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert result["entry"]["data"]["password"] != "admin"
    assert result["entry"]["data"]["host"] != DEVICE_INFO["ipAddressInternal"]
    assert result["device_info"]["macAddress"] != DEVICE_INFO["macAddress"]
    assert result["device_info"]["serialNumber"] != DEVICE_INFO["serialNumber"]
    # Non-identifying fields stay, or the report is useless.
    assert result["device_info"]["softwareVersion"] == DEVICE_INFO["softwareVersion"]
