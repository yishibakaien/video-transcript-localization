#!/usr/bin/env python3
"""Render annotated transcript drafts as readable, archival Markdown (format v3)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_translation  # noqa: E402


FORMAT_VERSION = 3
TIMESTAMP_PATTERN = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]$")
ENTRY_PATTERN = re.compile(r"^(\[\d{2}:\d{2}:\d{2}\])\s*(.*)$")
SECTION_PATTERN = re.compile(r"^#\s+(.+?)\s*$")
AD_KINDS = {"ad_read", "ad_narrator"}
ALERT_KINDS = {"narrator", "music"}
ROLE_KINDS = {
    "广告口播": "ad_read",
    "广告旁白": "ad_narrator",
    "旁白": "narrator",
    "音乐": "music",
    "主持人": "host",
    "嘉宾": "guest",
    "其他发言者": "other",
    "未知说话人": "unknown",
}
COMPACT_LABEL_PATTERN = re.compile(
    r"^\*{0,2}(?P<role>" + "|".join(ROLE_KINDS) + r")"
    r"(?:｜(?P<fields>[^*：:]*?))?\*{0,2}\s*[：:]\s*(?P<text>.*)$"
)
LANGUAGE_NAMES = {
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "zh": "中文",
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
}
CAPTION_TYPES = {
    "human": "人工字幕",
    "automatic": "平台自动生成字幕",
    "supplied": "用户提供的字幕文件",
    "asr": "语音识别（ASR）",
    "unknown": "未知",
}
ATTRIBUTION = {"inferred": "根据上下文推断", "provided": "字幕自带"}
STATUS = {"initialized": "已初始化", "draft": "草稿", "complete": "已完成"}


@dataclass
class Entry:
    timestamp: str
    kind: str
    label: str
    paragraphs: list[str]
    sponsor: str = ""


@dataclass
class EntryGroup:
    timestamps: list[str]
    kind: str
    label: str
    paragraphs: list[str]
    sponsor: str = ""


@dataclass
class Section:
    title: str
    start: int
    anchor: str
    groups: list[EntryGroup] = field(default_factory=list)
    end: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render annotated drafts as structured Markdown and validate the result."
    )
    parser.add_argument("episode_dir", type=Path, help="Episode directory containing metadata.yaml")
    parser.add_argument(
        "transcripts",
        type=Path,
        nargs="+",
        help="Annotated draft(s) in timeline order; several parts are concatenated",
    )
    parser.add_argument("--language", required=True, help="Document language code, such as zh-CN")
    parser.add_argument("--role", choices=("source", "localized"), required=True)
    parser.add_argument("-o", "--output", type=Path, help="Output Markdown path")
    parser.add_argument(
        "--section-minutes",
        type=int,
        default=10,
        help="Fallback section size when the draft contains no `# heading` lines",
    )
    parser.add_argument(
        "--section-title",
        action="append",
        default=[],
        metavar="HH:MM=TITLE",
        help="Fallback section title for fixed-size sections; repeatable",
    )
    parser.add_argument(
        "--max-turn-chars",
        type=int,
        default=1600,
        help="Maximum characters merged into one consecutive speaker turn",
    )
    parser.add_argument("--corrections", type=Path, help="Correction log appended to the document")
    parser.add_argument(
        "--source-transcript",
        nargs="+",
        type=Path,
        help="Corrected source-language draft(s) used for original/translation comparison in HTML",
    )
    parser.add_argument("--html-output", type=Path, help="Standalone HTML output path")
    parser.add_argument("--no-html", action="store_true", help="Do not render the companion HTML page")
    parser.add_argument("--no-validate", action="store_true", help="Skip post-render validation")
    return parser.parse_args()


# --- metadata -------------------------------------------------------------


def parse_scalar(value: str) -> object:
    value = value.strip()
    if value.startswith(('"', "'")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value.strip("\"'")
    if value in ("true", "false"):
        return value == "true"
    if value == "null":
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def read_metadata(path: Path) -> dict[str, object]:
    """Parse the small YAML subset used by metadata.yaml (two nesting levels)."""
    result: dict[str, object] = {}
    parent: str | None = None
    nested_key: str | None = None
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if not raw_line.startswith(" ") and not raw_line.startswith("-"):
            key, _, value = raw_line.partition(":")
            key, value = key.strip(), value.strip()
            parent, nested_key = (key, None) if not value else (None, None)
            result[key] = parse_scalar(value) if value else None
            continue
        if parent is None:
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        container = result.get(parent)
        if stripped.startswith("- "):
            item = parse_scalar(stripped[2:])
            if isinstance(container, dict) and nested_key and indent >= 4:
                nested = container.get(nested_key)
                if not isinstance(nested, list):
                    nested = []
                    container[nested_key] = nested
                nested.append(item)
                continue
            if not isinstance(container, list):
                container = []
                result[parent] = container
            container.append(item)
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        if not isinstance(container, dict):
            container = {}
            result[parent] = container
        key, value = key.strip(), value.strip()
        container[key] = parse_scalar(value) if value else None
        nested_key = None if value else key
    return result


def meta_str(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    return "" if value in (None, "", "unknown") else str(value)


def meta_map(metadata: dict[str, object], key: str) -> dict[str, object]:
    value = metadata.get(key)
    return {str(k): v for k, v in value.items() if v not in (None, "")} if isinstance(value, dict) else {}


def infer_source_drafts(episode_dir: Path, metadata: dict[str, object]) -> list[Path]:
    """Find the annotated source-language draft(s) for a localized render."""
    source_language = meta_str(metadata, "source_language")
    target_language = meta_str(metadata, "target_language")
    if not source_language or source_language == target_language:
        return []

    drafts_dir = episode_dir / "drafts"
    base_codes = dict.fromkeys([source_language, source_language.split("-")[0]])
    for language_code in base_codes:
        exact = drafts_dir / f"transcript.{language_code}.annotated.txt"
        if exact.is_file():
            return [exact]
        parts = drafts_dir.glob(f"transcript.{language_code}.part-*.txt")
        candidates = sorted(
            parts,
            key=lambda path: int(re.search(r"part-(\d+)", path.name).group(1)),
        )
        if candidates:
            return candidates
    return []


# --- drafts ---------------------------------------------------------------


def parse_timestamp(timestamp: str) -> int:
    match = TIMESTAMP_PATTERN.fullmatch(timestamp)
    if not match:
        raise ValueError(f"Invalid timestamp: {timestamp!r}")
    hours, minutes, seconds = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def clock(seconds: int, with_seconds: bool = True) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if with_seconds else f"{hours:02d}:{minutes:02d}"


def parse_entry(timestamp: str, body: str, host_name: str) -> Entry:
    match = COMPACT_LABEL_PATTERN.match(body)
    if not match:
        return Entry(timestamp, "source", "", [body.strip()])
    role = match.group("role")
    kind = ROLE_KINDS[role]
    fields = [part.strip() for part in (match.group("fields") or "").split("｜") if part.strip()]
    sponsor = ""
    if kind == "ad_read":
        name = fields[0] if fields else host_name
        sponsor = fields[1] if len(fields) > 1 else ""
    elif kind == "ad_narrator":
        name = ""
        sponsor = fields[0] if fields else ""
    else:
        name = " / ".join(fields)
    label = f"{role}｜{name}" if name else role
    return Entry(timestamp, kind, label, [match.group("text").strip()], sponsor)


def read_drafts(
    paths: list[Path], host_name: str
) -> tuple[str, list[Entry], dict[int, str]]:
    """Return (preamble Markdown, entries, {entry index: section title})."""
    preamble: list[str] = []
    entries: list[Entry] = []
    sections: dict[int, str] = {}
    pending_timestamp: str | None = None
    pending_section: str | None = None
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            entry_match = ENTRY_PATTERN.match(stripped)
            section_match = SECTION_PATTERN.match(stripped)
            if entry_match:
                timestamp, body = entry_match.groups()
                if not body.strip():
                    pending_timestamp = timestamp
                    continue
                if pending_section is not None:
                    sections[len(entries)] = pending_section
                    pending_section = None
                entries.append(parse_entry(timestamp, body.strip(), host_name))
                pending_timestamp = None
            elif section_match:
                pending_section = section_match.group(1)
            elif pending_timestamp and stripped:
                if pending_section is not None:
                    sections[len(entries)] = pending_section
                    pending_section = None
                entries.append(parse_entry(pending_timestamp, stripped, host_name))
                pending_timestamp = None
            elif not entries:
                preamble.append(line)
            elif stripped:
                # Continuation line: a new paragraph inside the previous turn.
                entries[-1].paragraphs.append(stripped)
    if not entries:
        raise ValueError("No timestamped transcript entries found in the draft(s)")
    return "\n".join(preamble).strip(), entries, sections


# --- grouping and sections ------------------------------------------------


SENTENCE_END = re.compile(r"[。！？!?…:：.）)」』”\"'\]]$")
CJK = re.compile(r"[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]")


def merge_paragraphs(paragraphs: list[str], incoming: list[str]) -> None:
    """Append paragraphs, re-joining a sentence that a caption boundary split in two."""
    for paragraph in incoming:
        previous = paragraphs[-1] if paragraphs else ""
        if not previous or SENTENCE_END.search(previous):
            paragraphs.append(paragraph)
            continue
        glue = "" if CJK.match(previous[-1]) or CJK.match(paragraph[:1]) else " "
        paragraphs[-1] = previous + glue + paragraph


SENTENCE_PIECE = re.compile(
    r".+?(?:[。！？!?…]+[”」』）)\"']*\s*"
    r"|(?<!Dr)(?<!Mr)(?<!Ms)(?<!St)(?<![A-Z])\.[\"')\]]*\s+(?=[A-Z\"“])"
    r"|$)",
    re.S,
)


def weight(text: str) -> int:
    return len(text) + len(CJK.findall(text))


def split_long(paragraph: str, target: int = 400, threshold: int = 560) -> list[str]:
    """Split a long paragraph at sentence ends into ~200-CJK-character chunks."""
    if weight(paragraph) <= threshold:
        return [paragraph]
    chunks: list[str] = []
    current = ""
    for piece in SENTENCE_PIECE.findall(paragraph):
        current += piece
        if weight(current) >= target:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        if chunks and weight(current) < target // 3:
            glue = "" if CJK.match(chunks[-1][-1]) else " "
            chunks[-1] = chunks[-1] + glue + current.strip()
        else:
            chunks.append(current.strip())
    return chunks or [paragraph]


def readable_paragraphs(paragraphs: list[str]) -> list[str]:
    return [chunk for paragraph in paragraphs for chunk in split_long(paragraph)]


def group_entries(entries: list[Entry], breaks: set[int], max_chars: int) -> tuple[list[EntryGroup], list[int]]:
    """Merge consecutive same-speaker entries; return groups and each group's first entry index."""
    groups: list[EntryGroup] = []
    starts: list[int] = []
    for index, entry in enumerate(entries):
        if groups and index not in breaks:
            current = groups[-1]
            size = sum(len(p) for p in current.paragraphs) + sum(len(p) for p in entry.paragraphs)
            if (
                current.kind == entry.kind
                and current.label == entry.label
                and entry.kind != "source"
                and (entry.kind in AD_KINDS or size <= max_chars)
                and (not entry.sponsor or not current.sponsor or entry.sponsor == current.sponsor)
            ):
                current.timestamps.append(entry.timestamp)
                merge_paragraphs(current.paragraphs, entry.paragraphs)
                current.sponsor = current.sponsor or entry.sponsor
                continue
        groups.append(
            EntryGroup([entry.timestamp], entry.kind, entry.label, list(entry.paragraphs), entry.sponsor)
        )
        starts.append(index)
    return groups, starts


