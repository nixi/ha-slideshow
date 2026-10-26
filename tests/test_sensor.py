"""Tests for the sensors."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.slideshow.const import DOMAIN

from .common import mock_status_reads
from .const import BASE, CONTENT, DEVICE_INFO, SECONDS_SINCE_USER_ACTIVITY


def _entity_id(hass: HomeAssistant, key: str) -> str | None:
    """Return the entity ID of one of the player's sensors."""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DEVICE_INFO['deviceId']}_{key}"
    )


async def test_device_local_time_uses_the_device_zone(
    hass: HomeAssistant, init_integration
) -> None:
    """A naive timestamp from the player is read in the player's own zone."""
    await hass.config.async_set_time_zone("UTC")
    coordinator = init_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "last_displayed_time"))

    # Timestamp states are kept to the second.
    expected = datetime(2026, 9, 18, 8, 0, 5, tzinfo=ZoneInfo("Europe/Stockholm"))
    assert datetime.fromisoformat(state.state) == expected


async def test_unknown_device_zone_falls_back_to_home_assistant(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A zone name Home Assistant cannot load does not break the update."""
    coordinator = init_integration.runtime_data
    for name in ("Mars/Olympus_Mons", "/etc/localtime"):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"{BASE}/ajax/deviceInfo", json={**DEVICE_INFO, "timeZone": name}
        )
        mock_status_reads(aioclient_mock)
        await coordinator.async_refresh()

        assert coordinator.last_update_success
        assert coordinator.time_zone == dt_util.get_default_time_zone()


async def test_panel_url_sensor_is_gone(hass: HomeAssistant, init_integration) -> None:
    """The panel secret is never published as an entity state."""
    assert _entity_id(hass, "panel_url") is None
    assert not [
        state
        for state in hass.states.async_all()
        if "test-secret" in str(state.state) + str(state.attributes)
    ]


async def test_old_panel_url_sensor_is_removed(
    hass: HomeAssistant,
    aioclient_mock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Upgrading drops the sensor that earlier versions registered."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_INFO['deviceId']}_panel_url",
        config_entry=mock_config_entry,
    )
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    mock_status_reads(aioclient_mock)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _entity_id(hass, "panel_url") is None


async def test_cpu_temperature_only_where_reported(
    hass: HomeAssistant, init_integration
) -> None:
    """Players that do not measure it get no sensor, rather than an empty one."""
    assert _entity_id(hass, "cpu_temperature") is None
    assert _entity_id(hass, "operating_system") is None


async def test_new_device_fields(
    hass: HomeAssistant, aioclient_mock, mock_config_entry
) -> None:
    """Fields SlideShow 4.13.0 added become sensors when the player has them."""
    aioclient_mock.get(
        f"{BASE}/ajax/deviceInfo",
        json={
            **DEVICE_INFO,
            "cpuTemperature": 48.5,
            "operatingSystem": "Android 6.0.1",
        },
    )
    mock_status_reads(aioclient_mock)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, "cpu_temperature")).state == "48.5"
    # Diagnostic text, so it is there but off until enabled.
    assert _entity_id(hass, "operating_system") is not None


async def test_last_user_activity(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Seconds since the last touch become the moment it happened."""
    coordinator = init_integration.runtime_data
    state = hass.states.get(_entity_id(hass, "last_user_activity"))
    touched = datetime.fromisoformat(state.state)
    expected = dt_util.utcnow() - timedelta(seconds=SECONDS_SINCE_USER_ACTIVITY)
    assert abs(touched - expected) < timedelta(seconds=5)

    # The next poll works out a second later; that is the same touch, and
    # must not be recorded as a new one.
    coordinator._async_set_last_user_activity(touched + timedelta(seconds=1))
    assert coordinator.last_user_activity == touched

    coordinator._async_set_last_user_activity(touched + timedelta(minutes=2))
    assert coordinator.last_user_activity == touched + timedelta(minutes=2)
