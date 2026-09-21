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
