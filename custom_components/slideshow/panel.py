"""A live dashboard page served by Home Assistant for a SlideShow player.

The player's browser has no Home Assistant session, so a Lovelace dashboard
would demand a login. Instead this serves a small page of its own on an
unauthenticated but unguessable URL, renders the user's Jinja template *inside*
Home Assistant — where it already has full access to state, so no token is
handed to the player — and streams re-renders to the page over server-sent
events. The page swaps its own markup, so there is no reload and no flicker,
and the player can hold it as an ordinary playlist item.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import http
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_template_result,
)
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.template import Template

from .const import CONF_PANEL_SECRET, CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE, DOMAIN

if TYPE_CHECKING:
    from .coordinator import SlideshowConfigEntry

_LOGGER = logging.getLogger(__name__)

PANEL_URL = "/api/slideshow/panel/{secret}"
EVENTS_URL = "/api/slideshow/panel/{secret}/events"
URL_FILE_URL = "/api/slideshow/panel/{secret}/url"

_VIEWS_REGISTERED = f"{DOMAIN}_panel_views"

# Sent as an SSE comment so proxies and the player's browser keep the
# connection open during quiet periods.
HEARTBEAT_SECONDS = 25

# A slow player should not be able to pin memory by opening streams it never
# reads; drop the oldest queued render instead of growing without bound.
QUEUE_SIZE = 4


class PanelRenderer:
    """Render one config entry's template and fan results out to viewers."""

    def __init__(
        self, hass: HomeAssistant, entry: SlideshowConfigEntry, template_str: str
    ) -> None:
        """Initialise the renderer."""
        self.hass = hass
        self.entry = entry
        self._template = Template(template_str, hass)
        self._subscribers: set[asyncio.Queue[str | None]] = set()
        self._unsub: Any = None
        self.last_html: str = ""

    @property
    def title(self) -> str:
        """Return the page title."""
        return self.entry.options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE)

    async def async_start(self) -> None:
        """Begin tracking the template."""
        info = async_track_template_result(
            self.hass,
            [TrackTemplate(self._template, None)],
            self._async_on_result,
        )
        self._unsub = info
        # Renders once immediately so the first viewer has something to show.
        info.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Stop tracking and disconnect every viewer."""
        if self._unsub is not None:
            self._unsub.async_remove()
            self._unsub = None
        for queue in list(self._subscribers):
            self._publish(queue, None)
        self._subscribers.clear()

    @callback
    def _async_on_result(
        self,
        event: Event | None,
        updates: list[TrackTemplateResult],
    ) -> None:
        """Handle a new render of the template."""
        for update in updates:
            result = update.result
            if isinstance(result, TemplateError):
                _LOGGER.error("SlideShow panel template failed: %s", result)
                self.last_html = _error_markup(str(result))
            else:
                self.last_html = str(result)
        for queue in list(self._subscribers):
            self._publish(queue, self.last_html)

    @callback
    def _publish(self, queue: asyncio.Queue[str | None], item: str | None) -> None:
        """Put an item on a viewer's queue, dropping the oldest if it is full."""
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(item)

    @callback
    def async_subscribe(self) -> asyncio.Queue[str | None]:
        """Register a viewer and return its queue, primed with the last render."""
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        if self.last_html:
            self._publish(queue, self.last_html)
        return queue

    @callback
    def async_unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        """Remove a viewer."""
        self._subscribers.discard(queue)


def _error_markup(message: str) -> str:
    """Return markup shown on the display when the template cannot render."""
    safe = (
        message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        '<div class="ss-error"><h1>Template error</h1>'
        f"<pre>{safe}</pre></div>"
    )


def _find_renderer(hass: HomeAssistant, secret: str) -> PanelRenderer | None:
    """Return the renderer whose entry owns this secret."""
    if not secret:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        # Compared in constant time: the secret is the only thing guarding
        # these endpoints.
        expected = entry.data.get(CONF_PANEL_SECRET, "")
        if expected and _constant_time_equal(expected, secret):
            coordinator = getattr(entry, "runtime_data", None)
            return getattr(coordinator, "panel", None)
    return None


def _constant_time_equal(left: str, right: str) -> bool:
    """Compare two secrets without leaking their contents through timing."""
    return hmac.compare_digest(left, right)


class SlideshowPanelView(http.HomeAssistantView):
    """Serve the dashboard page itself."""

    url = PANEL_URL
    name = "api:slideshow:panel"
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.StreamResponse:
        """Return the page shell."""
        hass = request.app[http.KEY_HASS]
        renderer = _find_renderer(hass, secret)
        if renderer is None:
            return web.Response(status=404, text="Unknown panel")
        return web.Response(
            text=_page(renderer.title),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )


