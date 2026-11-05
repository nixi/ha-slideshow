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
    SCHEDULE_OVERRIDE_FALLBACK,
    SCHEDULE_OVERRIDE_MAX,
)

if TYPE_CHECKING:
    from .panel import PanelRenderer

_LOGGER = logging.getLogger(__name__)

#: hass.data key: entry ID to when the player started rejecting its stored
#: credentials. Kept outside the coordinator because every setup retry builds
#: a new one, and a clock that restarted with it would never run out.
_AUTH_REJECTED_SINCE = f"{DOMAIN}_auth_rejected_since"

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

    @property
    def _auth_rejected_since(self) -> datetime | None:
        """Return when the player started rejecting the stored credentials.

        This survives setup retries, so a player that rejects good
        credentials while it starts up gets the same grace period during
        setup as later, and one that keeps rejecting still ends in reauth.
        """
        return self.hass.data.get(_AUTH_REJECTED_SINCE, {}).get(
            self.config_entry.entry_id
        )

    @_auth_rejected_since.setter
    def _auth_rejected_since(self, value: datetime | None) -> None:
        rejected = self.hass.data.setdefault(_AUTH_REJECTED_SINCE, {})
        if value is None:
            rejected.pop(self.config_entry.entry_id, None)
        else:
            rejected[self.config_entry.entry_id] = value

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
        # The address may now belong to another player, after a router
        # restart reshuffled the leases. Controlling that player, and renaming
        # this device after it, would be worse than going unavailable.
        device_id = data.get("deviceId")
        expected = self.config_entry.unique_id
        if device_id and expected and device_id != expected:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="wrong_device",
                translation_placeholders={"title": self.config_entry.title},
            )
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
            # Counted back from when the answer came, not from the start of
            # the poll: the reads before it can take a while.
            self._async_set_last_user_activity(
                dt_util.utcnow() - timedelta(seconds=seconds)
            )

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

    def _is_power_off_layout(self, name: str | None) -> bool:
        """Return whether a layout powers the screen down."""
        if name in self.layouts:
            return bool(self.layouts[name].get("powerOff"))
        return name == self.screen_off_layout

    def _showing_power_off_layout(self) -> bool:
        """Return whether the screen is off because of the layout on it."""
        return self._is_power_off_layout((self.data or {}).get("currentScreenLayout"))

    @property
    def screen_on(self) -> bool | None:
        """Return whether the display is showing anything.

        A power-off layout leaves nothing to see even while the backlight is
        on, which happens when someone touches a player whose schedule has
        the display off. ``screenPower`` alone would call that on.
        """
        if self.data is None:
            return None
        if self._showing_power_off_layout():
            return False
        return self.data.get("screenPower")

    def _layout_to_show(self) -> dict[str, Any] | None:
        """Return the layout to show when the schedule says power off.

        The layout with the lowest ID that neither powers off nor is a
        screensaver: SlideShow's own default layout comes first.
        """
        candidates = [
            layout
            for layout in self.layouts.values()
            if not layout.get("powerOff")
            and not layout.get("screensaver")
            and layout.get("id") is not None
        ]
        return min(candidates, key=lambda layout: layout["id"], default=None)

    async def _async_show_over_schedule(self) -> None:
        """Show a layout if the player's schedule still has the screen off.

        Clearing a layout only returns to the schedule, and a schedule can
        itself say power off. The layout set here expires on the player when
        the schedule would show a layout anyway, so the schedule gets the
        screen back without Home Assistant having to remember anything.
        """
        if not self.layouts or (layout := self._layout_to_show()) is None:
            return
        try:
            info = await self.client.async_get_device_info()
        except SlideshowError as err:
            # The screen still gets switched on; only the override is skipped.
            _LOGGER.debug("Could not read the layout after clearing it: %s", err)
            return
        if not self._is_power_off_layout(info.get("currentScreenLayout")):
            return
        length = await self._async_until_schedule_shows_a_layout()
        await self.client.async_set_layout(
            layout_id=layout["id"], length=int(length.total_seconds())
        )

    async def _async_until_schedule_shows_a_layout(self) -> timedelta:
        """Return how long the schedule keeps the screen powered off from now.

        Back-to-back power-off intervals count as one, since the schedule
        splits them at midnight.
        """
        now = dt_util.now(self.time_zone).replace(tzinfo=None)
        try:
            schedule = await self.client.async_get_layout_schedule(
                now.date(), (now + SCHEDULE_OVERRIDE_MAX).date()
            )
        except SlideshowError as err:
            _LOGGER.debug("Could not read the layout schedule: %s", err)
            return SCHEDULE_OVERRIDE_FALLBACK

        power_off = {
            layout.get("id")
            for layout in self.layouts.values()
            if layout.get("powerOff")
        }
        intervals = []
        for interval in schedule:
            try:
                start = datetime.fromisoformat(interval["from"])
                # "to" is the last minute the interval covers.
                end = datetime.fromisoformat(interval["to"]) + timedelta(minutes=1)
            except (KeyError, TypeError, ValueError):
                continue
            intervals.append((start, end, interval.get("entityId")))

        until = now
        for start, end, layout_id in sorted(intervals, key=lambda i: i[:2]):
            if end <= until:
                continue
            if start > until + timedelta(minutes=1) or layout_id not in power_off:
                break
            until = end
        if until <= now:
            return SCHEDULE_OVERRIDE_FALLBACK
        return min(until - now, SCHEDULE_OVERRIDE_MAX)

    async def async_set_screen_power(self, on: bool) -> None:
        """Turn the screen on or off.

        ``screen/power`` drives the display directly where SlideShow can,
        which keeps the layout and playback untouched. Elsewhere the device
        answers with an error, and the screen is switched with the layout
        SlideShow shows while a schedule has the display powered down.
        """
        if on and (self._screen_power_api is False or self._showing_power_off_layout()):
            # A power-off layout would keep the screen dark whatever the
            # power endpoint says, so it has to go first.
            await self.client.async_clear_layout()
            cleared = True
            await self._async_show_over_schedule()
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
