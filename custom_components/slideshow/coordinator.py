"""Polling coordinator for a SlideShow player."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SlideshowApiError,
    SlideshowAuthError,
    SlideshowClient,
    SlideshowError,
    SlideshowNotSupportedError,
)
from .const import (
    ACTIVITY_JITTER,
    AUTH_GRACE_PERIOD,
    CONF_SCREEN_OFF_LAYOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCREEN_OFF_LAYOUT,
    DOMAIN,
    PLAYLIST_REFRESH_INTERVAL,
)

if TYPE_CHECKING:
    from .panel import PanelRenderer

_LOGGER = logging.getLogger(__name__)

type SlideshowConfigEntry = ConfigEntry[SlideshowCoordinator]

#: Device registry fields that follow the player, and the deviceInfo key for each.
DEVICE_FIELDS = {
    "name": "deviceName",
    "model": "hardwareModel",
    "sw_version": "softwareVersion",
    "serial_number": "serialNumber",
}


class SlideshowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll ``/ajax/deviceInfo``, which carries the whole device status."""

    config_entry: SlideshowConfigEntry

    #: Set during setup; serves the live dashboard page for this player.
    panel: PanelRenderer

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SlideshowConfigEntry,
        client: SlideshowClient,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        self.client = client
        #: Playlist name to playlist ID, from the player's content entries.
        self.playlists: dict[str, int] = {}
        self._playlists_read: datetime | None = None
        self._auth_rejected_since: datetime | None = None
        #: The player's own time zone, for the naive timestamps it reports.
        self.time_zone: tzinfo = dt_util.get_default_time_zone()
        self._time_zone_name: str | None = None
        #: Screen layouts by name, each with its ID and power-off flag.
        self.layouts: dict[str, dict[str, Any]] = {}
        #: What each zone on screen, and the audio zone, is playing.
        self.zones: list[dict[str, Any]] = []
        #: When the screen was last touched or a key pressed.
        self.last_user_activity: datetime | None = None
        #: Endpoints this player answered 404 for; they are not asked again.
        self._unsupported: set[str] = set()
        #: Whether ``screen/power`` works here; ``None`` until first tried.
        self._screen_power_api: bool | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current device status."""
        try:
            data = await self.client.async_get_device_info()
        except SlideshowAuthError as err:
            # A player can reject perfectly good credentials for a moment --
            # while it is starting up, or being reconfigured. Asking the user
            # to retype a password that never changed is worse than waiting,
            # so a rejection has to persist before reauthentication starts.
            now = dt_util.utcnow()
            if self._auth_rejected_since is None:
                self._auth_rejected_since = now
            rejected_for = now - self._auth_rejected_since
            if rejected_for >= AUTH_GRACE_PERIOD:
                raise ConfigEntryAuthFailed(str(err)) from err
            _LOGGER.warning(
                "%s has rejected the stored credentials for %s; asking for new "
                "ones if this continues past %s: %s",
                self.config_entry.title,
                str(rejected_for).split(".")[0],
                AUTH_GRACE_PERIOD,
                err,
            )
            raise UpdateFailed(str(err)) from err
        except SlideshowError as err:
            raise UpdateFailed(str(err)) from err

        self._auth_rejected_since = None
        await self._async_resolve_time_zone(data.get("timeZone"))
        self._async_update_device(data)

        # Content entries change rarely and cost an extra request, so they are
        # read on a slower cycle than the device status.
        now = dt_util.utcnow()
        if (
            self._playlists_read is None
            or now - self._playlists_read > PLAYLIST_REFRESH_INTERVAL
        ):
            await self.async_refresh_playlists()
            await self.async_refresh_layouts()

        zones = await self._async_read_optional(
            "zone/content", self.client.async_get_zone_content
        )
        if zones is not None:
            self.zones = zones
        seconds = await self._async_read_optional(
            "lastUserActivity", self.client.async_get_seconds_since_user_activity
        )
        if seconds is not None:
            self._async_set_last_user_activity(now - timedelta(seconds=seconds))

        return data

    def supports(self, endpoint: str) -> bool:
        """Return whether the player offers an endpoint, as far as is known.

        Only a 404 counts against it, so a player that was merely slow to
        answer during setup still gets the entities that need the endpoint.
        """
        return endpoint not in self._unsupported

    async def _async_read_optional[T](
        self, endpoint: str, read: Callable[[], Awaitable[T]]
    ) -> T | None:
        """Read from an endpoint that older players lack.

        A failure returns ``None`` rather than failing the update, since the
        device status itself was read fine.
        """
        if endpoint in self._unsupported:
            return None
        try:
            return await read()
        except SlideshowNotSupportedError:
            _LOGGER.debug("%s does not offer %s", self.config_entry.title, endpoint)
            self._unsupported.add(endpoint)
        except SlideshowError as err:
            _LOGGER.debug("Could not read %s: %s", endpoint, err)
        return None

    def _async_set_last_user_activity(self, when: datetime) -> None:
        """Record the last user activity, ignoring the jitter between polls.

        The player reports whole seconds since the activity, so the same
        touch works out to a slightly different moment on every poll.
        """
        previous = self.last_user_activity
        if previous is None or abs(when - previous) > ACTIVITY_JITTER:
            self.last_user_activity = when.replace(microsecond=0)

    def _async_update_device(self, data: dict[str, Any]) -> None:
        """Keep the device registry in step with the player.

        Home Assistant reads an entity's device info only when the entity is
        added, so an app update or a renamed player would otherwise show the
        old details until the entry is reloaded.
        """
        entry = self.config_entry
        identifier = (DOMAIN, entry.unique_id or entry.entry_id)
        registry = dr.async_get(self.hass)
        # The first refresh runs before any entity has created the device.
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            if identifier not in device.identifiers:
                continue
            changes = {
                field: value
                for field, key in DEVICE_FIELDS.items()
                if (value := data.get(key)) is not None
                and getattr(device, field) != value
            }
            if changes:
                registry.async_update_device(device.id, **changes)

    async def _async_resolve_time_zone(self, name: str | None) -> None:
        """Look the player's time zone up once, whenever its name changes.

        Loading a zone reads tzdata from disk, which must not happen on the
        event loop, so it is done here rather than in the sensors. A name
        Home Assistant does not know falls back to its own zone.
        """
        if name == self._time_zone_name:
            return
        self._time_zone_name = name
        try:
            zone = await dt_util.async_get_time_zone(name) if name else None
        except ValueError:
            # A malformed key, such as an absolute path.
            zone = None
        self.time_zone = zone or dt_util.get_default_time_zone()

    async def async_refresh_playlists(self) -> None:
        """Re-read the playlists the player offers.

        A failure here leaves the previous list in place: a momentarily
        unreachable player should not empty the source list.
        """
        try:
            content = await self.client.async_get_content()
        except SlideshowError as err:
            _LOGGER.debug("Could not read content entries: %s", err)
            return

        self.playlists = {
            entry["name"]: entry["playlistId"]
            for entry in content
            if entry.get("name") and entry.get("playlistId") is not None
        }
        self._playlists_read = dt_util.utcnow()

    async def async_refresh_layouts(self) -> None:
        """Re-read the screen layouts, which SlideShow lists from 4.13.0."""
        layouts = await self._async_read_optional(
            "layout/get", self.client.async_get_layouts
        )
        if layouts is not None:
            self.layouts = {
                layout["name"]: layout for layout in layouts if layout.get("name")
            }

    @property
    def screen_off_layout(self) -> str:
        """Return the layout that powers the screen down.

        The configured name wins while the player has a layout by that name.
        Otherwise the layout the player itself flags as powering off is used,
        since its name follows the app's language.
        """
        configured = self.config_entry.options.get(CONF_SCREEN_OFF_LAYOUT)
        if configured and (not self.layouts or configured in self.layouts):
            return configured
        detected = next(
            (name for name, layout in self.layouts.items() if layout.get("powerOff")),
            None,
        )
        return detected or configured or DEFAULT_SCREEN_OFF_LAYOUT

    def _showing_power_off_layout(self) -> bool:
        """Return whether the screen is off because of the layout on it."""
        current = (self.data or {}).get("currentScreenLayout")
        if current in self.layouts:
            return bool(self.layouts[current].get("powerOff"))
        return current == self.screen_off_layout

    async def async_set_screen_power(self, on: bool) -> None:
        """Turn the screen on or off.

        ``screen/power`` drives the display directly where SlideShow can,
        which keeps the layout and playback untouched. Elsewhere the device
        answers with an error, and the screen is switched with the layout
        SlideShow shows while a schedule has the display powered down.
        """
        if on and (
            self._screen_power_api is False or self._showing_power_off_layout()
        ):
            # A power-off layout would keep the screen dark whatever the
            # power endpoint says, so it has to go first.
            await self.client.async_clear_layout()
            cleared = True
        else:
            cleared = False

        if self._screen_power_api is not False:
            try:
                await self.client.async_set_screen_power(on)
            except SlideshowApiError as err:
                _LOGGER.debug(
                    "%s cannot switch its screen directly, using the screen off "
                    "layout instead: %s",
                    self.config_entry.title,
                    err,
                )
                self._screen_power_api = False
            else:
                self._screen_power_api = True

        if self._screen_power_api is False:
            if not on:
                await self.client.async_set_layout(layout_name=self.screen_off_layout)
            elif not cleared:
                await self.client.async_clear_layout()

        await self.async_request_refresh()
