"""Tests for diagnostics."""

import re

from aiohttp import ClientConnectionError
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .const import DEVICE_INFO, HOST, PORT


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
    # The secret alone opens the panel page, which needs no login.
    assert result["entry"]["data"]["panel_secret"] != "test-secret"
    assert "test-secret" not in str(result)
    assert result["entry"]["data"]["host"] != DEVICE_INFO["ipAddressInternal"]
    assert result["device_info"]["macAddress"] != DEVICE_INFO["macAddress"]
    assert result["device_info"]["serialNumber"] != DEVICE_INFO["serialNumber"]
    # Non-identifying fields stay, or the report is useless.
    assert result["device_info"]["softwareVersion"] == DEVICE_INFO["softwareVersion"]


async def test_errors_do_not_reveal_the_address(
    hass: HomeAssistant, hass_client, aioclient_mock, init_integration
) -> None:
    """A player that is offline while diagnostics are taken stays anonymous."""
    aioclient_mock.get(re.compile(r"/ajax/zones"), exc=TimeoutError())
    aioclient_mock.get(
        re.compile(r"/ajax/displayInfo"),
        exc=ClientConnectionError(f"Cannot connect to host {HOST}:{PORT}"),
    )

    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert "error" in result["zones"]
    assert "error" in result["displays"]
    assert HOST not in str(result)


async def test_resolved_addresses_are_redacted_too(
    hass: HomeAssistant, hass_client, aioclient_mock, init_integration
) -> None:
    """A host set as a name still resolves to an address the error names."""
    aioclient_mock.get(
        re.compile(r"/ajax/zones"),
        exc=ClientConnectionError("Connect call failed ('192.168.11.184', 8080)"),
    )
    aioclient_mock.get(
        re.compile(r"/ajax/displayInfo"),
        exc=ClientConnectionError("Connect call failed ('fd00::1:2', 8080)"),
    )

    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert "192.168.11.184" not in str(result)
    assert "fd00::1:2" not in str(result)
