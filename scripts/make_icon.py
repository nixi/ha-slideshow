#!/usr/bin/env python3
"""Render the integration icon at the sizes the Home Assistant brands repo wants.

The palette is taken from SlideShow's own logo: a #2451FF to #323471 gradient
with a #2D2D2D stand.

Usage:
    python scripts/make_icon.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
BLUE = (36, 81, 255)
NAVY = (50, 52, 113)
DARK = (45, 45, 45)


def _linear_gradient(size: tuple[int, int]) -> Image.Image:
    """Return a diagonal gradient from the brand blue to the brand navy."""
    width, height = size
    gradient = Image.new("RGB", size)
    pixels = gradient.load()
    longest = (width - 1) + (height - 1)
    for x in range(width):
        for y in range(height):
            t = (x + y) / longest
            pixels[x, y] = (
                round(BLUE[0] + (NAVY[0] - BLUE[0]) * t),
                round(BLUE[1] + (NAVY[1] - BLUE[1]) * t),
                round(BLUE[2] + (NAVY[2] - BLUE[2]) * t),
            )
    return gradient


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    """Return an L-mode mask holding one rounded rectangle."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255
    )
    return mask


def build() -> Image.Image:
    """Draw the icon: a display showing a stack of slides, on a stand."""
    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    # The display body, filled with the brand gradient.
    body = (64, 120, 960, 688)
    body_size = (body[2] - body[0], body[3] - body[1])
    icon.paste(
        _linear_gradient(body_size), (body[0], body[1]), _rounded_mask(body_size, 56)
    )

    # Three slides stacked on the screen, peeking up and to the right.
    slides = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(slides)
    for offset, alpha in ((80, 90), (40, 155), (0, 255)):
        left, top = 282 + offset, 254 - offset
        draw.rounded_rectangle(
            (left, top, left + 460, top + 300),
            radius=26,
            fill=(255, 255, 255, alpha),
        )
    # Keep the slides inside the screen's rounded bezel.
    screen = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(screen).rounded_rectangle(
        (body[0] + 40, body[1] + 40, body[2] - 40, body[3] - 40), radius=30, fill=255
    )
    icon.paste(slides, (0, 0), Image.composite(slides.getchannel("A"), screen, screen))

    # Stand.
    stand = ImageDraw.Draw(icon)
    stand.rectangle((452, 688, 572, 762), fill=(*DARK, 255))
    stand.rounded_rectangle((344, 762, 680, 820), radius=28, fill=(*DARK, 255))

    # Trim to the drawn content and recentre on a square canvas.
    bbox = icon.getbbox()
    content = icon.crop(bbox)
    side = max(content.size) + 80
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(
        content,
        ((side - content.width) // 2, (side - content.height) // 2),
    )
    return square


def main() -> int:
    """Write icon.png and icon@2x.png."""
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "brands")
    out.mkdir(parents=True, exist_ok=True)
    icon = build()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        icon.resize((size, size), Image.LANCZOS).save(out / name, optimize=True)
        print(f"wrote {out / name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
