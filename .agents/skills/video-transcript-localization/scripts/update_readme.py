#!/usr/bin/env python3
"""Regenerate the episode catalog in README.md and README.en.md from episodes/*/metadata.yaml."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_markdown import meta_str, read_metadata  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SITE_URL = "https://yishibakaien.github.io/video-transcript-localization"
START, END = "<!-- episodes:start -->", "<!-- episodes:end -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="Project root with README files")
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help="GitHub Pages site URL used for episode links",
    )
    return parser.parse_args()


def cell(value: str) -> str:
    return value.replace("|", "\\|")


def episode_rows(root: Path, zh: bool, site_url: str = DEFAULT_SITE_URL) -> list[str]:
    rows = []
    for episode_dir in sorted(path for path in (root / "episodes").glob("[0-9]*-*") if path.is_dir()):
        metadata = read_metadata(episode_dir / "metadata.yaml")
        target = meta_str(metadata, "target_language") or "zh-CN"
        localized = episode_dir / f"transcript.{target}.md"
        reading_page = episode_dir / "index.html"
        if not localized.is_file() or not reading_page.is_file():
            continue
        number = metadata.get("episode") or episode_dir.name.split("-", 1)[0]
        title = (meta_str(metadata, "translated_title") if zh else "") or meta_str(metadata, "title")
        relative_path = quote(reading_page.relative_to(root).as_posix(), safe="/")
        link = f"{site_url.rstrip('/')}/{relative_path}"
        rows.append(
            f"| {int(number):03d} | [{cell(title)}]({link}) | {cell(meta_str(metadata, 'channel'))} | "
            f"{cell(meta_str(metadata, 'platform'))} | {meta_str(metadata, 'duration')} |"
        )
    return rows


def catalog(root: Path, zh: bool, site_url: str = DEFAULT_SITE_URL) -> str:
    rows = episode_rows(root, zh, site_url)
    if not rows:
        return "_暂无已完成的视频。_" if zh else "_No completed videos yet._"
    header = (
        "| # | 标题 | 频道 | 平台 | 时长 |" if zh
        else "| # | Title | Channel | Platform | Duration |"
    )
    return "\n".join([header, "|:---|:---|:---|:---|:---|", *rows])


def update(path: Path, content: str) -> bool:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise ValueError(f"{path}: missing {START} / {END} markers")
    updated = pattern.sub(lambda _: f"{START}\n{content}\n{END}", text, count=1)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    return updated != text


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    try:
        for name, zh in (("README.md", True), ("README.en.md", False)):
            changed = update(root / name, catalog(root, zh, args.site_url))
            print(f"{root / name}: {'updated' if changed else 'unchanged'}")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
