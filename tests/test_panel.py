"""Tests for the live dashboard panel."""

import json

from homeassistant.core import HomeAssistant

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