def anchor_for(seconds: int, used: set[str]) -> str:
    base = "sec-" + clock(seconds).replace(":", "")
    anchor, suffix = base, 2
    while anchor in used:
        anchor, suffix = f"{base}-{suffix}", suffix + 1
    used.add(anchor)
    return anchor


def build_sections(
    entries: list[Entry],
    draft_sections: dict[int, str],
    section_seconds: int,
    fallback_titles: dict[str, str],
    max_chars: int,
    language: str,
) -> list[Section]:
    if draft_sections:
        breaks = set(draft_sections)
        if 0 not in draft_sections:
            draft_sections = {0: "开场" if language.startswith("zh") else "Opening", **draft_sections}
    else:
        breaks, current_key = set(), None
        for index, entry in enumerate(entries):
            key = parse_timestamp(entry.timestamp) // section_seconds
            if key != current_key:
                breaks.add(index)
                current_key = key
        draft_sections = {}
        ordered = sorted(breaks)
        for position, index in enumerate(ordered):
            start = parse_timestamp(entries[index].timestamp) // section_seconds * section_seconds
            stop = ordered[position + 1] if position + 1 < len(ordered) else len(entries)
            sample = next((e for e in entries[index:stop] if e.kind not in AD_KINDS), None)
            text = re.split(r"[。！？!?；;：:]", " ".join(sample.paragraphs), maxsplit=1)[0] if sample else ""
            default = (text[:24].rstrip() + "…") if len(text) > 24 else (text or clock(start, False))
            draft_sections[index] = fallback_titles.get(clock(start, False), default)

    groups, starts = group_entries(entries, breaks, max_chars)
    sections: list[Section] = []
    used: set[str] = set()
    for group, entry_index in zip(groups, starts):
        if entry_index in draft_sections:
            start = parse_timestamp(entries[entry_index].timestamp)
            sections.append(Section(draft_sections[entry_index], start, anchor_for(start, used)))
        sections[-1].groups.append(group)
    last = parse_timestamp(entries[-1].timestamp)
    for index, section in enumerate(sections):
        section.end = sections[index + 1].start if index + 1 < len(sections) else last
    return sections


