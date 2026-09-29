#!/usr/bin/env python3
"""Create a consistently structured episode directory, auto-filling metadata from the URL."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ytdlp_common  # noqa: E402


SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_DIR.parents[2]
DEFAULT_EPISODES_DIR = PROJECT_ROOT / "episodes"
CHINESE_PLATFORMS = {"Bilibili", "Douyin", "Xiaohongshu"}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")[:60].strip("-")


def url_video_id(url: str) -> str:
    parsed = urlparse(url)
    return dict(parse_qsl(parsed.query)).get("v") or parsed.path.rstrip("/").rsplit("/", 1)[-1]


def next_episode_number(episodes_dir: Path) -> int:
    numbers = []
    if episodes_dir.exists():
        for path in episodes_dir.iterdir():
            match = re.match(r"^(\d+)-", path.name)
            if path.is_dir() and match:
                numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def clock(seconds: object) -> str:
    try:
        total = int(float(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "unknown"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the next episode directory and metadata.yaml.")
    parser.add_argument("title", nargs="?", help="Original video title; fetched from --url when omitted")
    parser.add_argument("--url", default="unknown", help="Original video URL")
    parser.add_argument("--slug", help="Episode slug; otherwise derived from the title")
    parser.add_argument("--platform", help="YouTube, Bilibili, Douyin, Vimeo, etc.")
    parser.add_argument("--channel", help="Channel or creator")
    parser.add_argument("--duration", help="Duration such as 01:31:52")
    parser.add_argument("--source-language", help="Source language code; detected when possible")
    parser.add_argument("--target-language", default="zh-CN", help="Target language code")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not query yt-dlp for title, channel, duration, description, and chapters",
    )
    parser.add_argument("--episodes-dir", type=Path, default=DEFAULT_EPISODES_DIR)
    parser.add_argument("--episode-number", type=int, help="Explicit episode number")
    ytdlp_common.add_auth_arguments(parser)
    return parser.parse_args()


def fetch_info(args: argparse.Namespace) -> dict | None:
    executable = ytdlp_common.executable()
    errors = ""
    for client in ytdlp_common.player_clients(args.url, args.player_client):
        command = [
            executable, "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings",
            *ytdlp_common.auth_args(args.cookies_from_browser, args.cookies),
            *ytdlp_common.client_args(client), args.url,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        errors = result.stderr.strip()
    print(f"Could not fetch video info; continuing without it.\n{errors[-800:]}", file=sys.stderr)
    return None


def trim_info(info: dict) -> dict:
    """Keep only the fields useful as translation context (description, chapters, tags)."""
    upload_date = str(info.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", upload_date):
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "webpage_url": info.get("webpage_url"),
        "extractor": info.get("extractor_key"),
        "duration": clock(info.get("duration")),
        "upload_date": upload_date or None,
        "language": info.get("language"),
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "chapters": [
            {"start": clock(chapter.get("start_time")), "title": chapter.get("title")}
            for chapter in info.get("chapters") or []
        ],
        "subtitle_languages": sorted((info.get("subtitles") or {}).keys()),
        "automatic_caption_languages": sorted(
            key for key in (info.get("automatic_captions") or {})
            if key.endswith("-orig") or key.startswith("ai-")
        ),
        "description": info.get("description") or "",
    }


def detect_language(explicit: str | None, info: dict | None, platform: str) -> str:
    if explicit:
        return explicit
    language = str((info or {}).get("language") or "")
    if language.startswith("zh"):
        return "zh-CN"
    if language:
        return language.split("-")[0]
    return "zh-CN" if platform in CHINESE_PLATFORMS else "en"


def main() -> int:
    args = parse_args()
    episodes_dir = args.episodes_dir.expanduser().resolve()
    number = args.episode_number or next_episode_number(episodes_dir)
    if number < 1:
        print("Episode number must be positive.", file=sys.stderr)
        return 2

    info = None
    if args.url != "unknown" and not args.no_fetch:
        try:
            raw = fetch_info(args)
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            raw = None
        info = trim_info(raw) if raw else None
    title = args.title or (info or {}).get("title")
    if not title:
        print("Title is required when video info cannot be fetched.", file=sys.stderr)
        return 2

    platform = args.platform or ytdlp_common.platform_for(args.url)
    source_language = detect_language(args.source_language, info, platform)
    target = args.target_language
    is_foreign_language = bool(source_language) and source_language != target
    video_id = str((info or {}).get("id") or url_video_id(args.url))
    slug = slugify(args.slug or title) or slugify(video_id) or "episode"
    episode_dir = episodes_dir / f"{number:03d}-{slug}"
    if episode_dir.exists():
        print(f"Episode already exists: {episode_dir}", file=sys.stderr)
        return 1
    (episode_dir / "source" / "subtitles").mkdir(parents=True)
    (episode_dir / "drafts").mkdir(parents=True)
    if info:
        (episode_dir / "source" / "video.info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    target_draft = f"drafts/transcript.{target}.annotated.txt"
    source_draft = f"drafts/transcript.{source_language}.annotated.txt"
    lines = [
        f"episode: {number}",
        f"slug: {yaml_string(slug)}",
        f"title: {yaml_string(title)}",
        'translated_title: ""',
        f"url: {yaml_string(args.url)}",
        f"platform: {yaml_string(platform)}",
        f"channel: {yaml_string(args.channel or (info or {}).get('channel') or 'unknown')}",
        f"upload_date: {yaml_string((info or {}).get('upload_date') or 'unknown')}",
        f"duration: {yaml_string(args.duration or (info or {}).get('duration') or 'unknown')}",
        f"source_language: {yaml_string(source_language)}",
        f"target_language: {yaml_string(target)}",
        'caption_source: "unknown"',
        'caption_type: "unknown"',
        'speaker_attribution: "inferred"',
        'status: "initialized"',
        "format_version: 3",
        "tags:",
        "people:",
        "quality_review:",
        "  full_context_read: false",
        "  caption_errors_corrected: false",
        "  speaker_attribution_reviewed: false",
        "  advertisements_folded: false",
        "  translation_reviewed: false",
        "files:",
        '  source_segments: "source.segments.tsv"',
    ]
    if info:
        lines.append('  video_info: "source/video.info.json"')
    lines += [
        *([f'  source_transcript: "transcript.{source_language}.md"'] if is_foreign_language else []),
        f'  localized_transcript: "transcript.{target}.md"',
        f'  correction_log: "corrections.{target}.md"',
        "  drafts:",
        *([f'    - "{source_draft}"'] if is_foreign_language else []),
        f'    - "{target_draft}"',
        "rendered_from:",
        *([f'  source_transcript: "{source_draft}"'] if is_foreign_language else []),
        f'  localized_transcript: "{target_draft}"',
        '  source_timeline: "source.segments.tsv"',
        "",
    ]
    (episode_dir / "metadata.yaml").write_text("\n".join(lines), encoding="utf-8")
    print(episode_dir)
    if info:
        chapters = len(info["chapters"])
        print(f"Fetched info: {info['title']} | {info['channel']} | {info['duration']} | {chapters} chapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
