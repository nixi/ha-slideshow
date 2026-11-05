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
import base64
import contextlib
import hashlib
import hmac
import html
import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import http
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_template_result,
)
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.template import Template

from .const import (
    CONF_PANEL_SECRET,
    CONF_PANEL_TITLE,
    DEFAULT_PANEL_TEMPLATE,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    PREVIOUS_DEFAULT_PANEL_TEMPLATE_HASHES,
)

if TYPE_CHECKING:
    from .coordinator import SlideshowConfigEntry

_LOGGER = logging.getLogger(__name__)

PANEL_URL = "/api/slideshow/panel/{secret}"
EVENTS_URL = "/api/slideshow/panel/{secret}/events"
URL_FILE_URL = "/api/slideshow/panel/{secret}/url"

_VIEWS_REGISTERED = f"{DOMAIN}_panel_views"

NO_URL_MESSAGE = (
    "Home Assistant does not know its own address. Set the internal URL under "
    "Settings, System, Network."
)

# Sent as a "ping" event during quiet periods. It keeps proxies from closing
# the connection, and lets the page notice a stream that died without a word.
HEARTBEAT_SECONDS = 25
HEARTBEAT = b"event: ping\ndata: 1\n\n"

# How long the page waits without a render or a heartbeat before it treats the
# stream as dead: a few missed heartbeats, not one late one.
STALE_MS = int(HEARTBEAT_SECONDS * 2.5 * 1000)

