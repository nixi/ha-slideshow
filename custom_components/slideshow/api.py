"""Async client for the SlideShow Digital Signage local REST API.

The API is documented at https://slideshow.digital/documentation/integration/rest-api/

Two behaviours of the device deviate from the published OpenAPI specification and
are handled here:

* Unauthenticated or badly authenticated requests are answered with an HTTP 303
  redirect to ``/login`` rather than a 401. Redirects are therefore never
  followed, and any 3xx is treated as an authentication failure.
* ``/ajax/deviceInfo`` returns a bare JSON object, while every other endpoint
  wraps its payload in ``{"success": bool, "result": {...}}``. Both shapes are
  normalised to the inner payload.
"""

from __future__ import annotations

import base64
import logging
from http import HTTPStatus
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)
SCREENSHOT_TIMEOUT = aiohttp.ClientTimeout(total=45)

# Where the device sends a request whose credentials it did not accept.
LOGIN_PATH = "/login"


class SlideshowError(Exception):
    """Base error for all SlideShow API failures."""


class SlideshowConnectionError(SlideshowError):
    """The device could not be reached."""


class SlideshowAuthError(SlideshowError):
    """The supplied credentials were rejected."""


class SlideshowApiError(SlideshowError):
    """The device was reached but reported a failure."""


def _clean_params(params: dict[str, Any] | None) -> dict[str, str]:
    """Drop unset parameters and render the rest the way the device expects."""
    if not params:
        return {}
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        else:
            cleaned[key] = str(value)
    return cleaned


