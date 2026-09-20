#!/usr/bin/env python3
"""Generate a starter content pack to upload to a SlideShow player.

Produces numbered slides whose colour and number make playlist cycling,
next/previous and transitions obvious at a glance, plus a web-page link and an
HTML page, and bundles the lot into a ZIP. SlideShow unpacks ZIP uploads
automatically.

Usage:
    python scripts/make_samples.py [output_dir] [--width 1280] [--height 800]
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

SLIDES = [
    ("01", "#1b4965", "Playlist test", "Slide 1 of 5"),
    ("02", "#5fa8d3", "Press Next", "The button entity, or media_player next track"),
    ("03", "#bee9e8", "Press Previous", "Transitions are set per playlist"),
    ("04", "#cae9ff", "Pause and resume", "The media_player reports paused state"),
    ("05", "#62b6cb", "Back to the start", "Slide 5 of 5 - it loops from here"),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Return a bold sans font at the given size, falling back if need be."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _readable_on(hex_colour: str) -> str:
    """Return black or white, whichever is readable on the given background."""
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 145 else "#ffffff"


def _slide(width: int, height: int, spec: tuple[str, str, str, str]) -> Image.Image:
    """Draw one numbered slide."""
    number, background, title, subtitle = spec
    ink = _readable_on(background)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    unit = height / 800
    draw.text(
        (width / 2, height * 0.40),
        number,
        font=_font(round(320 * unit)),
        fill=ink,
        anchor="mm",
    )
    draw.text(
        (width / 2, height * 0.68),
        title,
        font=_font(round(64 * unit)),
        fill=ink,
        anchor="mm",
    )
    draw.text(
        (width / 2, height * 0.78),
        subtitle,
        font=_font(round(30 * unit)),
        fill=ink,
        anchor="mm",
    )
    return image


HTML_SAMPLE = """<!doctype html>
<meta charset="utf-8">
<title>SlideShow sample</title>
<style>
  html, body { margin: 0; height: 100%; }
  body {
    display: grid; place-content: center; text-align: center;
    font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: linear-gradient(135deg, #2451ff, #323471); color: #fff;
  }
  h1 { font-size: 5vw; margin: 0 0 2vh; }
  p  { font-size: 2vw; margin: 0; opacity: .85; }
  #clock { font-size: 8vw; font-variant-numeric: tabular-nums; margin-top: 4vh; }
</style>
<h1>Hello from SlideShow</h1>
<p>This is a plain HTML file playing as a slide.</p>
<div id="clock"></div>
<script>
  function tick() {
    document.getElementById('clock').textContent =
      new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  tick(); setInterval(tick, 1000);
</script>
"""

URL_SAMPLE = """http://homeassistant.local:8123/lovelace/0
"""

README_SAMPLE = """Starter content for SlideShow
=============================

slides/01..05.jpg
    Five numbered slides. Put them in a playlist and use the Next and Previous
    buttons, or the media_player, to watch it cycle.

hello.html
    A plain HTML page with a live clock, to show that HTML plays as content.

dashboard.url
    A one-line text file containing a web address. SlideShow opens it as a web
    page. Edit it to point at your own Home Assistant dashboard, and remember
    the player has to be logged in or the dashboard has to allow guest access.

To upload: SlideShow web interface, menu Files, then drag this whole ZIP in.
SlideShow unpacks it automatically.
"""


def main() -> int:
    """Write the sample pack and a ZIP of it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default="samples", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    args = parser.parse_args()

    slides_dir = args.output / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for spec in SLIDES:
        path = slides_dir / f"{spec[0]}.jpg"
        _slide(args.width, args.height, spec).save(path, quality=90, optimize=True)
        written.append(path)

    for name, text in (
        ("hello.html", HTML_SAMPLE),
        ("dashboard.url", URL_SAMPLE),
        ("README.txt", README_SAMPLE),
    ):
        path = args.output / name
        path.write_text(text)
        written.append(path)

    archive = args.output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in written:
            zf.write(path, path.relative_to(args.output))

    for path in written:
        print(f"  {path}")
    print(f"\nZIP for upload: {archive} ({archive.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