# The page's only script. Templates are inserted with innerHTML, so the CSP
# below pins script execution to exactly this block by its hash: markup that
# slips through a template unescaped (an <img onerror=...> in a calendar title,
# say) cannot run script on the Home Assistant origin. ES5 only: players run
# old Android WebViews.
_SCRIPT = """
(function () {
  var root = document.getElementById('root');
  var offline = document.getElementById('offline');
  var src = null;
  var retry = null;
  var watchdog = null;
  var refresher = null;
  // Captured before any template markup exists: a named element in a render
  // (<img name="importNode">) would otherwise shadow document.importNode.
  var importNode = typeof Document === 'undefined' ? null
                                                  : Document.prototype.importNode;
  // Timing that a change of the wall clock cannot freeze.
  var clock = typeof performance !== 'undefined' && performance.now
    ? function () { return performance.now(); }
    : function () { return new Date().getTime(); };
  // One loader per picture source, so its state outlives the elements that
  // show it: an element that is replaced keeps the last still and the load
  // already under way.
  var loaders = {};

  // What a refreshing image shows: its address without the token or
  // signature Home Assistant rotates, so a camera whose token changes is
  // still the same camera, while two cameras never are.
  function source(el) {
    var url = el.getAttribute && el.getAttribute('data-ss-src');
    if (url === null || url === undefined) { return null; }
    return url.split('#')[0]
      .replace(/([?&])(token|authSig)=[^&]*/g, '$1')
      .replace(/&&+/g, '&').replace(/[?]&/, '?').replace(/[?&]$/, '');
  }

  // Bring the live markup in line with a new render, changing only what
  // differs. Untouched elements stay, so an image is not fetched again and
  // nothing flickers when one value changes.
  function patch(live, next) {
    var have = live.childNodes, want = next.childNodes, i, a, b;
    for (i = 0; i < want.length; i++) {
      a = have[i]; b = want[i];
      if (!a) {
        live.appendChild(importNode.call(document, b, true));
      } else if (a.nodeType !== b.nodeType || a.nodeName !== b.nodeName ||
                 a.nodeName === 'FORM' ||
                 (a.nodeType === 1 && source(a) !== source(b))) {
        // A form is replaced whole, since a control named like a DOM
        // property (childNodes, attributes) would hide its contents. A
        // refreshing image that now shows something else is replaced, so
        // the previous picture can never linger under the new one.
        live.replaceChild(importNode.call(document, b, true), a);
      } else if (a.nodeType === 1) {
        attributes(a, b);
        patch(a, b);
      } else if (a.nodeValue !== b.nodeValue) {
        a.nodeValue = b.nodeValue;
      }
    }
    while (have.length > want.length) { live.removeChild(live.lastChild); }
  }

  function attributes(a, b) {
    // A refreshing image's src belongs to this script, not the template.
    var own = source(a) !== null, i, at;
    for (i = a.attributes.length - 1; i >= 0; i--) {
      at = a.attributes[i];
      if (own && at.name === 'src') { continue; }
      if (at.namespaceURI ? !b.hasAttributeNS(at.namespaceURI, at.localName)
                          : !b.hasAttribute(at.name)) {
        if (at.namespaceURI) { a.removeAttributeNS(at.namespaceURI, at.localName); }
        else { a.removeAttribute(at.name); }
      }
    }
    for (i = 0; i < b.attributes.length; i++) {
      at = b.attributes[i];
      if (own && at.name === 'src') { continue; }
      if (at.namespaceURI) {
        if (a.getAttributeNS(at.namespaceURI, at.localName) !== at.value) {
          a.setAttributeNS(at.namespaceURI, at.name, at.value);
        }
      } else if (a.getAttribute(at.name) !== at.value) {
        a.setAttribute(at.name, at.value);
      }
    }
  }

  function refreshing() {
    return root.querySelectorAll ? root.querySelectorAll('img[data-ss-src]') : [];
  }

  function render(html) {
    try {
      var doc = new DOMParser().parseFromString(
        '<!doctype html><body>' + html, 'text/html');
      patch(root, doc.body);
    } catch (err) {
      // No DOMParser, or markup this browser cannot patch: start over.
      root.innerHTML = html;
    }
    refresh();
  }

  // <img data-ss-src="..." data-ss-refresh="2"> shows a still image and
  // fetches a fresh one every 2 seconds: the way to show a camera, since
  // older WebViews neither draw an MJPEG stream nor let go of it. The next
  // picture loads off-screen and is swapped in once complete. A source has
  // at most one request open; one that hangs is abandoned after 30 seconds,
  // a failed one is tried again after 10, and one no longer on the page is
  // dropped.
  function refresh() {
    clearTimeout(refresher);
    refresher = null;
    var list = refreshing(), now = clock(), seen = {}, i, img, key, l, wait;
    for (i = 0; i < list.length; i++) {
      img = list[i];
      key = source(img);
      l = loaders[key];
      if (!l) {
        l = loaders[key] = {next: null, started: 0, at: 0, failed: false,
                            src: null, base: null, url: null, every: 0};
      }
      if (!seen[key]) {
        seen[key] = true;
        l.url = img.getAttribute('data-ss-src');
        l.every = (parseFloat(img.getAttribute('data-ss-refresh')) || 0) * 1000;
      }
      if (l.src && img.getAttribute('src') !== l.src) {
        img.setAttribute('src', l.src);
      }
    }
    for (key in loaders) {
      if (!loaders.hasOwnProperty(key)) { continue; }
      l = loaders[key];
      if (!seen[key]) {
        abandon(l);
        delete loaders[key];
        continue;
      }
      if (l.next) {
        if (now - l.started < 30000) { continue; }
        abandon(l);
        l.failed = true;
      }
      wait = l.failed ? (l.every > 0 ? Math.min(l.every, 10000) : 10000) : l.every;
      if (l.base !== l.url || (wait > 0 && now - l.at >= wait)) { load(key, l, now); }
    }
    if (list.length) { refresher = setTimeout(refresh, 250); }
  }

  function abandon(l) {
    if (!l.next) { return; }
    l.next.onload = l.next.onerror = null;
    l.next.src = '';
    l.next = null;
  }

  function load(key, l, now) {
    var url = l.url, cut = url.indexOf('#'), tail = '', next = new Image();
    if (cut >= 0) { tail = url.slice(cut); url = url.slice(0, cut); }
    l.next = next;
    l.started = now;
    l.base = l.url;
    function done(ok) {
      if (l.next !== next) { return; }
      l.next = null;
      l.at = clock();
      l.failed = !ok;
      if (!ok) { return; }
      l.src = next.src;
      var list = refreshing(), i;
      for (i = 0; i < list.length; i++) {
        if (source(list[i]) === key) { list[i].setAttribute('src', l.src); }
      }
    }
    next.onload = function () { done(true); };
    next.onerror = function () { done(false); };
    next.src = url + (url.indexOf('?') < 0 ? '?' : '&') + 'ss=' +
      new Date().getTime() + tail;
  }

  function watch() {
    clearTimeout(watchdog);
    watchdog = setTimeout(stale, __STALE_MS__);
  }

  // A render or a heartbeat arrived, so the stream is alive.
  function alive() {
    offline.hidden = true;
    watch();
  }

  // Nothing at all for several heartbeats: Home Assistant went away without
  // closing the connection (a power cut, say), so the browser never noticed.
  function stale() {
    offline.hidden = false;
    connect();
  }

  function connect() {
    clearTimeout(retry);
    retry = null;
    if (src) { src.close(); }
    var es = new EventSource(location.pathname.replace(/\\/$/, '') + '/events');
    src = es;
    watch();
    es.onopen = alive;
    es.onmessage = function (e) {
      alive();
      try { render(JSON.parse(e.data)); } catch (err) {}
    };
    es.addEventListener('ping', alive);
    es.onerror = function () {
      if (es !== src) { return; }
      offline.hidden = false;
      // While the browser retries on its own it is CONNECTING; leave that to
      // it. It gives up (CLOSED) on an HTTP error, such as the 503 sent while
      // the player is still being set up, so then try once more after a pause.
      if (es.readyState === EventSource.CLOSED && retry === null) {
        retry = setTimeout(connect, 10000);
      }
    };
  }
  connect();
})();
""".replace("__STALE_MS__", str(STALE_MS))
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
# 'unsafe-inline' is only for WebViews too old to know hash sources, which
# would otherwise block the page's own script. Any browser that knows them
# ignores 'unsafe-inline' when a hash is present.
PANEL_CSP = (
    f"script-src 'sha256-{_SCRIPT_HASH}' 'unsafe-inline'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)

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
        # None until the first render; an empty render is still sent.
        self.last_html: str | None = None

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
        self.async_disconnect_viewers()

    @callback
    def async_disconnect_viewers(self) -> None:
        """End every open stream; the pages reconnect on their own."""
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
        if self.last_html is not None:
            self._publish(queue, self.last_html)
        return queue

    @callback
    def async_unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        """Remove a viewer."""
        self._subscribers.discard(queue)


def is_shipped_template(template: str) -> bool:
    """Return whether a template is the current or an earlier shipped default.

    Such a template is not the user's own work, so it is not stored: the panel
    then follows the default, and fixes to it reach every player.
    """
    text = template.replace("\r\n", "\n").strip()
    if not text or text == DEFAULT_PANEL_TEMPLATE.strip():
        return True
    digest = hashlib.sha256(text.encode()).hexdigest()
    return digest in PREVIOUS_DEFAULT_PANEL_TEMPLATE_HASHES


def _error_markup(message: str) -> str:
    """Return markup shown on the display when the template cannot render."""
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<div class="ss-error"><h1>Template error</h1><pre>{safe}</pre></div>'


def _find_entry(hass: HomeAssistant, secret: str) -> ConfigEntry | None:
    """Return the entry that owns this secret, whether it is loaded or not."""
    if not secret:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        # Compared in constant time: the secret is the only thing guarding
        # these endpoints.
        expected = entry.data.get(CONF_PANEL_SECRET, "")
        if expected and _constant_time_equal(expected, secret):
            return entry
    return None


def _renderer(entry: ConfigEntry) -> PanelRenderer | None:
    """Return the entry's renderer, or None while the entry is not loaded."""
    if entry.state is not ConfigEntryState.LOADED:
        return None
    return getattr(getattr(entry, "runtime_data", None), "panel", None)


def _constant_time_equal(left: str, right: str) -> bool:
    """Compare two secrets without leaking their contents through timing.

    Compared as bytes: compare_digest refuses a str holding anything but
    ASCII, and the path is percent-decoded, so it can hold anything.
    """
    return hmac.compare_digest(
        left.encode("utf-8", "surrogatepass"), right.encode("utf-8", "surrogatepass")
    )


class SlideshowPanelView(http.HomeAssistantView):
    """Serve the dashboard page itself."""

    url = PANEL_URL
    name = "api:slideshow:panel"
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.StreamResponse:
        """Return the page shell.

        It is served even while the player's entry is not set up (the player
        was not answering yet when Home Assistant started, say): the page then
        keeps asking for its stream until the panel is there.
        """
        hass = request.app[http.KEY_HASS]
        entry = _find_entry(hass, secret)
        if entry is None:
            return web.Response(status=404, text="Unknown panel")
        return web.Response(
            text=_page(entry.options.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE)),
            content_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": PANEL_CSP,
            },
        )


