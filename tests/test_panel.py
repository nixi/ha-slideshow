"""Tests for the live dashboard panel."""

import asyncio
import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from custom_components.slideshow.const import CONF_PANEL_TITLE, DEFAULT_PANEL_TEMPLATE
from custom_components.slideshow.panel import (
    _SCRIPT,
    HEARTBEAT_SECONDS,
    PANEL_CSP,
    STALE_MS,
    _page,
    is_shipped_template,
)

from .common import mock_status_reads
from .const import BASE, CONTENT, DEVICE_INFO

PATH = "/api/slideshow/panel/test-secret"


async def test_unknown_secret_is_not_found(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """The secret is the only thing guarding the panel."""
    client = await hass_client_no_auth()
    assert (await client.get("/api/slideshow/panel/wrong-secret")).status == 404
    assert (await client.get("/api/slideshow/panel/wrong-secret/events")).status == 404


@pytest.mark.parametrize("suffix", ["", "/events", "/url"])
async def test_non_ascii_secret_is_not_found(
    hass: HomeAssistant, hass_client_no_auth, init_integration, suffix: str
) -> None:
    """A percent-encoded non-ASCII secret is just a wrong one, not a 500."""
    client = await hass_client_no_auth()
    response = await client.get(f"/api/slideshow/panel/%C3%A9{suffix}")
    assert response.status == 404


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


async def test_empty_render_is_still_sent(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """A template that renders nothing must not leave the page on its placeholder."""
    init_integration.runtime_data.panel.last_html = ""

    client = await hass_client_no_auth()
    response = await client.get(f"{PATH}/events")
    async with asyncio.timeout(2):
        chunk = await response.content.readuntil(b"\n\n")
    assert chunk == b'data: ""\n\n'
    response.close()


async def test_heartbeat_is_an_event_the_page_sees(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """An SSE comment never reaches the page, so the heartbeat is a named event."""
    init_integration.runtime_data.panel.last_html = "<div>hello</div>"
    client = await hass_client_no_auth()
    with patch("custom_components.slideshow.panel.HEARTBEAT_SECONDS", 0.01):
        response = await client.get(f"{PATH}/events")
        async with asyncio.timeout(2):
            await response.content.readuntil(b"\n\n")
            heartbeat = await response.content.readuntil(b"\n\n")
    response.close()

    lines = heartbeat.decode().splitlines()
    assert lines[0] == "event: ping"
    # EventSource dispatches nothing for an event without data.
    assert lines[1].startswith("data: ")
    assert lines[1] != "data: "

    page = await (await client.get(PATH)).text()
    assert "addEventListener('ping'" in page
    assert STALE_MS == HEARTBEAT_SECONDS * 2500
    assert f"setTimeout(stale, {STALE_MS})" in page


async def test_streams_end_when_home_assistant_stops(
    hass: HomeAssistant, hass_client_no_auth, init_integration
) -> None:
    """Entries are not unloaded on stop, so open streams must end by themselves."""
    init_integration.runtime_data.panel.last_html = "<div>hello</div>"
    client = await hass_client_no_auth()
    response = await client.get(f"{PATH}/events")
    async with asyncio.timeout(2):
        await response.content.readuntil(b"\n\n")

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    # Without the stop listener this would wait for the next heartbeat, and
    # the web server would hold the restart for its shutdown timeout.
    async with asyncio.timeout(2):
        assert await response.content.read() == b""
    assert not init_integration.runtime_data.panel._subscribers


async def test_panel_answers_while_the_player_is_not_set_up(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock, mock_config_entry
) -> None:
    """A player that was slow to start must not leave its panel on a 404."""
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", exc=TimeoutError())
    entry = mock_config_entry
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    client = await hass_client_no_auth()
    page = await client.get(PATH)
    assert page.status == 200
    assert "EventSource" in await page.text()
    # The page sees the stream refused and asks again shortly.
    events = await client.get(f"{PATH}/events")
    assert events.status == 503
    # Unknown secrets are still unknown.
    assert (await client.get("/api/slideshow/panel/wrong-secret")).status == 404
    assert (await client.get("/api/slideshow/panel/wrong-secret/events")).status == 404

    # Once the player answers, the stream is there.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/ajax/deviceInfo", json=DEVICE_INFO)
    mock_status_reads(aioclient_mock)
    aioclient_mock.get(
        f"{BASE}/ajax/content/get",
        json={"success": True, "result": {"content": CONTENT}},
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    events = await client.get(f"{PATH}/events")
    assert events.status == 200
    events.close()


# Runs the page's script against a fake EventSource and a virtual clock, to
# check how it reconnects. Prints what happened as JSON.
_SCRIPT_HARNESS = r"""
var now = 0, timers = [], nextId = 1, sources = [];
global.setTimeout = function (fn, ms) {
  var t = {id: nextId++, at: now + ms, fn: fn};
  timers.push(t);
  return t.id;
};
global.clearTimeout = function (id) {
  timers = timers.filter(function (t) { return t.id !== id; });
};
function advance(ms) {
  var end = now + ms;
  for (;;) {
    var due = timers.filter(function (t) { return t.at <= end; });
    if (!due.length) { break; }
    due.sort(function (a, b) { return a.at - b.at; });
    var t = due[0];
    clearTimeout(t.id);
    now = t.at;
    t.fn();
  }
  now = end;
}
function FakeEventSource(url) {
  this.url = url; this.readyState = 0; this.listeners = {}; this.closed = false;
  sources.push(this);
}
FakeEventSource.CONNECTING = 0; FakeEventSource.OPEN = 1;
FakeEventSource.CLOSED = 2;
FakeEventSource.prototype.close = function () {
  this.readyState = 2; this.closed = true;
};
FakeEventSource.prototype.addEventListener = function (type, fn) {
  this.listeners[type] = fn;
};
global.EventSource = FakeEventSource;
var root = {innerHTML: ''}, offline = {hidden: true};
global.document = {getElementById: function (id) {
  return id === 'root' ? root : offline;
}};
global.location = {pathname: '/api/slideshow/panel/s'};

eval(require('fs').readFileSync(0, 'utf8'));

function last() { return sources[sources.length - 1]; }
var out = {};

// Home Assistant restarts: the browser retries on its own and reports an
// error for every failed attempt. None of them may start a second handle.
var es = last();
for (var i = 0; i < 4; i++) { es.readyState = 0; es.onerror(); advance(3000); }
out.duringBrowserRetry = sources.length;
out.offlineDuringOutage = !offline.hidden;
// An HTTP error (503 while the entry is set up) makes the browser give up.
es.readyState = 2; es.onerror(); es.onerror(); es.onerror();
advance(10000);
out.afterClosed = sources.length;

// The new handle works: renders and heartbeats keep it alive.
es = last();
es.readyState = 1; es.onopen();
es.onmessage({data: JSON.stringify('<b>hi</b>')});
out.rendered = root.innerHTML;
out.onlineAfterOpen = offline.hidden;
for (var j = 0; j < 8; j++) { advance(25000); es.listeners.ping({data: '1'}); }
out.afterHeartbeats = sources.length;

// Then nothing arrives, though the browser never sees the connection drop.
advance(__STALE__ + 1);
out.afterSilence = sources.length;
out.offlineAfterSilence = !offline.hidden;
out.oldClosed = es.closed;
out.pendingTimers = timers.length;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_page_reconnects_once_and_notices_a_dead_stream() -> None:
    """One retry at a time, and a stream that only went quiet is replaced."""
    harness = _SCRIPT_HARNESS.replace("__STALE__", str(STALE_MS))
    result = subprocess.run(
        ["node", "-e", harness],
        input=_SCRIPT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    out = json.loads(result.stdout)

    assert out["duringBrowserRetry"] == 1
    assert out["offlineDuringOutage"]
    assert out["afterClosed"] == 2
    assert out["rendered"] == "<b>hi</b>"
    assert out["onlineAfterOpen"]
    assert out["afterHeartbeats"] == 2
    assert out["afterSilence"] == 3
    assert out["offlineAfterSilence"]
    assert out["oldClosed"]
    # Only the new handle's watchdog is left; no stray reconnects pile up.
    assert out["pendingTimers"] == 1


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

    # Case-insensitive: the title filter turns a raw tag into <Img ... Onerror=.
    assert "<img" not in rendered.lower()
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
    # 'unsafe-inline' only helps WebViews too old to know hashes; with a hash
    # present, every browser that knows hashes ignores it.
    assert csp.startswith(f"script-src 'sha256-{digest}' 'unsafe-inline';")
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


OLD_DEFAULT = (
    Path(__file__).parent / "fixtures" / "panel_default_0_9_2.jinja"
).read_text()


def test_earlier_defaults_are_recognised() -> None:
    """A stored copy of an earlier default, however it was saved, is not the user's."""
    assert is_shipped_template(DEFAULT_PANEL_TEMPLATE)
    assert is_shipped_template(OLD_DEFAULT)
    # The UI's text field may hand it back with CRLF line ends or trimmed.
    assert is_shipped_template(OLD_DEFAULT.replace("\n", "\r\n").strip())
    assert is_shipped_template("")
    assert not is_shipped_template(OLD_DEFAULT + "<b>mine</b>")


@pytest.mark.parametrize(
    ("stored", "kept"),
    [
        pytest.param(OLD_DEFAULT, False, id="old-default"),
        pytest.param(DEFAULT_PANEL_TEMPLATE, False, id="current-default"),
        pytest.param("<b>{{ states('sun.sun') | e }}</b>", True, id="custom"),
    ],
)
async def test_setup_drops_a_stored_shipped_default(
    hass: HomeAssistant, mock_device, mock_config_entry, stored: str, kept: bool
) -> None:
    """Entries that saved the old unescaped default move onto the current one."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={"panel_template": stored, CONF_PANEL_TITLE: "Hall"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options[CONF_PANEL_TITLE] == "Hall"
    assert ("panel_template" in entry.options) is kept
    # Template keeps its source stripped.
    rendered_from = entry.runtime_data.panel._template.template
    assert rendered_from == (stored if kept else DEFAULT_PANEL_TEMPLATE).strip()


def _chrome() -> str | None:
    """Return a Chrome or Chromium binary, if one is installed."""
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if found := shutil.which(name):
            return found
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if Path(mac).exists() else None


# A 1x1 PNG.
_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _run_in_chrome(
    renders: list[str],
    *,
    pause: float = 1.5,
    budget: int = 6000,
    fail=None,
    delay: float = 0.0,
    stats: dict | None = None,
) -> tuple[str, list[str]]:
    """Serve the real page shell and return its final #root and image requests.

    The first event stream sends each render ``pause`` seconds apart; later
    reconnects get the last render only. ``/img`` answers a PNG after
    ``delay`` seconds, or 500 when ``fail(path, count)`` says so, where count
    is how often that path (without the ss cache-buster) was asked for
    before. ``stats["max_open"]`` records the most image requests open at
    once.
    """
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests: list[str] = []
    lock = threading.Lock()
    state = {"streams": 0, "open": 0, "max_open": 0}

    def strip(path: str) -> str:
        return re.sub(r"[?&]ss=\d+", "", path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            if self.path.startswith("/img"):
                with lock:
                    state["open"] += 1
                    state["max_open"] = max(state["max_open"], state["open"])
                try:
                    self._image()
                finally:
                    with lock:
                        state["open"] -= 1
            elif self.path.endswith("/events"):
                self._events()
            else:
                body = _page("t").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Security-Policy", PANEL_CSP)
                self.end_headers()
                self.wfile.write(body)

        def _image(self) -> None:
            key = strip(self.path)
            with lock:
                count = sum(strip(r) == key for r in requests)
                requests.append(self.path)
            time.sleep(delay)
            if fail and fail(key, count):
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_PIXEL)))
            self.end_headers()
            self.wfile.write(_PIXEL)

        def _events(self) -> None:
            with lock:
                state["streams"] += 1
                first = state["streams"] == 1
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for n, html in enumerate(renders if first else renders[-1:]):
                if n:
                    time.sleep(pause)
                self.wfile.write(f"data: {json.dumps(html)}\n\n".encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                _chrome(),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                f"--virtual-time-budget={budget}",
                "--dump-dom",
                f"http://127.0.0.1:{server.server_address[1]}/api/slideshow/panel/s",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    if stats is not None:
        stats["max_open"] = state["max_open"]
    match = re.search(
        r'<div id="root">(.*?)</div>\s*<div id="offline"', result.stdout, re.S
    )
    return (match.group(1) if match else result.stdout), requests


needs_chrome = [
    pytest.mark.enable_socket,
    pytest.mark.skipif(_chrome() is None, reason="needs Chrome"),
]


@pytest.mark.parametrize("_", [None], ids=["chrome"])
@needs_chrome[0]
@needs_chrome[1]
def test_page_patches_renders_and_refreshes_images(_) -> None:
    """In a real browser, renders are patched in and images refresh.

    A render changes only what differs, and an image marked data-ss-src is
    fetched again and again, following a new token.
    """
    image = '<img id="cam" data-ss-src="/img?token={}" data-ss-refresh="0.5">'
    root, requests = _run_in_chrome(
        [
            '<p id="a">one</p>' + image.format("A"),
            '<p id="a">two</p>' + image.format("B"),
        ],
        pause=0,
    )

    assert '<p id="a">two</p>' in root
    # The image carries the src the page set, with the new token.
    assert re.search(r'<img id="cam"[^>]* src="[^"]*/img\?token=B&amp;ss=\d+"', root)
    assert len([r for r in requests if "token=B" in r]) >= 2, requests
    assert all("&ss=" in r for r in requests)


@needs_chrome[0]
@needs_chrome[1]
def test_page_never_shows_one_camera_under_another() -> None:
    """When a camera block goes away, the next one does not inherit its picture."""
    root, _ = _run_in_chrome(
        [
            '<h2>Front</h2><img data-ss-src="/img?cam=front">'
            '<h2>Garage</h2><img data-ss-src="/img?cam=garage">',
            '<h2>Garage</h2><img data-ss-src="/img?cam=garage">',
        ],
        fail=lambda path, count: "garage" in path,
    )

    assert "<h2>Garage</h2>" in root
    assert "cam=front" not in root


@needs_chrome[0]
@needs_chrome[1]
def test_page_keeps_a_moved_images_last_picture() -> None:
    """An image shifted by new content shows its last still, not a blank."""
    root, requests = _run_in_chrome(
        [
            '<img id="cam" data-ss-src="/img?cam=a">',
            '<p>banner</p><img id="cam" data-ss-src="/img?cam=a">',
        ],
        # The first still loads; every later request fails.
        fail=lambda path, count: count > 0,
    )

    assert "<p>banner</p>" in root
    assert re.search(r'<img id="cam"[^>]* src="[^"]*/img\?cam=a&amp;ss=\d+"', root), (
        root,
        requests,
    )


@needs_chrome[0]
@needs_chrome[1]
def test_page_survives_markup_named_like_a_dom_method() -> None:
    """A named element cannot shadow what the page needs to patch."""
    root, _ = _run_in_chrome(
        [
            '<p id="a">one</p><img name="importNode" alt="">',
            '<p id="a">two</p><img name="importNode" alt=""><p id="b">added</p>',
        ]
    )

    assert '<p id="a">two</p>' in root
    assert '<p id="b">added</p>' in root


@needs_chrome[0]
@needs_chrome[1]
def test_page_refreshes_an_image_with_a_fragment() -> None:
    """The cache-buster goes before a #fragment, or nothing would change."""
    _, requests = _run_in_chrome(
        ['<img data-ss-src="/img?cam=f#x" data-ss-refresh="0.3">'], budget=4000
    )

    assert len(requests) >= 2, requests
    assert all(re.search(r"cam=f&ss=\d+$", r) for r in requests), requests


@needs_chrome[0]
@needs_chrome[1]
def test_page_retries_a_failed_image() -> None:
    """A still that failed is fetched again, even without data-ss-refresh."""
    root, requests = _run_in_chrome(
        ['<img id="cam" data-ss-src="/img?cam=r">'],
        budget=15000,
        fail=lambda path, count: count == 0,
    )

    assert len(requests) >= 2, requests
    assert re.search(r'<img id="cam"[^>]* src="[^"]*/img\?cam=r&amp;ss=\d+"', root)


@needs_chrome[0]
@needs_chrome[1]
@pytest.mark.parametrize(
    "extra",
    [
        pytest.param("<p>alert</p>", id="shifted"),
        # An attribute name setAttribute rejects sends every render down the
        # innerHTML fallback, which makes every element anew.
        pytest.param('<p =x="{n}">alert</p>', id="fallback"),
    ],
)
def test_page_keeps_a_camera_alive_through_fast_renders(extra: str) -> None:
    """A camera recreated faster than it answers keeps updating.

    Neither the shifted element nor the innerHTML fallback may freeze it or
    open a second request for it.
    """
    image = '<img id="cam" data-ss-src="/img?cam=a" data-ss-refresh="0.3">'
    renders = [
        (extra.format(n=n) if n % 2 else "") + f'<p id="n">{n}</p>' + image
        for n in range(8)
    ]
    stats: dict = {}
    root, requests = _run_in_chrome(
        renders, pause=0.2, delay=0.3, budget=4000, stats=stats
    )

    assert '<p id="n">7</p>' in root
    assert re.search(r'<img id="cam"[^>]* src="[^"]*/img\?cam=a&amp;ss=\d+"', root), (
        root,
        requests,
    )
    assert stats["max_open"] == 1, requests


@needs_chrome[0]
@needs_chrome[1]
def test_page_updates_a_form_whose_control_shadows_dom_properties() -> None:
    """A control named childNodes cannot hide a form's new contents."""
    form = '<form class="c{0}"><input name="childNodes"><span>{1}</span></form>'
    root, _ = _run_in_chrome([form.format(0, "old"), form.format(1, "new")], pause=0.5)

    assert '<form class="c1">' in root
    assert "<span>new</span>" in root
