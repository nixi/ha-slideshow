"""Shared fixtures data, taken from a real player running SlideShow 4.12.7."""

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)

from custom_components.slideshow.const import CONF_VERIFY_SSL

HOST = "192.0.2.10"
PORT = 8080
BASE = f"http://{HOST}:{PORT}"

USER_INPUT = {
    CONF_HOST: HOST,
    CONF_PORT: PORT,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "admin",
    CONF_SSL: False,
    CONF_VERIFY_SSL: False,
}

# Trimmed from an actual /ajax/deviceInfo response. Note that it is a bare
# object: every other endpoint wraps its payload in success/result.
DEVICE_INFO = {
    "deviceId": "637f0651ea9ef4c",
    "deviceName": "Frame",
    "softwareVersion": "4.12.7",
    "androidVersion": "6.0.1",
    "hardwareModel": "Frame",
    "serialNumber": "65330797",
    "macAddress": "2E:36:EC:21:97:EF",
    "ipAddressInternal": HOST,
    "timeZone": "Europe/Stockholm",
    "uptime": 1789631621172,
    "appUptime": 1789631659956,
    "currentTime": 1789741074105,
    "lastDisplayedFile": "/webpages/room.url",
    "lastDisplayedTime": "2026-09-18T08:00:05.714",
    "currentPlaylist": "All files in cycle",
    "currentScreenLayout": "Default layout",
    "currentVolume": 20,
    "screenPower": True,
    "screenBrightness": 100,
    "paused": False,
    "rooted": True,
    "deviceOwner": False,
    "deviceAdmin": False,
    "lockTaskMode": False,
    "lockTaskApplication": False,
    "storageSpaceFree": 13118431232,
    "storageSpaceTotal": 13658669056,
}


# /ajax/content/get, as a real player answers it. Every entry carries the ID
# of the playlist it belongs to, which is the only way to enumerate playlists.
CONTENT = [
    {"id": 1, "playlistId": 1, "type": "IMAGE", "name": "All files in cycle",
     "path": "photos"},
    {"id": 33, "playlistId": 34, "type": "IMAGE", "name": "HA Template",
     "path": "ha.url"},
]