# --- rendering helpers ----------------------------------------------------


def timestamp_url(url: str, seconds: int) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("youtube.com") or host.endswith("youtu.be"):
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "t"] + [("t", f"{seconds}s")]
        return urlunparse(parsed._replace(query=urlencode(query)))
    if host.endswith("bilibili.com"):
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "t"] + [("t", str(seconds))]
        return urlunparse(parsed._replace(query=urlencode(query)))
    if host.endswith("vimeo.com"):
        return urlunparse(parsed._replace(fragment=f"t={seconds}s"))
    return ""


def time_link(timestamp: str, url: str) -> str:
    seconds = parse_timestamp(timestamp)
    target = timestamp_url(url, seconds)
    return f"[{clock(seconds)}]({target})" if target else clock(seconds)


def ad_anchor(timestamp: str) -> str:
    return "ad-" + timestamp.strip("[]").replace(":", "-")


def duration_text(seconds: int, zh: bool) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    if zh:
        if not minutes:
            return f"约 {secs} 秒"
        return f"约 {minutes} 分钟" if not secs else f"约 {minutes} 分 {secs} 秒"
    return f"~{minutes}m {secs}s" if minutes else f"~{secs}s"


def md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def yaml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return "null"
    return json.dumps(str(value), ensure_ascii=False)


