"""Fixtures for the SlideShow tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.slideshow.const import DOMAIN

from .const import BASE, CONTENT, DEVICE_INFO, USER_INPUT


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make the custom integration loadable in tests."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured entry for the player."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Frame",
        unique_id=DEVICE_INFO["deviceId"],
        data={**USER_INPUT, "panel_secret": "test-secret"},
    )


@pytest.fixture
def mock_device(aioclient_mock) -> None:
    """Answer the endpoints polled during setup."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    return aioclient_mock


@pytest.fixture
def bypass_panel() -> Generator[None]:
    """Skip template tracking, which needs a rendering environment."""
    with patch(
        "custom_components.slideshow.PanelRenderer.async_start",
        return_value=None,
    ):
        yield


@pytest.fixture
async def init_integration(hass, aioclient_mock, mock_config_entry) -> MockConfigEntry:
    """Set the integration up against a mocked player."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
