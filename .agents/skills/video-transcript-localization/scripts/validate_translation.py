#!/usr/bin/env python3
"""Verify timestamp coverage, speaker labels, and folded ads in a rendered transcript."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TIMESTAMP = r"\[\d{2}:\d{2}:\d{2}\]"
TSV_TIMESTAMP_PATTERN = re.compile(rf"^{TIMESTAMP}$")
MARKDOWN_TIMESTAMP_PATTERN = re.compile(rf"^<!--\s*(?:ts:\s*)?({TIMESTAMP})\s*-->$")
# Speaker line rendered as `<sub>Name · [HH:MM:SS](link)</sub><br>`; a time-only line means no label.
LABEL_PATTERN = re.compile(r"^(?:>\s*)?<sub>(.+?) · .*</sub><br>$")
AD_ANCHOR_PATTERN = re.compile(r'^<a id="ad-(\d{2})-(\d{2})-(\d{2})"></a>$')
FRONT_MATTER_REQUIRED_FIELDS = (
    "document_type", "document_role", "language", "episode", "slug", "title", "url",
    "platform", "channel", "duration", "source_language", "target_language", "caption_source",
    "caption_type", "speaker_attribution", "contains_ads", "ad_break_count", "ad_segment_count",
    "status", "format_version", "tags", "people", "quality_review", "files",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a rendered transcript against the source timeline.")
    parser.add_argument("source_tsv", type=Path, help="Normalized source.segments.tsv")
    parser.add_argument("transcript", type=Path, help="Rendered transcript.<lang>.md")
    parser.add_argument("--allow-unlabeled", action="store_true", help="Skip speaker-label checks")
    return parser.parse_args()


def read_source_timestamps(path: Path) -> list[str]:
    timestamps = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        columns = line.split("\t")
        if len(columns) < 3 or not TSV_TIMESTAMP_PATTERN.fullmatch(columns[1].strip()):
            raise ValueError(f"{path}:{line_number}: expected `index<TAB>[HH:MM:SS]<TAB>text`")
        timestamps.append(columns[1].strip())
    if not timestamps:
        raise ValueError(f"{path}: no source timestamps found")
    return timestamps


def read_front_matter(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line[:1].isspace():
            continue
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip().strip("\"'")
    return result


def validate(source_tsv: Path, transcript: Path, allow_unlabeled: bool = False) -> tuple[list[str], str]:
    try:
        source = read_source_timestamps(source_tsv)
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        return [str(exc)], ""

    issues: list[str] = []
    name = transcript.name
    front = read_front_matter(lines)
    missing_fields = [key for key in FRONT_MATTER_REQUIRED_FIELDS if key not in front]
    if missing_fields:
        issues.append("Missing front matter fields: " + ", ".join(missing_fields))

    timestamps: list[str] = []
    unlabelled: list[tuple[str, int]] = []
    pending: list[tuple[str, int]] = []
    ad_timestamps: list[str] = []
    ad_anchors: list[tuple[str, int]] = []
    ad_blocks = 0
    in_ad = False

    def flush_unlabelled() -> None:
        unlabelled.extend(pending)
        pending.clear()

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith('<details class="ad"'):
            flush_unlabelled()
            in_ad, ad_blocks = True, ad_blocks + 1
            continue
        if stripped == "</details>" and in_ad:
            in_ad = False
            continue
        ts_match = MARKDOWN_TIMESTAMP_PATTERN.match(stripped)
        if ts_match:
            timestamps.append(ts_match.group(1))
            if in_ad:
                ad_timestamps.append(ts_match.group(1))
            else:
                pending.append((ts_match.group(1), number))
            continue
        anchor_match = AD_ANCHOR_PATTERN.match(stripped)
        if anchor_match:
            ad_anchors.append((f"[{':'.join(anchor_match.groups())}]", number))
            continue
        label_match = LABEL_PATTERN.match(stripped)
        if label_match and not in_ad:
            if label_match.group(1).strip().startswith("广告"):
                issues.append(f"{name}:{number}: advertisement is not inside a folded <details class=\"ad\"> block")
            pending.clear()
            continue
        if pending and stripped and not stripped.startswith("> [!") and stripped != ">":
            flush_unlabelled()
    flush_unlabelled()
    if in_ad:
        issues.append(f"{name}: unclosed <details class=\"ad\"> block")

    if not timestamps:
        return issues + [f"{name}: no `<!-- ts: [HH:MM:SS] -->` comments found"], ""

    source_set, rendered_set = set(source), set(timestamps)
    missing = sorted(source_set - rendered_set)
    if missing:
        issues.append(f"Missing {len(missing)} source timestamps: {', '.join(missing[:10])}{' ...' if len(missing) > 10 else ''}")
    unexpected = sorted(rendered_set - source_set)
    if unexpected:
        issues.append(f"{len(unexpected)} timestamps absent from the source: {', '.join(unexpected[:10])}")
    if timestamps[0] != source[0]:
        issues.append(f"First timestamp differs: source {source[0]}, rendered {timestamps[0]}")
    if timestamps[-1] != source[-1]:
        issues.append(f"Last timestamp differs: source {source[-1]}, rendered {timestamps[-1]}")
    order = {ts: index for index, ts in enumerate(dict.fromkeys(source))}
    previous = -1
    for ts in timestamps:
        current = order.get(ts, previous)
        if current < previous:
            issues.append(f"{name}: timestamp {ts} is out of order")
            break
        previous = current

    def front_int(key: str) -> int:
        try:
            return int(front.get(key, ""))
        except ValueError:
            issues.append(f"Front matter {key} must be an integer")
            return -1

    contains_ads = front.get("contains_ads", "").lower()
    if contains_ads not in {"true", "false"}:
        issues.append("Front matter contains_ads must be true or false")
    declared_breaks, declared_segments = front_int("ad_break_count"), front_int("ad_segment_count")
    if (contains_ads == "true") != (ad_blocks > 0):
        issues.append(f"contains_ads is {contains_ads} but {ad_blocks} folded ad blocks were found")
    if declared_breaks >= 0 and declared_breaks != ad_blocks:
        issues.append(f"ad_break_count is {declared_breaks} but {ad_blocks} folded ad blocks were found")
    if declared_segments >= 0 and declared_segments != len(ad_timestamps):
        issues.append(f"ad_segment_count is {declared_segments} but {len(ad_timestamps)} ad timestamps were found")
    if len(ad_anchors) != ad_blocks:
        issues.append(f"Expected {ad_blocks} ad anchors, found {len(ad_anchors)}")
    for ts, number in ad_anchors:
        if ts not in source_set:
            issues.append(f"{name}:{number}: ad anchor {ts} is not a source timestamp")

    if not allow_unlabeled:
        for ts, number in unlabelled:
            issues.append(f"{name}:{number}: {ts} has no speaker label")

    summary = (
        f"OK: {len(source_set)} source timestamps covered by {len(timestamps)} rendered blocks; "
        f"{ad_blocks} folded ad breaks ({len(ad_timestamps)} segments)."
    )
    return issues, summary


def main() -> int:
    args = parse_args()
    issues, summary = validate(args.source_tsv, args.transcript, args.allow_unlabeled)
    for issue in issues:
        print(f"ERROR: {issue}", file=sys.stderr)
    if issues:
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
