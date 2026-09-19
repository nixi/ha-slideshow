#!/usr/bin/env python3
"""Exercise the API client against a real SlideShow player.

Reads every endpoint the integration uses, performs one deliberately no-op write
(setting the volume to the value it already has) and checks both error paths.

Usage:
    SLIDESHOW_HOST=192.168.1.100 SLIDESHOW_PORT=8080 \
    SLIDESHOW_USER=admin SLIDESHOW_PASS=admin \
    python scripts/live_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import aiohttp

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "slideshow"
sys.path.insert(0, str(COMPONENT))

from api import (  # noqa: E402  (path is set up above)
    SlideshowAuthError,
    SlideshowClient,
    SlideshowConnectionError,
)

HOST = os.environ.get("SLIDESHOW_HOST")
PORT = int(os.environ.get("SLIDESHOW_PORT", "8080"))
USER = os.environ.get("SLIDESHOW_USER", "admin")
PASSWORD = os.environ.get("SLIDESHOW_PASS", "admin")
UNREACHABLE = os.environ.get("SLIDESHOW_UNREACHABLE_HOST", "192.0.2.1")


async def main() -> int:
    """Run the checks and return a process exit code."""
    if not HOST:
        print("Set SLIDESHOW_HOST (and optionally PORT/USER/PASS).")
        return 2

    failures: list[str] = []
    async with aiohttp.ClientSession() as session:
        client = SlideshowClient(session, HOST, PORT, USER, PASSWORD)

        info = await client.async_get_device_info()
        print(
            f"  deviceInfo       -> {info.get('deviceName')!r} "
            f"v{info.get('softwareVersion')} paused={info.get('paused')} "
            f"screen={info.get('screenPower')} vol={info.get('currentVolume')}"
        )
        if not info.get("deviceId"):
            failures.append("deviceInfo did not include a deviceId")

        print(f"  zones            -> {await client.async_get_zones()}")
        displays = (await client.async_get_display_info()).get("displays")
        print(f"  displayInfo      -> {displays}")
        print(f"  volume/get       -> {await client.async_get_volume()}%")
        content = await client.async_get_content()
        print(f"  content/get      -> {len(content)} entries")
        syncs = await client.async_get_last_synchronizations()
        print(f"  synchronize/last -> {syncs}")

        shot = await client.async_get_screenshot()
        is_jpeg = shot[:2] == b"\xff\xd8"
        print(f"  screenshot       -> {len(shot)} bytes, JPEG={is_jpeg}")
        if shot[:2] != b"\xff\xd8":
            failures.append("screenshot was not a JPEG")

        current = info.get("currentVolume")
        if current is not None:
            echoed = await client.async_set_volume(current)
            print(f"  volume/set({current})   -> {echoed} (no-op)")
            if echoed != current:
                failures.append(
                    f"no-op volume write changed the volume: {current} -> {echoed}"
                )

        bad = SlideshowClient(session, HOST, PORT, USER, "definitely-not-the-password")
        try:
            await bad.async_get_device_info()
        except SlideshowAuthError:
            print("  bad password     -> SlideshowAuthError (correct)")
        else:
            failures.append("a bad password did not raise SlideshowAuthError")

        unreachable = SlideshowClient(session, UNREACHABLE, PORT, USER, PASSWORD)
        try:
            await unreachable.async_get_device_info()
        except SlideshowConnectionError:
            print("  unreachable host -> SlideshowConnectionError (correct)")
        except Exception as err:
            failures.append(f"unreachable host raised {type(err).__name__}: {err}")
        else:
            failures.append("unreachable host did not raise")

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(" -", failure)
        return 1

    print("\nAll live checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
