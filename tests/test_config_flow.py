"""Tests for the SlideShow config flow."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.slideshow.api import SlideshowAuthError
from custom_components.slideshow.const import DOMAIN

from .const import BASE, DEVICE_INFO, USER_INPUT


async def test_user_flow_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    """A reachable player is added and identified by its device ID."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.slideshow.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Frame"
    assert result["result"].unique_id == DEVICE_INFO["deviceId"]


@pytest.mark.parametrize(
    ("mock_kwargs", "expected"),
    [
        ({"status": 303, "headers": {"Location": "/login"}}, "invalid_auth"),
        ({"status": 401}, "invalid_auth"),
        ({"exc": TimeoutError()}, "cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, aioclient_mock, mock_kwargs: dict, expected: str
) -> None:
    """Failures are reported on the form rather than raising."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", **mock_kwargs)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_duplicate_player_is_rejected(
    hass: HomeAssistant, aioclient_mock, mock_config_entry
) -> None:
    """The same player cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_resolves_itself_when_the_player_recovers(
    hass: HomeAssistant, aioclient_mock, mock_config_entry
) -> None:
    """A player that only stumbled should not make anyone retype a password."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)

    result = await mock_config_entry.start_reauth_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "admin"


async def test_reauth_asks_when_the_credentials_really_changed(
    hass: HomeAssistant, aioclient_mock, mock_config_entry
) -> None:
    """A genuine rejection still prompts, and stores what is entered."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)

    # The stored credentials are refused; the new ones are accepted.
    with patch(
        "custom_components.slideshow.config_flow._async_validate",
        side_effect=[SlideshowAuthError("nope"), DEVICE_INFO],
    ):
        result = await mock_config_entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"

        with patch("custom_components.slideshow.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"username": "admin", "password": "a-new-password"}
            )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["password"] == "a-new-password"


async def test_options_flow_stores_the_panel_template(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """The panel template and screen-off layout are editable in the UI."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 60,
            "screen_off_layout": "Skärm av",
            "panel_title": "Hall",
            "panel_template": "<b>hi</b>",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options["panel_template"] == "<b>hi</b>"
    assert init_integration.options["screen_off_layout"] == "Skärm av"
