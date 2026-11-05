"""Tests for the SlideShow config flow."""

import re
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components import slideshow
from custom_components.slideshow.api import SlideshowAuthError
from custom_components.slideshow.const import DEFAULT_PANEL_TEMPLATE, DOMAIN

from .const import BASE, DEVICE_INFO, HOST, USER_INPUT


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
        # Something other than SlideShow answers at the address.
        ({"status": 404}, "cannot_connect"),
        ({"text": "<html>Router login</html>"}, "cannot_connect"),
        ({"content": b"\xff\xfe\x00"}, "cannot_connect"),
        ({"json": ["not", "an", "object"]}, "cannot_connect"),
        (
            {"status": 301, "headers": {"Location": "https://192.0.2.10/"}},
            "cannot_connect",
        ),
        ({"status": 405}, "cannot_connect"),
        ({"status": 500, "content": b"\xff\xd8 binary"}, "cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock,
    caplog: pytest.LogCaptureFixture,
    mock_kwargs: dict,
    expected: str,
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
    # A wrong address is the user's to fix, not an unexpected error.
    assert "Traceback" not in caplog.text


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


async def test_options_flow_does_not_store_the_default_template(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Saving the pre-filled default must not pin the entry to that copy."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 60,
            "screen_off_layout": "Screen off",
            "panel_title": "Hall",
            "panel_template": DEFAULT_PANEL_TEMPLATE.replace("\n", "\r\n"),
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "panel_template" not in init_integration.options
    assert init_integration.options["scan_interval"] == 60


async def test_reconfigure_to_a_non_slideshow_address(
    hass: HomeAssistant,
    aioclient_mock,
    caplog: pytest.LogCaptureFixture,
    mock_config_entry,
) -> None:
    """A host answering 404 is a wrong address, not an unexpected error."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(re.compile(r"/ajax/deviceInfo"), status=404)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "192.0.2.99", "port": 80, "ssl": False, "verify_ssl": False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Traceback" not in caplog.text


async def test_reauth_against_a_non_slideshow_answer(
    hass: HomeAssistant,
    aioclient_mock,
    caplog: pytest.LogCaptureFixture,
    mock_config_entry,
) -> None:
    """A page that is not JSON is reported as an address problem."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", text="<html>Not here</html>")

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "admin", "password": "admin"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert "Traceback" not in caplog.text


async def test_options_flow_rejects_a_broken_template(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A template that does not compile is flagged on the form, not saved.

    Saved, it would replace the panel on every player with an error.
    """
    broken = "{% for x in [1, 2] %}{{ x }}"
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 60,
            "screen_off_layout": "Screen off",
            "panel_title": "Hall",
            "panel_template": broken,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"panel_template": "invalid_template"}
    assert "panel_template" not in init_integration.options
    # What was typed is kept on the form, to be corrected.
    fields = {str(key): key for key in result["data_schema"].schema}
    assert fields["panel_template"].default() == broken
    assert fields["panel_title"].default() == "Hall"


async def test_saving_options_reloads_once(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """Changed options take effect at once, with a single reload."""
    with patch(
        "custom_components.slideshow.async_setup_entry",
        wraps=slideshow.async_setup_entry,
    ) as setup:
        result = await hass.config_entries.options.async_init(init_integration.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "scan_interval": 45,
                "screen_off_layout": "Screen off",
                "panel_title": "Hall",
                "panel_template": "<b>hi</b>",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup.call_count == 1
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.update_interval.total_seconds() == 45


async def test_reconfigure_reloads_once(
    hass: HomeAssistant, aioclient_mock, init_integration
) -> None:
    """A changed setting is picked up by one reload, not two."""
    with patch(
        "custom_components.slideshow.async_setup_entry",
        wraps=slideshow.async_setup_entry,
    ) as setup:
        result = await init_integration.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": HOST, "port": 8080, "ssl": False, "verify_ssl": True},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert setup.call_count == 1
