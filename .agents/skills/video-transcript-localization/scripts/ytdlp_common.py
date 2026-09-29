"""Shared yt-dlp helpers for episode scripts."""

from __future__ import annotations

import shutil
from urllib.parse import urlparse


YOUTUBE_FALLBACK_CLIENTS = ("default", "android_vr")
PLATFORM_NAMES = {
    "youtube": "YouTube",
    "youtu.be": "YouTube",
    "bilibili": "Bilibili",
    "b23.tv": "Bilibili",
    "douyin": "Douyin",
    "tiktok": "TikTok",
    "vimeo": "Vimeo",
    "xiaohongshu": "Xiaohongshu",
}


def executable() -> str:
    path = shutil.which("yt-dlp")
    if not path:
        raise RuntimeError(
            "yt-dlp is not installed. Install it with `brew install yt-dlp` or "
            "`python3 -m pip install --user -U yt-dlp`, or pass --subtitle-file."
        )
    return path


def platform_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for key, name in PLATFORM_NAMES.items():
        if key in host:
            return name
    return "unknown"


def is_youtube(url: str) -> bool:
    return platform_for(url) == "YouTube"


def player_clients(url: str, override: list[str] | None) -> list[str]:
    if override:
        return override
    return list(YOUTUBE_FALLBACK_CLIENTS) if is_youtube(url) else ["default"]


def client_args(client: str) -> list[str]:
    return [] if client == "default" else ["--extractor-args", f"youtube:player_client={client}"]


def auth_args(cookies_from_browser: str | None, cookies: str | None) -> list[str]:
    """Use the user's own logged-in session; never used to bypass access controls."""
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]
    if cookies:
        return ["--cookies", cookies]
    return []


def add_auth_arguments(parser) -> None:
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="Reuse your own browser login (chrome, safari, firefox, edge); needed for many Bilibili/Douyin videos",
    )
    parser.add_argument("--cookies", metavar="FILE", help="Netscape cookies.txt exported from your own login")
    parser.add_argument(
        "--player-client",
        action="append",
        help="YouTube player client fallback; repeat to override `default,android_vr`",
    )
