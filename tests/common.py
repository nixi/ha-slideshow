"""Helpers shared by the SlideShow tests."""

import re

from .const import BASE, LAYOUTS, SECONDS_SINCE_USER_ACTIVITY, ZONES


def mock_status_reads(aioclient_mock, base: str | None = BASE) -> None:
    """Answer the reads polled alongside /ajax/deviceInfo.

    With ``base`` set to ``None`` the endpoints match any address, for tests
    that mock the rest by pattern.
    """

    def url(path: str):
        return re.compile(rf"/ajax/{path}") if base is None else f"{base}/ajax/{path}"

    aioclient_mock.get(
        url("layout/get"), json={"success": True, "result": {"layouts": LAYOUTS}}
    )
    aioclient_mock.get(
        url("zone/content"), json={"success": True, "result": {"zones": ZONES}}
    )
    aioclient_mock.get(
        url("lastUserActivity"),
        json={
            "success": True,
            "result": {"secondsSinceLastActivity": SECONDS_SINCE_USER_ACTIVITY},
        },
    )
