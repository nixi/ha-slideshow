"""Tests for the live dashboard panel."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from custom_components.slideshow.const import CONF_PANEL_TITLE, DEFAULT_PANEL_TEMPLATE

PATH = "/api/slideshow/panel/test-secret"


async def test_unknown_secret_is_not_found(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The secret is the only thing guarding the panel."""
    client = await hass_client_no_auth()
    assert (await client.get("/api/slideshow/panel/wrong-secret")).status == 404
    assert (await client.get("/api/slideshow/panel/wrong-secret/events")).status == 404


async def test_page_is_served_without_authentication(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The player has no Home Assistant session, so the page must not need one."""
    client = await hass_client_no_auth()
    response = await client.get(PATH)

    assert response.status == 200
    body = await response.text()
    # The shell owns the theme, so a template can never render invisibly the
    # way sent HTML can.
    assert "text/html" in response.headers["Content-Type"]
    assert "--fg: #ffffff" in body
    assert "EventSource" in body


async def test_events_stream_renders_the_template(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The stream pushes rendered markup, not raw template text."""
    coordinator = init_integration.runtime_data
    coordinator.panel.last_html = "<div>hello</div>"

    client = await hass_client_no_auth()
    response = await client.get(f"{PATH}/events")
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")

    chunk = await response.content.readuntil(b"\n\n")
    payload = chunk.decode().removeprefix("data: ").strip()
    assert json.loads(payload) == "<div>hello</div>"
    response.close()


async def test_url_file_is_served_for_the_player(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """SlideShow shows a web page by playing a file holding its address."""
    hass.config.internal_url = "http://10.0.0.5:8123"
    client = await hass_client_no_auth()

    response = await client.get(f"{PATH}/url")
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert (await response.text()).strip() == (
        "http://10.0.0.5:8123/api/slideshow/panel/test-secret"
    )


async def test_url_file_needs_the_right_secret(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The .url endpoint is guarded by the same secret as the panel."""
    client = await hass_client_no_auth()
    assert (await client.get("/api/slideshow/panel/nope/url")).status == 404


HOSTILE = '<img src=x onerror="alert(1)">'

# Every entity the shipped default and the docs example read, so a hostile
# value reaches each text interpolation. Values the templates do arithmetic on
# stay numeric, as they would be from a real integration.
_HOSTILE_STATES = {
    "weather.home": {"temperature": 21.5, "humidity": HOSTILE},
    "sensor.outside_temperature": {},
    "sensor.living_room_temperature": {"unit_of_measurement": HOSTILE},
    "sensor.hallway_temperature": {},
    "sensor.bedroom_temperature": {},
    "sensor.study_temperature": {},
    "sensor.garden_temperature": {},
    "sensor.electricity_price": {"unit_of_measurement": HOSTILE},
    "sensor.departures": {},
    "sensor.bus_stop_departures": {
        "upcoming": [
            {
                "line": HOSTILE,
                "destination": HOSTILE,
                "time_formatted": HOSTILE,
                "minutes_until": HOSTILE,
            }
        ]
    },
    "calendar.home": {"message": HOSTILE, "start_time": "2026-11-05 09:30:00"},
    "calendar.gym": {"message": HOSTILE, "start_time": "2026-11-05 18:00:00"},
    "calendar.school_lunch": {"message": HOSTILE},
    "calendar.waste_collection": {"message": HOSTILE},
    "alarm_control_panel.home": {},
    "lock.front_door": {},
    "lock.garage": {},
    "lock.back_door": {},
    "binary_sensor.any_water_leak": {},
}


@pytest.mark.parametrize(
    "template_str",
    [
        pytest.param(DEFAULT_PANEL_TEMPLATE, id="default"),
        pytest.param(
            (Path(__file__).parent.parent / "docs" / "panel-example.jinja").read_text(),
            id="docs-example",
        ),
    ],
)
async def test_shipped_templates_escape_entity_data(
    hass: HomeAssistant, template_str: str
) -> None:
    """A calendar invite or transit feed must not be able to inject markup."""
    for entity_id, attributes in _HOSTILE_STATES.items():
        hass.states.async_set(entity_id, HOSTILE, attributes)

    rendered = Template(template_str, hass).async_render(parse_result=False)

    assert "<img" not in rendered
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in rendered


async def test_page_pins_its_script_with_a_csp(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """Only the page's own script may run, whatever a template lets through."""
    client = await hass_client_no_auth()
    response = await client.get(PATH)
    body = await response.text()

    csp = response.headers["Content-Security-Policy"]
    script = body.split("<script>", 1)[1].split("</script>", 1)[0]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in csp
    assert "unsafe-inline" not in csp
    assert "object-src 'none'" in csp


async def test_page_title_is_escaped(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The title is an option, but it still must not break out of <title>."""
    hass.config_entries.async_update_entry(
        init_integration,
        options={**init_integration.options, CONF_PANEL_TITLE: "</title><b>x"},
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    body = await (await client.get(PATH)).text()

    assert "<title>&lt;/title&gt;&lt;b&gt;x</title>" in body
