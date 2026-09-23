"""Tests for following a player to a new address."""

from homeassistant.config_entries import SOURCE_DHCP
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.slideshow.const import DOMAIN

from .const import CONTENT, DEVICE_INFO, PORT

NEW_HOST = "192.0.2.99"
NEW_BASE = f"http://{NEW_HOST}:{PORT}"
MAC = DEVICE_INFO["macAddress"].replace(":", "").lower()


def _serve_new_address(aioclient_mock, device_info=DEVICE_INFO) -> None:
    """Make the old address dead and the new one answer."""
    from .const import BASE

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", exc=TimeoutError())
    aioclient_mock.get(f"{NEW_BASE}/ajax/deviceInfo", json=device_info)
    aioclient_mock.get(
        f"{NEW_BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )


async def _dhcp(hass: HomeAssistant, mac: str = MAC, ip: str = NEW_HOST):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip=ip, hostname="android", macaddress=mac),
    )


async def test_dhcp_follows_a_known_player(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A new lease for a known MAC moves the entry to the new address."""
    _serve_new_address(aioclient_mock)
    secret = init_integration.data["panel_secret"]

    result = await _dhcp(hass)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert init_integration.data["host"] == NEW_HOST
    # The panel address must survive the move, or every player showing it breaks.
    assert init_integration.data["panel_secret"] == secret


async def test_dhcp_moves_even_before_the_app_answers(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """If nothing answers yet, the registry's MAC match is trusted.

    The address change usually comes with a reboot, so the app may not be up
    when the lease is seen; waiting for it would mean never moving.
    """
    from .const import BASE

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", exc=TimeoutError())
    aioclient_mock.get(f"{NEW_BASE}/ajax/deviceInfo", exc=TimeoutError())

    await _dhcp(hass)
    await hass.async_block_till_done()

    assert init_integration.data["host"] == NEW_HOST


async def test_dhcp_refuses_a_different_player(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A new address answering as another player must not be adopted."""
    _serve_new_address(aioclient_mock, {**DEVICE_INFO, "deviceId": "someone-else"})

    await _dhcp(hass)
    await hass.async_block_till_done()

    assert init_integration.data["host"] != NEW_HOST


async def test_dhcp_leaves_a_working_player_alone(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A player still answering where it is does not get moved."""
    await _dhcp(hass)
    await hass.async_block_till_done()

    assert init_integration.data["host"] != NEW_HOST


async def test_dhcp_ignores_unknown_devices(
    hass: HomeAssistant, init_integration
) -> None:
    """Only players already configured are followed."""
    result = await _dhcp(hass, mac="aabbccddeeff")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_reconfigure_changes_the_address(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Reconfigure moves the entry without regenerating the panel secret."""
    _serve_new_address(aioclient_mock)
    secret = init_integration.data["panel_secret"]

    result = await init_integration.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": NEW_HOST, "port": PORT, "ssl": False, "verify_ssl": False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data["host"] == NEW_HOST
    assert init_integration.data["panel_secret"] == secret


async def test_reconfigure_rejects_a_different_player(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Pointing an entry at another player's address is refused."""
    _serve_new_address(aioclient_mock, {**DEVICE_INFO, "deviceId": "someone-else"})

    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": NEW_HOST, "port": PORT, "ssl": False, "verify_ssl": False},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert init_integration.data["host"] != NEW_HOST