class SlideshowClient:
    """Talk to a single SlideShow player."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        use_ssl: bool = False,
        verify_ssl: bool = True,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._host = host
        self._port = port
        scheme = "https" if use_ssl else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._auth = aiohttp.BasicAuth(username, password)
        # ``None`` keeps aiohttp's default handling; ``False`` disables
        # verification, which is needed for the self-signed certificate the app
        # generates on first start.
        self._ssl: bool | None = None
        if use_ssl:
            self._ssl = True if verify_ssl else False

    @property
    def base_url(self) -> str:
        """Return the base URL of the player's web interface."""
        return self._base_url

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        client_timeout: aiohttp.ClientTimeout = DEFAULT_TIMEOUT,
    ) -> Any:
        """Perform a request and return the normalised payload."""
        url = f"{self._base_url}/ajax/{path}"
        try:
            response = await self._session.request(
                method,
                url,
                params=_clean_params(params),
                auth=self._auth,
                timeout=client_timeout,
                allow_redirects=False,
                ssl=self._ssl,
            )
            async with response:
                if response.status in (
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                ):
                    raise SlideshowAuthError(
                        f"Authentication rejected by {self._host} "
                        f"(HTTP {response.status})"
                    )
                if 300 <= response.status < 400:
                    # Rejected credentials are answered with a redirect to the
                    # login page rather than a 401. A redirect somewhere else
                    # is not an authentication problem, and must not drag the
                    # user through re-authentication.
                    location = response.headers.get("Location", "")
                    if LOGIN_PATH in location:
                        raise SlideshowAuthError(
                            f"Authentication rejected by {self._host}: "
                            f"redirected to {location}"
                        )
                    raise SlideshowApiError(
                        f"{method} {path} was redirected to {location or 'nowhere'}"
                    )
                if response.status >= 400:
                    body = (await response.text())[:200]
                    raise SlideshowApiError(
                        f"{method} {path} failed: HTTP {response.status}: {body}"
                    )
                payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise SlideshowConnectionError(
                f"Timeout talking to SlideShow at {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise SlideshowConnectionError(
                f"Cannot connect to SlideShow at {self._host}: {err}"
            ) from err

        if not isinstance(payload, dict):
            raise SlideshowApiError(f"{path} returned an unexpected payload type")

        # deviceInfo answers with a bare object; everything else is wrapped.
        if "success" in payload:
            if not payload["success"]:
                reason = (
                    payload.get("errorMessage")
                    or payload.get("errorCode")
                    or "no reason given"
                )
                raise SlideshowApiError(f"{path} was rejected by the device: {reason}")
            result = payload.get("result", {})
            return result if isinstance(result, dict) else {}
        return payload

    # -- Reads ---------------------------------------------------------------

    async def async_get_device_info(self) -> dict[str, Any]:
        """Return the device status object that drives every entity."""
        return await self._request("GET", "deviceInfo")

    async def async_get_display_info(self) -> dict[str, Any]:
        """Return information about the attached displays."""
        return await self._request("GET", "displayInfo")

    async def async_get_zones(self) -> dict[str, str]:
        """Return the zones of the current screen layout, keyed by zone ID."""
        return await self._request("GET", "zones")

    async def async_get_volume(self) -> int:
        """Return the current volume as a percentage."""
        result = await self._request("GET", "volume/get")
        return int(result.get("currentVolume", 0))

    async def async_get_content(self) -> list[dict[str, Any]]:
        """Return the configured content entries."""
        result = await self._request("GET", "content/get")
        return result.get("content", [])

    async def async_create_content(
        self, name: str, path: str, content_type: str = "ALPHABETICALLY"
    ) -> dict[str, Any]:
        """Create a content entry and return its ``id`` and ``playlistId``."""
        return await self._request(
            "POST",
            "content/create",
            {"name": name, "path": path, "type": content_type},
        )

    async def async_delete_content(self, content_id: int) -> None:
        """Delete a content entry, which the device refuses if it is scheduled."""
        await self._request("POST", "content/delete", {"id": content_id})

    async def async_get_last_synchronizations(self) -> list[dict[str, Any]]:
        """Return statistics about the five most recent file synchronisations."""
        result = await self._request("GET", "synchronize/last")
        return result.get("lastStatistics", [])

    async def async_get_screenshot(self) -> bytes:
        """Return a JPEG screenshot of the player's current screen."""
        result = await self._request(
            "GET", "screenshot", client_timeout=SCREENSHOT_TIMEOUT
        )
        data = result.get("data")
        if not data:
            raise SlideshowApiError("Device returned an empty screenshot")
        try:
            return base64.b64decode(data)
        except (ValueError, TypeError) as err:
            raise SlideshowApiError("Screenshot was not valid base64") from err

    # -- Playback ------------------------------------------------------------

    async def async_next(
        self, zone_id: Any = None, zone_name: str | None = None
    ) -> None:
        """Play the next file in a zone."""
        await self._request("PUT", "next", {"zoneId": zone_id, "zoneName": zone_name})

    async def async_previous(
        self, zone_id: Any = None, zone_name: str | None = None
    ) -> None:
        """Play the previous file in a zone."""
        await self._request(
            "PUT", "previous", {"zoneId": zone_id, "zoneName": zone_name}
        )

    async def async_audio_next(self) -> None:
        """Play the next file in the audio playlist."""
        await self._request("PUT", "audio/next")

    async def async_pause(
        self, zone_id: Any = None, zone_name: str | None = None
    ) -> None:
        """Pause playback in a zone."""
        await self._request("PUT", "pause", {"zoneId": zone_id, "zoneName": zone_name})

    async def async_resume(
        self, zone_id: Any = None, zone_name: str | None = None
    ) -> None:
        """Resume playback in a zone."""
        await self._request("PUT", "resume", {"zoneId": zone_id, "zoneName": zone_name})

    async def async_show_file(
        self,
        file: str,
        length: int,
        zone_id: Any = None,
        zone_name: str | None = None,
    ) -> None:
        """Display a single file, overwriting the current playlist."""
        await self._request(
            "POST",
            "showFile",
            {
                "file": file,
                "length": length,
                "zoneId": zone_id,
                "zoneName": zone_name,
            },
        )

    async def async_show_html(
        self,
        html: str,
        length: int,
        zone_id: Any = None,
        zone_name: str | None = None,
    ) -> None:
        """Display a block of HTML, overwriting the current playlist."""
        await self._request(
            "POST",
            "showSentHtml",
            {
                "html": html,
                "length": length,
                "zoneId": zone_id,
                "zoneName": zone_name,
            },
        )

    async def async_show_stream(
        self,
        address: str,
        duration: int,
        zone_id: Any = None,
        zone_name: str | None = None,
    ) -> None:
        """Display an audio or video stream, overwriting the current playlist.

        Note the parameter names: this endpoint takes ``address``/``duration``
        where the others take ``file``/``length``.
        """
        await self._request(
            "POST",
            "showStream",
            {
                "address": address,
                "duration": duration,
                "zoneId": zone_id,
                "zoneName": zone_name,
            },
        )

    async def async_set_playlist(
        self,
        playlist_id: int | None = None,
        playlist_name: str | None = None,
        playlist_number: int | None = None,
        length: int | None = None,
        zone_id: Any = None,
        zone_name: str | None = None,
    ) -> None:
        """Switch a zone to a particular playlist."""
        await self._request(
            "PUT",
            "playlist/set",
            {
                "playlistId": playlist_id,
                "playlistName": playlist_name,
                "playlistNumber": playlist_number,
                "length": length,
                "zoneId": zone_id,
                "zoneName": zone_name,
            },
        )

    async def async_clear_playlist(
        self, zone_id: Any = None, zone_name: str | None = None
    ) -> None:
        """Clear the playlist override in a zone."""
        await self._request(
            "PUT", "playlist/clear", {"zoneId": zone_id, "zoneName": zone_name}
        )

    async def async_set_layout(
        self,
        layout_id: int | None = None,
        layout_name: str | None = None,
        length: int | None = None,
    ) -> None:
        """Switch to a particular screen layout."""
        await self._request(
            "PUT",
            "layout/set",
            {"layoutId": layout_id, "layoutName": layout_name, "length": length},
        )

    async def async_clear_layout(self) -> None:
        """Clear the screen layout override."""
        await self._request("PUT", "layout/clear")

    async def async_toggle_fullscreen(self) -> None:
        """Toggle fullscreen display of the main zone."""
        await self._request("PUT", "fullscreen/toggle")

    async def async_zoom_in(self) -> None:
        """Zoom in on the displayed web page."""
        await self._request("PUT", "zoom/in")

    async def async_zoom_out(self) -> None:
        """Zoom out of the displayed web page."""
        await self._request("PUT", "zoom/out")

    # -- Audio ---------------------------------------------------------------

    async def async_set_volume(self, percentage: int) -> int:
        """Set the global volume as a percentage and return the accepted value."""
        result = await self._request(
            "PUT", "volume/set", {"volPercentage": max(0, min(100, percentage))}
        )
        return int(result.get("currentVolume", percentage))

    async def async_beep(self) -> None:
        """Play a beep tone."""
        await self._request("PUT", "beep")

    # -- Device --------------------------------------------------------------

    async def async_activate_screensaver(self) -> None:
        """Activate the screensaver layout, if one is configured."""
        await self._request("PUT", "screensaver/activate")

    async def async_deactivate_screensaver(self) -> None:
        """Deactivate the screensaver layout."""
        await self._request("PUT", "screensaver/deactivate")

    async def async_reload(self) -> None:
        """Restart the SlideShow app."""
        await self._request("PUT", "reload")

    async def async_reboot(self) -> None:
        """Reboot the whole Android device."""
        await self._request("PUT", "reboot")

    async def async_synchronize(
        self,
        url: str,
        target: str,
        method: str = "GET",
        clear_folder: bool = False,
    ) -> None:
        """Trigger a file synchronisation from an external server."""
        await self._request(
            "POST",
            "synchronize",
            {
                "url": url,
                "method": method,
                "target": target,
                "clearFolder": clear_folder,
            },
        )