class SlideshowPanelEventsView(http.HomeAssistantView):
    """Stream re-renders to the page."""

    url = EVENTS_URL
    name = "api:slideshow:panel:events"
    requires_auth = False

    async def get(self, request: web.Request, secret: str) -> web.StreamResponse:
        """Stream server-sent events until the viewer goes away."""
        hass = request.app[http.KEY_HASS]
        entry = _find_entry(hass, secret)
        if entry is None:
            return web.Response(status=404, text="Unknown panel")
        renderer = _renderer(entry)
        if renderer is None or hass.is_stopping:
            # The page shows itself disconnected and asks again shortly.
            return web.Response(
                status=503,
                text="The panel is not ready",
                headers={"Cache-Control": "no-store", "Retry-After": "10"},
            )

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
                    await response.write(HEARTBEAT)
                    continue
                if html is None:
                    break
                payload = json.dumps(html)
                await response.write(f"data: {payload}\n\n".encode())
        except ConnectionResetError:
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
        if _find_entry(hass, secret) is None:
            return web.Response(status=404, text="Unknown panel")
        try:
            base = panel_base_url(hass)
        except NoURLAvailableError:
            return web.Response(status=503, text="No Home Assistant URL is known")
        return web.Response(
            text=f"{base}{panel_path(secret)}\n",
            content_type="text/plain",
            headers={"Cache-Control": "no-store"},
        )


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Register the panel views once for the whole integration.

    Called from async_setup, so the addresses answer whether or not a
    player's entry has managed to set up yet.
    """
    if hass.data.get(_VIEWS_REGISTERED):
        return
    hass.http.register_view(SlideshowPanelView())
    hass.http.register_view(SlideshowPanelEventsView())
    hass.http.register_view(SlideshowPanelUrlFileView())
    hass.data[_VIEWS_REGISTERED] = True

    @callback
    def _async_end_streams(event: Event) -> None:
        """End open streams, or the web server waits for them when stopping.

        Entries are not unloaded when Home Assistant stops, so nothing else
        ends them, and every restart would sit out the server's full timeout.
        """
        for entry in hass.config_entries.async_entries(DOMAIN):
            renderer = getattr(getattr(entry, "runtime_data", None), "panel", None)
            if renderer is not None:
                renderer.async_disconnect_viewers()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_end_streams)


def panel_base_url(hass: HomeAssistant) -> str:
    """Return the Home Assistant address a player should use.

    Players are often old Android devices whose browser cannot manage a
    modern certificate chain, so the LAN address is tried on its own first
    and an external address is only a fallback. Raises
    ``NoURLAvailableError`` when neither is known.
    """
    try:
        return get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        return get_url(hass, allow_cloud=False)


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
<title>{html.escape(title)}</title>
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
<script>{_SCRIPT}</script>
</body>
</html>
"""
