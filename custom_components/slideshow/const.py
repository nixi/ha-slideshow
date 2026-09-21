"""Constants for the SlideShow Digital Signage integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "slideshow"

CONF_VERIFY_SSL: Final = "verify_ssl"

DEFAULT_PORT_HTTP: Final = 8080
DEFAULT_PORT_HTTPS: Final = 8443
DEFAULT_USERNAME: Final = "admin"
DEFAULT_PASSWORD: Final = "admin"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
MIN_SCAN_INTERVAL: Final = 5

# Playlists are read on a slower cycle than the device status, since
# content entries change rarely and cost an extra request.
PLAYLIST_REFRESH_INTERVAL: Final = timedelta(minutes=5)
MAX_SCAN_INTERVAL: Final = 3600

CONF_SCAN_INTERVAL: Final = "scan_interval"

MANUFACTURER: Final = "SlideShow"

# Service names
SERVICE_SHOW_FILE: Final = "show_file"
SERVICE_SHOW_HTML: Final = "show_html"
SERVICE_SHOW_STREAM: Final = "show_stream"
SERVICE_SET_PLAYLIST: Final = "set_playlist"
SERVICE_SET_LAYOUT: Final = "set_layout"
SERVICE_SYNCHRONIZE: Final = "synchronize"
SERVICE_SHOW_CAMERA: Final = "show_camera"
SERVICE_INSTALL_PANEL: Final = "install_panel"

ATTR_FILE: Final = "file"
ATTR_HTML: Final = "html"
ATTR_URL: Final = "url"
ATTR_LENGTH: Final = "length"
ATTR_ZONE_ID: Final = "zone_id"
ATTR_ZONE_NAME: Final = "zone_name"
ATTR_PLAYLIST_ID: Final = "playlist_id"
ATTR_PLAYLIST_NAME: Final = "playlist_name"
ATTR_PLAYLIST_NUMBER: Final = "playlist_number"
ATTR_LAYOUT_ID: Final = "layout_id"
ATTR_LAYOUT_NAME: Final = "layout_name"
ATTR_METHOD: Final = "method"
ATTR_TARGET: Final = "target"
ATTR_CLEAR_FOLDER: Final = "clear_folder"
ATTR_CAMERA_ENTITY_ID: Final = "camera_entity_id"
ATTR_DURATION: Final = "duration"
ATTR_CONTENT_NAME: Final = "content_name"
ATTR_FILENAME: Final = "filename"

DEFAULT_PANEL_CONTENT_NAME: Final = "Home Assistant panel"
DEFAULT_PANEL_FILENAME: Final = "ha_panel.url"

# The audio playlist is addressed by this literal zone ID. Note the device
# rejects the audio zone's *name*, so only the ID works.
AUDIO_ZONE_ID: Final = "audio"

# Live dashboard panel
CONF_PANEL_SECRET: Final = "panel_secret"
CONF_PANEL_TEMPLATE: Final = "panel_template"
CONF_PANEL_TITLE: Final = "panel_title"
DEFAULT_PANEL_TITLE: Final = "SlideShow panel"

# Screen power is driven by switching to the layout that SlideShow shows while a
# screen layout schedule has it powered down. The name is configurable because
# it follows the app's language.
CONF_SCREEN_OFF_LAYOUT: Final = "screen_off_layout"
DEFAULT_SCREEN_OFF_LAYOUT: Final = "Screen power off"

# Streams and remote media have no length known to Home Assistant, so a
# generous default is used and the stream is expected to end on its own.
DEFAULT_MEDIA_DURATION: Final = 3600


# Shipped as the starting point for the live panel. The three lists at the top
# are the only part most people need to touch, so they are kept together.
DEFAULT_PANEL_TEMPLATE: Final = """\
{%- set weather_entity = "weather.home" -%}
{%- set outdoor = "sensor.outside_temperature" -%}
{%- set indoor = [
     ("Living room", "sensor.living_room_temperature"),
     ("Hallway", "sensor.hallway_temperature"),
   ] -%}
{%- set agenda = ["calendar.home"] -%}
{%- set transit = "sensor.departures" -%}
{%- set status = [
     ("Alarm", "alarm_control_panel.home"),
     ("Front door", "lock.front_door"),
   ] -%}
{%- set alerting = ["on", "open", "unlocked", "wet", "triggered", "detected"] -%}

<div class="ss-grid" style="grid-template-rows: auto 1fr;">

  <div class="ss-row">
    <div class="ss-card" style="flex: 0 0 34%">
      <div class="ss-label">Outside</div>
      <div class="ss-big">{{ states(outdoor) }}&deg;</div>
      <div class="ss-mid ss-muted">
        {{ states(weather_entity) | replace("_", " ") | title }}
      </div>
    </div>
    <div class="ss-card">
      <div class="ss-label">Inside</div>
      <ul class="ss-list">
        {%- for name, eid in indoor %}
        <li><span>{{ name }}</span>
            <span>{{ states(eid) }}
              {{ state_attr(eid, "unit_of_measurement") or "" }}</span></li>
        {%- endfor %}
      </ul>
    </div>
  </div>

  <div class="ss-row">
    <div class="ss-card">
      <div class="ss-label">Next up</div>
      <ul class="ss-list">
        {%- for eid in agenda %}
        {%- if states(eid) not in ["unknown", "unavailable"] %}
        <li><span>{{ state_attr(eid, "message") or "Nothing scheduled" }}</span>
            <span class="ss-muted">
              {{ (state_attr(eid, "start_time") or "")[11:16] }}</span></li>
        {%- endif %}
        {%- endfor %}
        {%- if states(transit) not in ["unknown", "unavailable"] %}
        <li><span>Next departure</span><span>{{ states(transit) }}</span></li>
        {%- endif %}
      </ul>
    </div>
    <div class="ss-card">
      <div class="ss-label">Status</div>
      <ul class="ss-list">
        {%- for name, eid in status %}
        {%- set value = states(eid) %}
        <li><span>{{ name }}</span>
            <span class="{{ "ss-bad" if value in alerting else "ss-ok" }}">
              {{ value | replace("_", " ") | title }}</span></li>
        {%- endfor %}
      </ul>
    </div>
  </div>

</div>
<div class="ss-label" style="position: fixed; bottom: 1.5vh; left: 3vw">
  {{ now().strftime("%H:%M &middot; %a %d %b") }}
</div>
"""
