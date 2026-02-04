"""Update checker for MCBManager."""

import threading
import webbrowser
from dataclasses import dataclass
from typing import Callable, Optional
from urllib import request
import json

from . import __version__

# GitHub repository info
GITHUB_OWNER = "SiderealEmu"
GITHUB_REPO = "MCBManager"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


@dataclass
class UpdateInfo:
    """Information about an available update."""

    current_version: str
    latest_version: str
    release_url: str
    release_notes: str
    is_update_available: bool


def parse_version(version_str: str) -> tuple:
    """Parse a version string into a comparable tuple."""
    # Remove 'v' prefix if present
    version_str = version_str.lstrip("v")

    # Split by dots and convert to integers
    parts = []
    for part in version_str.split("."):
        # Handle versions like "1.0.0-beta"
        numeric_part = ""
        for char in part:
            if char.isdigit():
                numeric_part += char
            else:
                break
        parts.append(int(numeric_part) if numeric_part else 0)

    # Ensure at least 3 parts
    while len(parts) < 3:
        parts.append(0)

    return tuple(parts[:3])


def compare_versions(current: str, latest: str) -> int:
    """Compare two version strings.

    Returns:
        -1 if current < latest (update available)
         0 if current == latest (up to date)
         1 if current > latest (ahead of release)
    """
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)

    if current_tuple < latest_tuple:
        return -1
    elif current_tuple > latest_tuple:
        return 1
    else:
        return 0


def check_for_updates() -> Optional[UpdateInfo]:
    """Check GitHub for the latest release.

    Returns:
        UpdateInfo if check was successful, None if check failed.
    """
    try:
        req = request.Request(
            RELEASES_URL,
            headers={"User-Agent": f"MCBManager/{__version__}"},
        )

        with request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        latest_version = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", RELEASES_PAGE)
        release_notes = data.get("body", "")

        if not latest_version:
            return None

        is_update_available = compare_versions(__version__, latest_version) < 0

        return UpdateInfo(
            current_version=__version__,
            latest_version=latest_version,
            release_url=release_url,
            release_notes=release_notes,
            is_update_available=is_update_available,
        )

    except Exception:
        return None


def check_for_updates_async(callback: Callable[[Optional[UpdateInfo]], None]) -> None:
    """Check for updates in a background thread.

    Args:
        callback: Function to call with the result (called on background thread).
    """

    def _check():
        result = check_for_updates()
        callback(result)

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()


def open_releases_page() -> None:
    """Open the GitHub releases page in the default browser."""
    webbrowser.open(RELEASES_PAGE)


def open_release_url(url: str) -> None:
    """Open a specific release URL in the default browser."""
    webbrowser.open(url)
