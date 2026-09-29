#!/usr/bin/env python3
"""Convert JSON3, SRT, or WebVTT subtitles to a normalized timestamped TSV."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TAG_PATTERN = re.compile(r"<[^>]+>")
VOICE_TAG_PATTERN = re.compile(r"<v(?:\.[^\s>]+)*\s+([^>]+)>", re.IGNORECASE)
INLINE_SPEAKER_PATTERN = re.compile(r"^(?:>>\s*)?([A-Za-z][A-Za-z0-9 .'-]{0,31}):\s+")
TIME_PATTERN = re.compile(
    r"(?:(?P<hours>\d{1,2}):)?(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"(?:[,.](?P<milliseconds>\d{1,3}))?"
)
TIMELINE_PATTERN = re.compile(r"-->")
SENTENCE_END_PATTERN = re.compile(r"[.!?。！？…][\"'”」』)）\]]*$")
CJK_PATTERN = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]")


@dataclass(frozen=True)
class Cue:
    milliseconds: int
    text: str
    duration_ms: int = 0
    speaker_change: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize subtitle cues into source.segments.tsv."
    )
    parser.add_argument("subtitle_file", type=Path, help="SRT, VTT, or JSON3 subtitle file")
    parser.add_argument("-o", "--output", type=Path, help="Output TSV path")
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="Keep consecutive cues whose text is identical",
    )
    parser.add_argument(
        "--no-group",
        action="store_true",
        help="Keep one output row per subtitle cue instead of readable paragraphs",
    )
    parser.add_argument(
        "--target-chars",
        type=int,
        default=600,
        help="Preferred paragraph length; CJK characters count double",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1000,
        help="Hard paragraph length limit used while grouping cues",
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=3.0,
        help="Split paragraphs at pauses longer than this value",
    )
    return parser.parse_args()


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = TAG_PATTERN.sub("", value)
    value = value.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def format_timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


def parse_timestamp(value: str) -> int:
    match = TIME_PATTERN.search(value)
    if not match:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    milliseconds = int(match.group("milliseconds") or "0")
    if len(match.group("milliseconds") or "") == 1:
        milliseconds *= 100
    elif len(match.group("milliseconds") or "") == 2:
        milliseconds *= 10
    return (
        int(match.group("hours") or "0") * 3_600_000
        + int(match.group("minutes")) * 60_000
        + int(match.group("seconds")) * 1000
        + milliseconds
    )


def parse_json3(path: Path) -> list[Cue]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    cues: list[Cue] = []
    for event in payload.get("events", []):
        segments = event.get("segs")
        if not segments:
            continue
        raw_text = clean_text("".join(segment.get("utf8", "") for segment in segments))
        speaker_change = any(segment.get("isSpeakerChange") for segment in segments)
        if raw_text.startswith(">>"):
            speaker_change = True
        text = re.sub(r"^>>\s*", "", raw_text)
        if text:
            cues.append(
                Cue(
                    milliseconds=int(event.get("tStartMs", 0)),
                    text=text,
                    duration_ms=int(event.get("dDurationMs", 0)),
                    speaker_change=speaker_change,
                )
            )
    return cues


def text_blocks(path: Path) -> list[tuple[str, list[str]]]:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[tuple[str, list[str]]] = []
    for raw_block in re.split(r"\n{2,}", content):
        lines = [line.strip("\ufeff") for line in raw_block.splitlines() if line.strip()]
        if not lines:
            continue
        timeline_index = next(
            (index for index, line in enumerate(lines) if TIMELINE_PATTERN.search(line)),
            None,
        )
        if timeline_index is None:
            continue
        blocks.append((lines[timeline_index], lines[timeline_index + 1 :]))
    return blocks


def parse_text_subtitle(path: Path) -> list[Cue]:
    cues: list[Cue] = []
    previous_speaker = None
    for timeline, lines in text_blocks(path):
        start_text, end_text = timeline.split("-->", 1)
        start = parse_timestamp(start_text.strip())
        end = parse_timestamp(end_text.strip())
        raw_text = " ".join(lines)
        voice_match = VOICE_TAG_PATTERN.search(raw_text)
        inline_match = INLINE_SPEAKER_PATTERN.match(clean_text(raw_text))
        speaker = (
            clean_text(voice_match.group(1))
            if voice_match
            else clean_text(inline_match.group(1))
            if inline_match
            else None
        )
        text = clean_text(raw_text)
        if speaker and not text.startswith(f"{speaker}:"):
            text = f"{speaker}: {text}"
        if text:
            cues.append(
                Cue(
                    milliseconds=start,
                    text=text,
                    duration_ms=max(0, end - start),
                    speaker_change=bool(
                        text.startswith(">>") or (speaker and speaker != previous_speaker)
                    ),
                )
            )
            if speaker:
                previous_speaker = speaker
    return cues


def remove_consecutive_duplicates(cues: list[Cue]) -> list[Cue]:
    result: list[Cue] = []
    previous_text = None
    for cue in cues:
        if cue.text == previous_text:
            continue
        result.append(cue)
        previous_text = cue.text
    return result


def text_weight(text: str) -> int:
    return len(text) + len(CJK_PATTERN.findall(text))


def group_cues(
    cues: list[Cue],
    target_chars: int,
    max_chars: int,
    max_gap_ms: int,
) -> list[Cue]:
    """Group cues into paragraphs, preferring to split at sentence ends once past target size."""
    if target_chars < 1 or max_chars < target_chars:
        raise ValueError("Require 1 <= target_chars <= max_chars")
    if max_gap_ms < 0:
        raise ValueError("max_gap_ms must not be negative")

    groups: list[list[Cue]] = []
    current: list[Cue] = []
    current_chars = 0
    previous_end = 0
    for cue in cues:
        gap = cue.milliseconds - previous_end if current else 0
        weight = text_weight(cue.text)
        at_sentence_end = bool(current and SENTENCE_END_PATTERN.search(current[-1].text))
        should_split = bool(
            current
            and (
                cue.speaker_change
                or gap > max_gap_ms
                or (current_chars >= target_chars and at_sentence_end)
                or current_chars + 1 + weight > max_chars
            )
        )
        if should_split:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(cue)
        current_chars += (1 if current_chars else 0) + weight
        previous_end = max(previous_end, cue.milliseconds + cue.duration_ms)
    if current:
        groups.append(current)

    return [
        Cue(
            milliseconds=group[0].milliseconds,
            text=" ".join(cue.text for cue in group),
            duration_ms=max(
                0,
                group[-1].milliseconds + group[-1].duration_ms - group[0].milliseconds,
            ),
        )
        for group in groups
    ]


def load_cues(path: Path) -> list[Cue]:
    suffix = path.suffix.lower()
    if suffix == ".json3":
        cues = parse_json3(path)
    elif suffix in {".srt", ".vtt"}:
        cues = parse_text_subtitle(path)
    else:
        raise ValueError("Subtitle file must be .srt, .vtt, or .json3")
    return sorted(cues, key=lambda cue: cue.milliseconds)


def default_output(subtitle_file: Path) -> Path:
    if subtitle_file.parent.name == "subtitles":
        return subtitle_file.parent.parent.parent / "source.segments.tsv"
    return subtitle_file.with_suffix(".segments.tsv")


def convert(
    subtitle_file: Path,
    output: Path | None = None,
    keep_duplicates: bool = False,
    group: bool = True,
    target_chars: int = 600,
    max_chars: int = 1000,
    max_gap_seconds: float = 3.0,
) -> tuple[Path, int]:
    """Normalize one subtitle file into a TSV timeline; return (path, row count)."""
    cues = load_cues(subtitle_file)
    if not keep_duplicates:
        cues = remove_consecutive_duplicates(cues)
    if not cues:
        raise ValueError("No subtitle cues found.")
    if group:
        cues = group_cues(cues, target_chars, max_chars, round(max_gap_seconds * 1000))
    output = (output or default_output(subtitle_file)).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{index:03d}\t{format_timestamp(cue.milliseconds)}\t{cue.text}"
        for index, cue in enumerate(cues, start=1)
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output, len(cues)


def main() -> int:
    args = parse_args()
    subtitle_file = args.subtitle_file.expanduser().resolve()
    if not subtitle_file.is_file():
        print(f"Subtitle file not found: {subtitle_file}", file=sys.stderr)
        return 2
    try:
        output, count = convert(
            subtitle_file,
            args.output,
            keep_duplicates=args.keep_duplicates,
            group=not args.no_group,
            target_chars=args.target_chars,
            max_chars=args.max_chars,
            max_gap_seconds=args.max_gap_seconds,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Could not convert subtitles: {exc}", file=sys.stderr)
        return 1
    print(f"{output} ({count} cues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