def yaml_block(key: str, value: object, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for item_key, item_value in value.items():
            lines.extend(yaml_block(str(item_key), item_value, indent + 2))
        return lines
    if isinstance(value, list):
        return [f"{prefix}{key}:"] + [f"{prefix}  - {yaml_value(item)}" for item in value]
    return [f"{prefix}{key}: {yaml_value(value)}"]


# --- document parts -------------------------------------------------------


def ad_breaks(sections: list[Section]) -> list[list[EntryGroup]]:
    result: list[list[EntryGroup]] = []
    for section in sections:
        previous_is_ad = False
        for group in section.groups:
            if group.kind in AD_KINDS:
                if previous_is_ad:
                    result[-1].append(group)
                else:
                    result.append([group])
            previous_is_ad = group.kind in AD_KINDS
    return result


def break_sponsors(groups: list[EntryGroup]) -> list[str]:
    return list(dict.fromkeys(group.sponsor for group in groups if group.sponsor))


def render_frontmatter(
    metadata: dict[str, object], language: str, role: str, breaks: list[list[EntryGroup]]
) -> str:
    ad_segments = sum(len(group.timestamps) for groups in breaks for group in groups)
    sponsors = list(dict.fromkeys(s for groups in breaks for s in break_sponsors(groups)))
    fields: list[tuple[str, object]] = [
        ("document_type", "video_transcript"),
        ("document_role", role),
        ("language", language),
    ]
    for key in (
        "episode", "slug", "title", "translated_title", "url", "platform", "channel",
        "upload_date", "duration", "source_language", "target_language", "caption_source",
        "caption_type", "speaker_attribution",
    ):
        fields.append((key, metadata.get(key)))
    fields += [
        ("contains_ads", bool(breaks)),
        ("ad_break_count", len(breaks)),
        ("ad_segment_count", ad_segments),
        ("status", metadata.get("status")),
        ("format_version", FORMAT_VERSION),
    ]
    lines = ["---"]
    lines += [f"{key}: {yaml_value(value)}" for key, value in fields if value not in ("", None)]
    for key in ("tags",):
        values = metadata.get(key)
        if isinstance(values, list) and values:
            lines += yaml_block(key, values)
    if sponsors:
        lines += yaml_block("sponsors", sponsors)
    for key in ("people", "quality_review", "files", "rendered_from"):
        mapping = meta_map(metadata, key)
        if mapping:
            lines += yaml_block(key, mapping)
    lines.append("---")
    return "\n".join(lines)


def render_info(metadata: dict[str, object], language: str, breaks: list[list[EntryGroup]]) -> str:
    zh = language.startswith("zh")
    rows: list[tuple[str, str]] = []

    def add(label_zh: str, label_en: str, value: str, table: dict[str, str] | None = None) -> None:
        if value:
            shown = (table or {}).get(value, value) if zh else value
            rows.append((label_zh if zh else label_en, md_cell(shown)))

    add("原视频标题", "Original title", meta_str(metadata, "title"))
    if zh and meta_str(metadata, "translated_title") != meta_str(metadata, "title"):
        add("中文标题", "Chinese title", meta_str(metadata, "translated_title"))
    add("平台", "Platform", meta_str(metadata, "platform"))
    add("频道 / 作者", "Channel", meta_str(metadata, "channel"))
    add("发布日期", "Published", meta_str(metadata, "upload_date"))
    add("时长", "Duration", meta_str(metadata, "duration"))
    source_lang, target_lang = meta_str(metadata, "source_language"), meta_str(metadata, "target_language")
    if source_lang and target_lang and source_lang != target_lang:
        add("语言", "Languages", f"{LANGUAGE_NAMES.get(source_lang, source_lang) if zh else source_lang} → "
            f"{LANGUAGE_NAMES.get(target_lang, target_lang) if zh else target_lang}")
    add("字幕来源", "Caption source", meta_str(metadata, "caption_source"))
    add("字幕类型", "Caption type", meta_str(metadata, "caption_type"), CAPTION_TYPES)
    add("说话人判定", "Speaker attribution", meta_str(metadata, "speaker_attribution"), ATTRIBUTION)
    if breaks:
        count = len(breaks)
        rows.append(("广告", f"{count} 段，正文中已默认折叠") if zh else ("Ads", f"{count} breaks, collapsed"))
    add("处理状态", "Status", meta_str(metadata, "status"), STATUS)
    url = meta_str(metadata, "url")
    if url:
        rows.append(("链接" if zh else "URL", f"[{md_cell(url)}]({url})"))
    header = "| 字段 | 内容 |" if zh else "| Field | Value |"
    lines = [f"## {'本期信息' if zh else 'Episode Information'}", "", header, "|:---|:---|"]
    lines += [f"| {label} | {value} |" for label, value in rows]
    return "\n".join(lines)


def render_people(metadata: dict[str, object], language: str) -> str:
    people = meta_map(metadata, "people")
    if not people:
        return ""
    zh = language.startswith("zh")
    names = {
        "host": ("主持人", "Host"),
        "guest": ("嘉宾", "Guest"),
        "narrator": ("旁白", "Narrator"),
        "other": ("其他发言者", "Other"),
    }
    header = "| 角色 | 人物 |" if zh else "| Role | Person |"
    lines = [f"## {'人物' if zh else 'People'}", "", header, "|:---|:---|"]
    for key, value in people.items():
        role = names.get(key, (key, key))[0 if zh else 1]
        lines.append(f"| {role} | {md_cell(value)} |")
    return "\n".join(lines)


def render_toc(sections: list[Section], language: str) -> str:
    zh = language.startswith("zh")
    lines = [f"## {'章节导航' if zh else 'Contents'}", ""]
    for index, section in enumerate(sections, start=1):
        lines.append(f"{index}. [{section.title}](#{section.anchor}) · `{clock(section.start)}`")
    return "\n".join(lines)


def speaker_line(group: EntryGroup, url: str) -> str:
    """Small, unobtrusive `name · time` line; roles are listed once in the people table."""
    _, _, name = group.label.partition("｜")
    shown = name if name and group.kind not in AD_KINDS else group.label
    time = time_link(group.timestamps[0], url)
    return f"<sub>{shown} · {time}</sub><br>" if shown else f"<sub>{time}</sub><br>"


def body_lines(group: EntryGroup, prefix: str = "") -> list[str]:
    lines: list[str] = []
    for index, paragraph in enumerate(readable_paragraphs(group.paragraphs)):
        if index:
            lines.append(prefix.rstrip())
        lines.append(f"{prefix}{paragraph}")
    return lines


def render_turn(group: EntryGroup, url: str) -> list[str]:
    lines = [f"<!-- ts: {timestamp} -->" for timestamp in group.timestamps]
    if group.kind in ALERT_KINDS:
        return lines + ["> [!NOTE]", f"> {speaker_line(group, url)}"] + body_lines(group, "> ")
    return lines + [speaker_line(group, url)] + body_lines(group)


def render_ad_break(groups: list[EntryGroup], next_start: int | None, url: str, language: str) -> list[str]:
    zh = language.startswith("zh")
    first = groups[0].timestamps[0]
    start = parse_timestamp(first)
    sponsors = "、".join(break_sponsors(groups)) or ("赞助内容" if zh else "Sponsor")
    span = f"，{duration_text(next_start - start, zh)}" if next_start and next_start > start else ""
    if zh:
        summary = f"广告｜{sponsors} · {clock(start)} 起{span}（已折叠，点击展开）"
    else:
        summary = f"Ad | {sponsors} · {clock(start)}{span.replace('，', ', ')} (collapsed)"
    lines = [f'<a id="{ad_anchor(first)}"></a>', '<details class="ad">', f"<summary>{summary}</summary>", ""]
    for group in groups:
        lines += [f"<!-- ts: {timestamp} -->" for timestamp in group.timestamps]
        lines += [speaker_line(group, url)] + body_lines(group) + [""]
    lines.append("</details>")
    return lines


def render_document(
    metadata: dict[str, object],
    preamble: str,
    entries: list[Entry],
    sections: list[Section],
    language: str,
    role: str,
    corrections: str,
) -> str:
    zh = language.startswith("zh")
    url = meta_str(metadata, "url")
    breaks = ad_breaks(sections)
    title = (meta_str(metadata, "translated_title") if zh else "") or meta_str(metadata, "title") or "Transcript"
    note = (
        "> [!TIP]\n> 完整逐字稿：开场、正片、片尾均未删减；广告已默认折叠。"
        "点击说话人旁的时间可跳转到视频对应位置。"
        if zh
        else "> [!TIP]\n> Complete transcript. Ads are collapsed; click a timestamp to open the video there."
    )
    parts = [render_frontmatter(metadata, language, role, breaks), "", f"# {title}", "", note, ""]
    parts += [render_info(metadata, language, breaks), ""]
    people = render_people(metadata, language)
    if people:
        parts += [people, ""]
    if preamble:
        parts += [preamble, ""]
    parts += [render_toc(sections, language), "", "---", ""]

    entry_starts = [parse_timestamp(entry.timestamp) for entry in entries]
    for section in sections:
        parts += [
            f'<a id="{section.anchor}"></a>',
            "",
            f"## {section.title}",
            "",
            f"<sub>{time_link(f'[{clock(section.start)}]', url)} – {clock(section.end)}</sub>",
            "",
        ]
        groups = section.groups
        index = 0
        while index < len(groups):
            group = groups[index]
            if group.kind in AD_KINDS:
                block = [group]
                while index + 1 < len(groups) and groups[index + 1].kind in AD_KINDS:
                    index += 1
                    block.append(groups[index])
                last_seconds = parse_timestamp(block[-1].timestamps[-1])
                next_start = next((s for s in entry_starts if s > last_seconds), None)
                parts += render_ad_break(block, next_start, url, language) + [""]
            else:
                parts += render_turn(group, url) + [""]
            index += 1

    document = "\n".join(parts).rstrip()
    if corrections.strip():
        document += "\n\n---\n\n" + corrections.strip()
    return document + "\n"


def main() -> int:
    args = parse_args()
    episode_dir = args.episode_dir.expanduser().resolve()
    drafts = [path.expanduser().resolve() for path in args.transcripts]
    if not episode_dir.is_dir():
        print(f"Episode directory not found: {episode_dir}", file=sys.stderr)
        return 2
    missing = [str(path) for path in drafts if not path.is_file()]
    if missing:
        print(f"Draft not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    if args.section_minutes < 1:
        print("--section-minutes must be positive", file=sys.stderr)
        return 2

    try:
        metadata = read_metadata(episode_dir / "metadata.yaml")
        host = str(meta_map(metadata, "people").get("host", "主持人"))
        source_drafts: list[Path] = []
        if args.role == "localized" and not args.no_html:
            if args.source_transcript:
                source_drafts = [path.expanduser().resolve() for path in args.source_transcript]
                missing_source = [str(path) for path in source_drafts if not path.is_file()]
                if missing_source:
                    print(
                        f"Source draft not found: {', '.join(missing_source)}",
                        file=sys.stderr,
                    )
                    return 2
            else:
                source_drafts = infer_source_drafts(episode_dir, metadata)
                if not source_drafts:
                    source_language = meta_str(metadata, "source_language") or "source"
                    print(
                        "Missing source transcript draft for comparison HTML: "
                        f"expected drafts/transcript.{source_language}.annotated.txt",
                        file=sys.stderr,
                    )
                    return 2
        preamble, entries, draft_sections = read_drafts(drafts, host)
        fallback_titles: dict[str, str] = {}
        for value in args.section_title:
            key, separator, title = value.partition("=")
            if not separator or not re.fullmatch(r"\d{2}:\d{2}", key):
                raise ValueError(f"Invalid --section-title {value!r}; expected HH:MM=Title")
            fallback_titles[key] = title.strip()
        sections = build_sections(
            entries, draft_sections, args.section_minutes * 60, fallback_titles,
            args.max_turn_chars, args.language,
        )
        corrections = ""
        if args.corrections:
            corrections = args.corrections.expanduser().resolve().read_text(encoding="utf-8")
        output = (
            args.output.expanduser().resolve() if args.output
            else episode_dir / f"transcript.{args.language}.md"
        )
        output.write_text(
            render_document(metadata, preamble, entries, sections, args.language, args.role, corrections),
            encoding="utf-8",
        )
        html_output: Path | None = None
        html_source_preamble = ""
        html_source_entries: list[Entry] = []
        html_source_sections: list[Section] = []
        if not args.no_html and args.role == "localized":
            html_output = (
                args.html_output.expanduser().resolve()
                if args.html_output
                else episode_dir / "index.html"
            )
            html_source_preamble, html_source_entries, source_draft_sections = read_drafts(
                source_drafts, host
            )
            html_source_sections = build_sections(
                html_source_entries,
                source_draft_sections,
                args.section_minutes * 60,
                fallback_titles,
                args.max_turn_chars,
                args.language,
            )
            import render_html  # noqa: PLC0415

            render_html.write_html(
                html_output,
                metadata,
                preamble,
                html_source_preamble,
                sections,
                html_source_sections,
                html_source_entries,
                corrections,
                episode_dir,
                args.language,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    turns = sum(len(section.groups) for section in sections)
    print(f"{output} ({len(entries)} entries, {turns} turns, {len(sections)} sections)")
    if html_output:
        print(f"{html_output} ({len(html_source_entries)} source entries)")

    source_tsv = episode_dir / "source.segments.tsv"
    if not args.no_validate and source_tsv.is_file():
        issues, summary = validate_translation.validate(
            source_tsv, output, allow_unlabeled=any(entry.kind == "source" for entry in entries)
        )
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        if issues:
            return 1
        print(summary)
    refresh_readmes(episode_dir)
    return 0


def refresh_readmes(episode_dir: Path) -> None:
    """Keep the README episode catalogs in sync when rendering an episode of this project."""
    import update_readme

    root = update_readme.PROJECT_ROOT
    if episode_dir.parent != root / "episodes" or not (root / "README.md").is_file():
        return
    for name, zh in (("README.md", False), ("README.zh-CN.md", True)):
        path = root / name
        try:
            if path.is_file() and update_readme.update(path, update_readme.catalog(root, zh)):
                print(f"{path}: catalog updated")
        except (OSError, ValueError) as exc:
            print(f"WARNING: README not updated: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