class SlideshowPanelEventsView(http.HomeAssistantView):
    """Stream re-renders to the page."""

    url = EVENTS_URL
    name = "api:slideshow:panel:events"
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.StreamResponse:
        """Stream server-sent events until the viewer goes away."""
        hass = request.app[http.KEY_HASS]
        renderer = _find_renderer(hass, secret)
        if renderer is None:
            return web.Response(status=404, text="Unknown panel")

        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-store",
                # aiohttp manages Connection itself; this is the conventional
                # hint for any reverse proxy sitting in between.
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)

        queue = renderer.async_subscribe()
        try:
            while True:
                try:
                    html = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    await response.write(b": ping\n\n")
                    continue
                if html is None:
                    break
                payload = json.dumps(html)
                await response.write(f"data: {payload}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            renderer.async_unsubscribe(queue)
        return response


class SlideshowPanelUrlFileView(http.HomeAssistantView):
    """Serve the panel address as a .url file for the player to download.

    SlideShow shows a web page by playing a text file containing its address,
    and the API offers no way to upload files -- but it can be told to
    synchronize one from a URL, so Home Assistant serves that file itself.
    """

    url = URL_FILE_URL
    name = "api:slideshow:panel:url"
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.StreamResponse:
        """Return a one-line file holding the panel address."""
        hass = request.app[http.KEY_HASS]
        if _find_renderer(hass, secret) is None:
            return web.Response(status=404, text="Unknown panel")
        try:
            base = get_url(hass, allow_external=False, allow_cloud=False)
        except NoURLAvailableError:
            try:
                base = get_url(hass, allow_cloud=False)
            except NoURLAvailableError:
                return web.Response(status=503, text="No Home Assistant URL is known")
        return web.Response(
            text=f"{base}{panel_path(secret)}\n",
            content_type="text/plain",
            headers={"Cache-Control": "no-store"},
        )


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Register the panel views once for the whole integration."""
    if hass.data.get(_VIEWS_REGISTERED):
        return
    hass.http.register_view(SlideshowPanelView())
    hass.http.register_view(SlideshowPanelEventsView())
    hass.http.register_view(SlideshowPanelUrlFileView())
    hass.data[_VIEWS_REGISTERED] = True


def panel_path(secret: str) -> str:
    """Return the path the player should load."""
    return PANEL_URL.format(secret=secret)


def panel_url_file_path(secret: str) -> str:
    """Return the path serving the .url file for the player to download."""
    return URL_FILE_URL.format(secret=secret)


def _page(title: str) -> str:
    """Return the page shell.

    The shell owns the theme and layout so a template only has to emit
    content, and so an unstyled template can never come out as black text on a
    black background the way sent HTML does.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #0d1b24; --bg2: #14293a; --fg: #ffffff; --muted: rgba(255,255,255,.62);
    --card: rgba(255,255,255,.07); --line: rgba(255,255,255,.12);
    --ok: #4ade80; --warn: #fbbf24; --bad: #f87171;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}
  body {{
    background: linear-gradient(140deg, var(--bg), var(--bg2));
    color: var(--fg);
    font-family: -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 2.2vh; line-height: 1.3; overflow: hidden;
  }}
  #root {{ height: 100%; padding: 3vh 3vw; }}
  h1, h2, h3 {{ margin: 0; font-weight: 500; }}
  .ss-grid {{ display: grid; gap: 2.4vh; height: 100%; }}
  .ss-row {{ display: flex; gap: 2vw; align-items: stretch; }}
  .ss-card {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 1.6vh; padding: 2vh 2vw; flex: 1; min-width: 0;
  }}
  .ss-label {{ color: var(--muted); font-size: 1.9vh; text-transform: uppercase;
               letter-spacing: .08em; }}
  .ss-big {{ font-size: 9vh; font-weight: 300; line-height: 1; }}
  .ss-mid {{ font-size: 4vh; font-weight: 300; }}
  .ss-muted {{ color: var(--muted); }}
  .ss-ok {{ color: var(--ok); }} .ss-warn {{ color: var(--warn); }}
  .ss-bad {{ color: var(--bad); }}
  .ss-list {{ list-style: none; margin: 0; padding: 0; }}
  .ss-list li {{ display: flex; justify-content: space-between; gap: 1vw;
                 padding: .7vh 0; border-bottom: 1px solid var(--line); }}
  .ss-list li:last-child {{ border-bottom: 0; }}
  .ss-error {{ padding: 4vh; color: var(--bad); }}
  .ss-error pre {{ white-space: pre-wrap; color: var(--fg); font-size: 1.8vh; }}
  #offline {{
    position: fixed; top: 1.4vh; right: 1.4vw; padding: .5vh 1vw;
    border-radius: 1vh; background: var(--bad); color: #000;
    font-size: 1.7vh; opacity: .92;
  }}
  #offline[hidden] {{ display: none; }}
</style>
</head>
<body>
<div id="root"><div class="ss-error">Waiting for Home Assistant…</div></div>
<div id="offline" hidden>Disconnected</div>
<script>
(function () {{
  var root = document.getElementById('root');
  var offline = document.getElementById('offline');
  var src = null;

  function connect() {{
    if (src) {{ src.close(); }}
    src = new EventSource(location.pathname.replace(/\\/$/, '') + '/events');
    src.onmessage = function (e) {{
      offline.hidden = true;
      try {{ root.innerHTML = JSON.parse(e.data); }} catch (err) {{}}
    }};
    src.onopen = function () {{ offline.hidden = true; }};
    src.onerror = function () {{
      offline.hidden = false;
      // EventSource retries on its own, but a player that has been asleep can
      // end up with a dead handle, so replace it after a pause.
      setTimeout(connect, 10000);
    }};
  }}
  connect();
}})();
</script>
</body>
</html>
"""
