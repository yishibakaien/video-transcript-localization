#!/usr/bin/env python3
"""Download or import raw subtitles for one episode, then normalize them to source.segments.tsv."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subtitle_to_tsv  # noqa: E402
import ytdlp_common  # noqa: E402


SUBTITLE_SUFFIXES = {".json3", ".srt", ".vtt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a subtitle file or download subtitles with yt-dlp."
    )
    parser.add_argument("episode_dir", type=Path, help="Episode directory")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--url", help="Video URL; otherwise read url from metadata.yaml")
    source.add_argument("--subtitle-file", type=Path, help="Existing SRT, VTT, or JSON3 file")
    parser.add_argument(
        "--source-language",
        help="Expected source language code; defaults to source_language in metadata.yaml",
    )
    parser.add_argument(
        "--sub-format",
        default="json3/srt/vtt/best",
        help="Preferred yt-dlp subtitle formats in priority order",
    )
    parser.add_argument(
        "--output-name",
        help="Destination filename for --subtitle-file; defaults to the source filename",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Do not write source.segments.tsv after acquiring the subtitle",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing source.segments.tsv",
    )
    ytdlp_common.add_auth_arguments(parser)
    return parser.parse_args()


def read_metadata_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith(('"', "'")):
            try:
                return str(json.loads(value))
            except json.JSONDecodeError:
                return value.strip("\"'")
        return value
    return None


def subtitle_files(directory: Path) -> set[Path]:
    return {
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUBTITLE_SUFFIXES
    }


def yt_dlp_languages(language: str) -> str:
    if language.startswith("zh"):
        # ai-zh is Bilibili's AI-generated Chinese track.
        candidates = ["zh-orig", "zh", "zh-Hans", "zh-CN", "ai-zh", "zh.*"]
    else:
        base = language.split("-")[0]
        candidates = [f"{language}-orig", language, f"{base}-orig", base, f"ai-{base}", f"{base}.*"]
    return ",".join(dict.fromkeys(candidates))


def subtitle_score(path: Path, source_language: str, human: set[str]) -> tuple[int, int, str]:
    language = track_language(path)
    base = source_language.split("-")[0]
    if language in human:
        language_rank = 0
    elif language in (f"{source_language}-orig", f"{base}-orig"):
        language_rank = 1
    elif language in (source_language, base):
        language_rank = 2
    elif language.startswith(base) or language == f"ai-{base}":
        language_rank = 3
    else:
        language_rank = 4
    format_rank = {".json3": 0, ".srt": 1, ".vtt": 2}.get(path.suffix.lower(), 3)
    return language_rank, format_rank, path.name


def track_language(path: Path) -> str:
    return path.name[: -len(path.suffix)].rsplit(".", 1)[-1]


def human_languages(episode_dir: Path) -> set[str]:
    info_path = episode_dir / "source" / "video.info.json"
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {lang for lang in info.get("subtitle_languages", []) if not lang.startswith("ai-")}


def set_metadata_if_unknown(path: Path, key: str, value: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf'^{re.escape(key)}:[ \t]*(?:"unknown"|unknown|"")?[ \t]*$', re.MULTILINE)
    updated, count = pattern.subn(f"{key}: {json.dumps(value, ensure_ascii=False)}", text, count=1)
    if count:
        path.write_text(updated, encoding="utf-8")


def import_subtitle(args: argparse.Namespace, subtitles_dir: Path) -> Path:
    source = args.subtitle_file.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Subtitle file not found: {source}")
    if source.suffix.lower() not in SUBTITLE_SUFFIXES:
        raise ValueError("Subtitle file must be .srt, .vtt, or .json3")

    destination = subtitles_dir / (args.output_name or source.name)
    if destination.resolve() == source:
        return destination
    if destination.exists():
        if destination.read_bytes() == source.read_bytes():
            return destination
        raise FileExistsError(f"Destination already exists with different content: {destination}")
    shutil.copy2(source, destination)
    return destination


def download_subtitles(
    args: argparse.Namespace, subtitles_dir: Path, url: str, human: set[str]
) -> Path:
    executable = ytdlp_common.executable()
    before = subtitle_files(subtitles_dir)
    output_template = str(subtitles_dir / "%(id)s.%(ext)s")
    base_command = [
        executable,
        "--skip-download",
        "--no-playlist",
        "--sleep-requests",
        "1",
        "--sub-langs",
        yt_dlp_languages(args.source_language),
        "--sub-format",
        args.sub_format,
        "--output",
        output_template,
        *ytdlp_common.auth_args(args.cookies_from_browser, args.cookies),
    ]
    player_clients = ytdlp_common.player_clients(url, args.player_client)
    failures: list[str] = []
    for position, player_client in enumerate(player_clients):
        command = base_command + ytdlp_common.client_args(player_client)
        command.extend(["--write-subs", "--write-auto-subs", url])
        result = subprocess.run(command, check=False)
        created = subtitle_files(subtitles_dir) - before
        if created:
            return min(created, key=lambda path: subtitle_score(path, args.source_language, human))
        failures.append(f"{player_client}: exit {result.returncode}")
        if position + 1 < len(player_clients):
            print(
                f"No subtitle downloaded with player client {player_client}; "
                f"retrying with {player_clients[position + 1]}.",
                file=sys.stderr,
            )

    raise RuntimeError(
        "No subtitles were downloaded "
        f"({', '.join(failures)}). Check tracks with `yt-dlp --list-subs {json.dumps(url)}`; "
        "for Bilibili/Douyin retry with --cookies-from-browser, or fall back to ASR "
        "(see references/platforms.md), or provide --subtitle-file."
    )


def main() -> int:
    args = parse_args()
    episode_dir = args.episode_dir.expanduser().resolve()
    subtitles_dir = episode_dir / "source" / "subtitles"
    if not episode_dir.is_dir():
        print(f"Episode directory not found: {episode_dir}", file=sys.stderr)
        return 2
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = episode_dir / "metadata.yaml"
    args.source_language = (
        args.source_language or read_metadata_value(metadata_path, "source_language") or "en"
    )

    try:
        human = human_languages(episode_dir)
        if args.subtitle_file:
            result = import_subtitle(args, subtitles_dir)
            caption_type, caption_source = "supplied", f"Supplied file {result.name}"
        else:
            url = args.url or read_metadata_value(metadata_path, "url")
            if not url or url == "unknown":
                raise RuntimeError("No URL supplied and no usable URL found in metadata.yaml.")
            result = download_subtitles(args, subtitles_dir, url, human)
            language = track_language(result)
            caption_type = "human" if language in human else "automatic"
            kind = "creator/human captions" if caption_type == "human" else "auto-generated captions"
            caption_source = f"{ytdlp_common.platform_for(url)} {kind}, {language}"
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(result)
    set_metadata_if_unknown(metadata_path, "caption_type", caption_type)
    set_metadata_if_unknown(metadata_path, "caption_source", caption_source)
    if args.no_normalize:
        return 0
    timeline = episode_dir / "source.segments.tsv"
    if timeline.exists() and not args.force:
        print(f"Kept existing {timeline}; pass --force to regenerate it.", file=sys.stderr)
        return 0
    try:
        output, count = subtitle_to_tsv.convert(result, timeline)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Could not normalize subtitles: {exc}", file=sys.stderr)
        return 1
    print(f"{output} ({count} segments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
