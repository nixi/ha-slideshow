#!/usr/bin/env python3
"""Render docs/panel.png: the example panel template, with invented data.

The screenshot is produced from the real page shell in panel.py and the real
template in docs/panel-example.jinja, so it cannot drift into showing a layout
the integration does not actually produce. Everything it displays is made up —
never point this at a real Home Assistant.

Needs jinja2, pillow and Google Chrome.

Usage:
    python scripts/make_panel_screenshot.py
"""

from __future__ import annotations

import datetime
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from jinja2 import Environment
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

# An entirely invented household.
STATES = {
    "weather.home": "partlycloudy",
    "sensor.electricity_price": "0.94",
    "sensor.living_room_temperature": "21.4",
    "sensor.bedroom_temperature": "19.8",
    "sensor.study_temperature": "22.1",
    "sensor.garden_temperature": "12.6",
    "alarm_control_panel.home": "disarmed",
    "lock.front_door": "locked",
    "lock.garage": "unlocked",
    "lock.back_door": "locked",
    "binary_sensor.any_water_leak": "off",
    "sensor.bus_stop_departures": "4",
}
ATTRS = {
    ("weather.home", "temperature"): 14.2,
    ("weather.home", "humidity"): 63,
    ("sensor.electricity_price", "unit_of_measurement"): "SEK/kWh",
    ("calendar.gym", "message"): "Strength class",
    ("calendar.gym", "start_time"): "2026-09-22 18:30:00",
    ("calendar.school_lunch", "message"): "Pasta with tomato sauce and salad",
    ("calendar.school_lunch", "start_time"): "2026-09-22 11:00:00",
    ("calendar.waste_collection", "message"): "Food and residual waste",
    ("calendar.waste_collection", "start_time"): "2026-09-24 00:00:00",
    ("sensor.bus_stop_departures", "upcoming"): [
        {"line": "3", "destination": "City centre",
         "time_formatted": "08:12", "minutes_until": 4},
        {"line": "6", "destination": "Station",
         "time_formatted": "08:19", "minutes_until": 11},
        {"line": "3", "destination": "City centre",
         "time_formatted": "08:32", "minutes_until": 24},
        {"line": "21", "destination": "Hospital",
         "time_formatted": "08:40", "minutes_until": 32},
    ],
}


def _find_chrome() -> str:
    """Return a usable Chrome binary, or exit explaining what is missing."""
    for candidate in CHROME_CANDIDATES:
        if pathlib.Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("Could not find Google Chrome or Chromium to render with.")


def _render_content() -> str:
    """Render the example template against the invented household."""
    env = Environment()
    env.filters["float"] = lambda value, default=0.0: (
        float(value) if str(value).replace(".", "", 1).isdigit() else default
    )
    template = env.from_string(
        (ROOT / "docs" / "panel-example.jinja").read_text()
    )
    return template.render(
        states=lambda entity: STATES.get(entity, "unknown"),
        state_attr=lambda entity, attr: ATTRS.get((entity, attr)),
        as_datetime=lambda value: datetime.datetime.fromisoformat(str(value)),
        now=lambda: datetime.datetime(2026, 9, 22, 8, 8),
    )


def _page_shell(title: str) -> str:
    """Return the real page shell from panel.py.

    Read rather than imported: the module pulls in Home Assistant, and putting
    its directory on sys.path would shadow standard library modules such as
    `select` with the integration's own platform of the same name.
    """
    source = (ROOT / "custom_components" / "slideshow" / "panel.py").read_text()
    namespace: dict = {}
    exec(source[source.index("def _page(title: str) -> str:") :], namespace)
    return namespace["_page"](title)


def main() -> int:
    """Write docs/panel.png."""
    shell = _page_shell("Hallway panel")
    marker = (
        '<div id="root">'
        '<div class="ss-error">Waiting for Home Assistant…</div></div>'
    )
    if marker not in shell:
        raise SystemExit("The page shell changed; update the marker in this script.")

    page = shell.replace(marker, f'<div id="root">{_render_content()}</div>', 1)
    # A static capture has no event stream, so the live-update script would
    # only raise the disconnected badge.
    page = re.sub(r"<script>.*?</script>", "", page, flags=re.S)
    page = page.replace('<div id="offline" hidden>Disconnected</div>', "")

    with tempfile.TemporaryDirectory() as tmp:
        html = pathlib.Path(tmp) / "panel.html"
        shot = pathlib.Path(tmp) / "panel.png"
        html.write_text(page)
        subprocess.run(
            [
                _find_chrome(), "--headless", "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=1", "--window-size=1280,800",
                f"--screenshot={shot}", str(html),
            ],
            check=True,
            capture_output=True,
        )
        out = ROOT / "docs" / "panel.png"
        Image.open(shot).convert(
            "P", palette=Image.ADAPTIVE, colors=128
        ).save(out, optimize=True)
        print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
