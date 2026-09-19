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
