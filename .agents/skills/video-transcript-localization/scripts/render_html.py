#!/usr/bin/env python3
"""Render the same parsed transcript data as a standalone readable HTML page."""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_markdown as md  # noqa: E402


NOTE_PATTERN = re.compile(
    r"（注：(?P<parenthetical>[^）]+)）"
    r"|\[(?P<bracket_kind>可能为|原文字面)：(?P<bracket>[^\]]+)\]"
    r"|\[(?P<unintelligible>听不清)\]"
)
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
CODE_PATTERN = re.compile(r"`([^`]+)`")
IMAGE_PATTERN = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class GlossaryTerm:
    original: str
    translated: str
    description: str


@dataclass(frozen=True)
class InlineMatch:
    start: int
    end: int
    markup: str
    term_key: str = ""
    priority: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a standalone transcript HTML page.")
    parser.add_argument("episode_dir", type=Path, help="Episode directory containing metadata.yaml")
    parser.add_argument("transcript", type=Path, help="Annotated localized draft")
    parser.add_argument("--source-transcript", nargs="+", type=Path, help="Annotated source draft(s)")
    parser.add_argument("--language", required=True, help="Document language code, such as zh-CN")
    parser.add_argument("--corrections", type=Path, help="Correction log appended to the page")
    parser.add_argument("-o", "--output", type=Path, help="Output HTML path")
    parser.add_argument("--section-minutes", type=int, default=10)
    parser.add_argument(
        "--section-title",
        action="append",
        default=[],
        metavar="HH:MM=TITLE",
        help="Fallback section title for fixed-size sections; repeatable",
    )
    parser.add_argument("--max-turn-chars", type=int, default=1600)
    return parser.parse_args()


def split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip().replace("\\|", "|") for cell in stripped.split("|")]


def split_preamble_reference(preamble: str) -> tuple[str, str]:
    """Split glossary/reference blocks from the introductory summary."""
    match = re.search(r"(?m)^##\s+(?:术语对照|Glossary)\s*$", preamble)
    if not match:
        return preamble.strip(), ""
    return preamble[:match.start()].strip(), preamble[match.start():].strip()


def parse_glossary(preamble: str) -> list[GlossaryTerm]:
    in_glossary = False
    rows: list[list[str]] = []
    for line in preamble.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_glossary = stripped == "## 术语对照"
            rows = []
            continue
        if not in_glossary or not stripped.startswith("|"):
            continue
        row = split_table_row(stripped)
        if not row or all(TABLE_SEPARATOR.fullmatch(cell) for cell in row):
            continue
        rows.append(row)
    if len(rows) < 2:
        return []
    terms: list[GlossaryTerm] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        terms.append(
            GlossaryTerm(
                original=row[0],
                translated=row[1],
                description=row[2] if len(row) > 2 else "",
            )
        )
    return [term for term in terms if term.original or term.translated]


def note_match(match: re.Match[str]) -> InlineMatch:
    if match.group("parenthetical"):
        label = "注"
        note = f"译注：{match.group('parenthetical')}"
    elif match.group("bracket_kind"):
        label = "疑"
        note = f"{match.group('bracket_kind')}：{match.group('bracket')}"
    else:
        label = "听"
        note = "听不清"
    markup = (
        f'<span class="inline-note" tabindex="0" role="note" '
        f'data-note="{html.escape(note, quote=True)}">{label}</span>'
    )
    return InlineMatch(match.start(), match.end(), markup, priority=4)


def link_match(match: re.Match[str]) -> InlineMatch:
    label = html.escape(match.group(1))
    target = html.escape(match.group(2), quote=True)
    markup = f'<a href="{target}" target="_blank" rel="noopener">{label}</a>'
    return InlineMatch(match.start(), match.end(), markup, priority=3)


def glossary_matches(
    text: str,
    glossary: list[GlossaryTerm],
    context: str,
    seen: set[str],
) -> list[InlineMatch]:
    matches: list[InlineMatch] = []
    for term in glossary:
        value = term.translated if context == "translation" else term.original
        value = value.strip()
        key = f"{context}:{term.original}:{term.translated}"
        if not value or key in seen:
            continue
        flags = re.IGNORECASE if value.isascii() else 0
        found = re.search(re.escape(value), text, flags)
        if not found:
            continue
        tooltip_parts = [part for part in (term.original, term.translated, term.description) if part]
        tooltip = "｜".join(dict.fromkeys(tooltip_parts))
        markup = (
            f'<span class="glossary-term" tabindex="0" data-tooltip="'
            f'{html.escape(tooltip, quote=True)}">{html.escape(found.group(0))}</span>'
        )
        matches.append(
            InlineMatch(found.start(), found.end(), markup, term_key=key, priority=1)
        )
    return matches


def select_inline_matches(candidates: list[InlineMatch]) -> list[InlineMatch]:
    selected: list[InlineMatch] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.start, -(item.end - item.start), -item.priority),
    ):
        if any(candidate.start < item.end and candidate.end > item.start for item in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def render_inline(
    text: str,
    glossary: list[GlossaryTerm] | None = None,
    context: str = "translation",
    seen: set[str] | None = None,
) -> str:
    glossary = glossary or []
    seen = seen if seen is not None else set()
    candidates = [note_match(match) for match in NOTE_PATTERN.finditer(text)]
    candidates += [link_match(match) for match in LINK_PATTERN.finditer(text)]
    candidates += [
        InlineMatch(
            match.start(),
            match.end(),
            f"<strong>{html.escape(match.group(1))}</strong>",
            priority=2,
        )
        for match in BOLD_PATTERN.finditer(text)
    ]
    candidates += [
        InlineMatch(
            match.start(),
            match.end(),
            f"<code>{html.escape(match.group(1))}</code>",
            priority=2,
        )
        for match in CODE_PATTERN.finditer(text)
    ]
    candidates += glossary_matches(text, glossary, context, seen)
    selected = select_inline_matches(candidates)

    output: list[str] = []
    cursor = 0
    for item in selected:
        output.append(html.escape(text[cursor:item.start]))
        output.append(item.markup)
        if item.term_key:
            seen.add(item.term_key)
        cursor = item.end
    output.append(html.escape(text[cursor:]))
    return "".join(output)


def render_table(rows: list[list[str]], glossary: list[GlossaryTerm], seen: set[str]) -> str:
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    lines = ["<div class=\"table-wrap\">", "<table>", "<thead><tr>"]
    lines += [f"<th>{render_inline(cell, glossary, 'translation', seen)}</th>" for cell in header]
    lines += ["</tr></thead>", "<tbody>"]
    for row in body:
        lines.append("<tr>")
        lines += [f"<td>{render_inline(cell, glossary, 'translation', seen)}</td>" for cell in row]
        lines.append("</tr>")
    lines += ["</tbody>", "</table>", "</div>"]
    return "\n".join(lines)


def render_image(alt: str, source: str, title: str = "") -> str:
    caption = render_inline(alt)
    caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
    title_attr = f' data-title="{html.escape(title, quote=True)}"' if title else ""
    return (
        f'<figure class="media-frame"{title_attr}>'
        f'<img src="{html.escape(source, quote=True)}" alt="{html.escape(alt, quote=True)}" '
        f'loading="lazy">{caption_html}</figure>'
    )


def render_markdown_blocks(
    markdown: str,
    glossary: list[GlossaryTerm] | None = None,
    context: str = "translation",
    seen: set[str] | None = None,
) -> str:
    glossary = glossary or []
    seen = seen if seen is not None else set()
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        image_match = IMAGE_PATTERN.fullmatch(stripped)
        if image_match:
            output.append(render_image(image_match.group(1), image_match.group(2)))
            index += 1
            continue
        heading_match = re.match(r"^(#{2,4})\s+(.+)$", stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            output.append(
                f"<h{level}>{render_inline(heading_match.group(2), glossary, context, seen)}</h{level}>"
            )
            index += 1
            continue
        if stripped.startswith("> "):
            block: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("> "):
                block.append(lines[index].strip()[2:])
                index += 1
            output.append(
                "<blockquote>"
                + render_inline(" ".join(block), glossary, context, seen)
                + "</blockquote>"
            )
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:])
                index += 1
            output.append(
                "<ul>"
                + "".join(
                    f"<li>{render_inline(item, glossary, context, seen)}</li>" for item in items
                )
                + "</ul>"
            )
            continue
        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = split_table_row(lines[index])
                if not all(TABLE_SEPARATOR.fullmatch(cell) for cell in row):
                    rows.append(row)
                index += 1
            output.append(render_table(rows, glossary, seen))
            continue

        paragraph: list[str] = []
        while index < len(lines):
            current = lines[index].strip()
            if not current:
                break
            if (
                current.startswith(("#", "- ", "> ", "|"))
                or IMAGE_PATTERN.fullmatch(current)
            ):
                break
            paragraph.append(current)
            index += 1
        output.append(f"<p>{render_inline(' '.join(paragraph), glossary, context, seen)}</p>")
    return "\n".join(output)


def read_source_lookup(entries: list[md.Entry]) -> dict[tuple[str, str], list[md.Entry]]:
    lookup: dict[tuple[str, str], list[md.Entry]] = defaultdict(list)
    for entry in entries:
        lookup[(entry.timestamp, entry.label)].append(entry)
    return lookup


def original_paragraphs(
    group: md.EntryGroup,
    lookup: dict[tuple[str, str], list[md.Entry]],
) -> list[str]:
    paragraphs: list[str] = []
    used: set[int] = set()
    for timestamp in group.timestamps:
        candidates = lookup.get((timestamp, group.label), [])
        for candidate in candidates:
            identity = id(candidate)
            if identity in used:
                continue
            used.add(identity)
            paragraphs.extend(candidate.paragraphs)
            break
    return paragraphs


def display_speaker(group: md.EntryGroup) -> str:
    if group.kind in md.AD_KINDS:
        return "广告"
    _, _, name = group.label.partition("｜")
    return name or group.label or "未知说话人"


def speaker_key(group: md.EntryGroup) -> str:
    return display_speaker(group)


def render_media(
    metadata: dict[str, object],
    episode_dir: Path,
    language: str,
) -> str:
    cover = md.meta_str(metadata, "cover_image")
    if not cover:
        return ""
    cover_path = episode_dir / cover
    if not cover_path.is_file():
        return ""
    title = md.meta_str(metadata, "translated_title") or md.meta_str(metadata, "title")
    return (
        '<figure class="episode-cover">'
        f'<img src="{html.escape(cover, quote=True)}" alt="{html.escape(title, quote=True)}" '
        'loading="eager">'
        "</figure>"
    )


def render_info_rows(metadata: dict[str, object], language: str) -> str:
    rows = [
        md.meta_str(metadata, "platform"),
        md.meta_str(metadata, "channel"),
        md.meta_str(metadata, "duration"),
    ]
    visible = [value for value in rows if value]
    return "".join(
        f'<span class="meta-item">{html.escape(value)}</span>' for value in visible
    )


def render_toc(
    sections: list[md.Section], source_sections: list[md.Section]
) -> str:
    source_by_start = {section.start: section for section in source_sections}
    links = []
    for index, section in enumerate(sections, start=1):
        source_section = source_by_start.get(section.start)
        source_title = source_section.title if source_section else section.title
        links.append(
            f'<a href="#{section.anchor}" data-section-link="{section.anchor}">'
            f'<span class="toc-index">{index:02d}</span>'
            f'<span class="toc-title toc-title-translation">{html.escape(section.title)}</span>'
            f'<span class="toc-title toc-title-original" lang="en">'
            f'{html.escape(source_title)}</span>'
            f'<time>{md.clock(section.start, False)}</time></a>'
        )
    return "\n".join(links)


def render_turn(
    group: md.EntryGroup,
    source_paragraphs: list[str],
    section: md.Section,
    metadata: dict[str, object],
    glossary: list[GlossaryTerm],
    seen: dict[str, set[str]],
    url: str,
    language: str,
    turn_index: int,
) -> str:
    source_language = md.meta_str(metadata, "source_language") or "en"
    timestamp = group.timestamps[0]
    turn_id = f"turn-{md.parse_timestamp(timestamp)}-{turn_index}"
    target = md.timestamp_url(url, md.parse_timestamp(timestamp))
    speaker = group.label if group.kind in md.AD_KINDS else display_speaker(group)
    time_markup = (
        f'<a class="timestamp" href="{html.escape(target, quote=True)}" target="_blank" '
        f'rel="noopener">{timestamp}</a>'
        if target
        else f'<span class="timestamp">{timestamp}</span>'
    )
    ad_badge = '<span class="ad-badge">广告</span>' if group.kind in md.AD_KINDS else ""
    comments = "".join(f"<!-- ts: {value} -->" for value in group.timestamps)
    translation = "".join(
        f'<p>{render_inline(paragraph, glossary, "translation", seen["translation"])}</p>'
        for paragraph in md.readable_paragraphs(group.paragraphs)
    )
    source_available = bool(source_paragraphs)
    if source_available:
        original = "".join(
            f'<p>{render_inline(paragraph, glossary, "original", seen["original"])}</p>'
            for paragraph in md.readable_paragraphs(source_paragraphs)
        )
    else:
        original = '<p class="missing-source">原文未提供</p>'
    show_original = "查看原文" if language.startswith("zh") else "Show source"
    hide_original = "收起原文" if language.startswith("zh") else "Hide source"
    original_toggle = (
        f'<button class="turn-original-toggle" type="button" data-turn-original-toggle '
        f'data-show-label="{html.escape(show_original, quote=True)}" '
        f'data-hide-label="{html.escape(hide_original, quote=True)}" '
        f'aria-controls="{turn_id}-original" aria-expanded="false" '
        f'aria-label="{html.escape(show_original, quote=True)}" '
        f'title="{html.escape(show_original, quote=True)}">'
        '<svg class="turn-original-show-icon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/>'
        '<circle cx="12" cy="12" r="2.5"/></svg>'
        '<svg class="turn-original-hide-icon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="m3 3 18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c6 0 9.5 6 9.5 6a16 16 0 0 1-2.2 3M6.6 6.6C4 8.3 2.5 12 2.5 12s3.5 6 9.5 6a9.8 9.8 0 0 0 3-.5"/>'
        '</svg><span class="visually-hidden">'
        f'{html.escape(show_original)}</span></button>'
        if source_available
        else ""
    )
    return (
        f'{comments}<article class="turn" id="{turn_id}" '
        f'data-speaker="{html.escape(speaker_key(group), quote=True)}" '
        f'data-section="{section.anchor}" data-search="{html.escape(display_speaker(group), quote=True)}" '
        f'data-original-expanded="false" data-source-available="{str(source_available).lower()}">'
        f'<header class="turn-header"><div><span class="speaker">{html.escape(speaker)}</span>'
        f'{ad_badge}</div><div class="turn-actions">{original_toggle}{time_markup}</div></header>'
        f'<div class="turn-copy"><div class="turn-translation" lang="{html.escape(language, quote=True)}">'
        f'{translation}</div><div class="turn-original" id="{turn_id}-original" '
        f'lang="{html.escape(source_language, quote=True)}">{original}</div></div></article>'
    )


def ad_summary(groups: list[md.EntryGroup], language: str) -> str:
    zh = language.startswith("zh")
    first = groups[0].timestamps[0]
    sponsors = "、".join(md.break_sponsors(groups))
    if zh:
        label = f"广告｜{sponsors}" if sponsors else "广告"
        return f"{label} · {first} 起（展开）"
    label = f"Ad | {sponsors}" if sponsors else "Ad"
    return f"{label} · from {first} (expand)"


def render_ad_block(
    groups: list[md.EntryGroup],
    source_lookup: dict[tuple[str, str], list[md.Entry]],
    section: md.Section,
    metadata: dict[str, object],
    glossary: list[GlossaryTerm],
    seen: dict[str, set[str]],
    url: str,
    language: str,
    turn_index: int,
) -> str:
    first_turn_index = turn_index
    turns = "".join(
        render_turn(
            group,
            original_paragraphs(group, source_lookup),
            section,
            metadata,
            glossary,
            seen,
            url,
            language,
            turn_index,
        )
        for turn_index, group in enumerate(groups, start=first_turn_index)
    )
    return (
        f'<details class="ad-break" data-section="{section.anchor}">'
        f"<summary>{html.escape(ad_summary(groups, language))}</summary>"
        f'<div class="ad-body">{turns}</div></details>'
    )


def render_sections(
    sections: list[md.Section],
    source_sections: list[md.Section],
    source_lookup: dict[tuple[str, str], list[md.Entry]],
    metadata: dict[str, object],
    glossary: list[GlossaryTerm],
    seen: dict[str, set[str]],
    url: str,
    language: str,
) -> str:
    output: list[str] = []
    turn_index = 1
    source_by_start = {section.start: section for section in source_sections}
    for index, section in enumerate(sections):
        source_section = source_by_start.get(section.start)
        source_title = source_section.title if source_section else ""
        source_heading = (
            f'<span class="chapter-title-original" lang="en">{html.escape(source_title)}</span>'
            if source_title
            else ""
        )
        output.append(
            f'<section class="chapter" id="{section.anchor}" data-section="{section.anchor}">'
            f'<header class="chapter-header"><p class="chapter-index">'
            f'{index + 1:02d}</p><div><h2><span class="chapter-title-translation">'
            f'{html.escape(section.title)}</span>{source_heading}</h2>'
            f'<p class="chapter-time">{md.clock(section.start)} – {md.clock(section.end)}</p>'
            "</div></header>"
        )
        group_index = 0
        while group_index < len(section.groups):
            group = section.groups[group_index]
            if group.kind in md.AD_KINDS:
                ad_groups = [group]
                while (
                    group_index + 1 < len(section.groups)
                    and section.groups[group_index + 1].kind in md.AD_KINDS
                ):
                    group_index += 1
                    ad_groups.append(section.groups[group_index])
                output.append(
                    render_ad_block(
                        ad_groups,
                        source_lookup,
                        section,
                        metadata,
                        glossary,
                        seen,
                        url,
                        language,
                        turn_index,
                    )
                )
                turn_index += len(ad_groups)
            else:
                output.append(
                    render_turn(
                        group,
                        original_paragraphs(group, source_lookup),
                        section,
                        metadata,
                        glossary,
                        seen,
                        url,
                        language,
                        turn_index,
                    )
                )
                turn_index += 1
            group_index += 1
        output.append("</section>")
    return "\n".join(output)


def collect_speakers(sections: list[md.Section]) -> list[str]:
    names: dict[str, None] = {}
    for section in sections:
        for group in section.groups:
            names.setdefault(speaker_key(group), None)
    return list(names)


def build_css() -> str:
    return """
:root {
  color-scheme: light;
  --paper: #f7f5ef;
  --surface: #fffdf8;
  --surface-subtle: #ecefe9;
  --media-placeholder: #e7eae6;
  --ink: #202523;
  --muted: #66706a;
  --secondary: #606862;
  --faint: #8b938d;
  --line: #d9ddd7;
  --line-strong: #bfc7c0;
  --accent: #0f6658;
  --accent-soft: #dcece7;
  --accent-contrast: #fff;
  --warm: #a6532f;
  --warm-ink: #74381e;
  --warm-soft: #f3e3d8;
  --toolbar: rgba(247, 245, 239, .94);
  --tooltip-bg: #202724;
  --tooltip-ink: #fff;
  --tooltip-line: #aeb8b1;
  --overlay: rgba(19, 24, 21, .28);
  --shadow: 0 18px 50px rgba(31, 38, 34, .09);
  --control-shadow: 0 1px 5px rgba(28, 37, 32, .12);
  --drawer-shadow: 18px 0 36px rgba(24, 30, 27, .14);
  --focus-ring: rgba(15, 102, 88, .24);
  --serif: Iowan Old Style, Palatino Linotype, Book Antiqua, Georgia, serif;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

html[data-theme="dark"] {
  color-scheme: dark;
  --paper: #151816;
  --surface: #1d211e;
  --surface-subtle: #252b27;
  --media-placeholder: #242925;
  --ink: #e8ece8;
  --muted: #aab4ad;
  --secondary: #bcc5bf;
  --faint: #89928c;
  --line: #343b36;
  --line-strong: #4a554e;
  --accent: #78cbbb;
  --accent-soft: #203b35;
  --accent-contrast: #10211d;
  --warm: #e3a17c;
  --warm-ink: #f0b18c;
  --warm-soft: #3b2a23;
  --toolbar: rgba(21, 24, 22, .94);
  --tooltip-bg: #edf2ee;
  --tooltip-ink: #1c211e;
  --tooltip-line: #657169;
  --overlay: rgba(0, 0, 0, .52);
  --shadow: 0 18px 50px rgba(0, 0, 0, .34);
  --control-shadow: 0 1px 5px rgba(0, 0, 0, .32);
  --drawer-shadow: 18px 0 36px rgba(0, 0, 0, .38);
  --focus-ring: rgba(120, 203, 187, .28);
}

* { box-sizing: border-box; }

html {
  scroll-behavior: smooth;
  scroll-padding-top: 24px;
}

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  line-height: 1.8;
  text-rendering: optimizeLegibility;
}

button, input, select { font: inherit; }
button, select { color: inherit; }
button:focus-visible,
input:focus-visible,
select:focus-visible,
[tabindex="0"]:focus-visible {
  outline: 3px solid var(--focus-ring);
  outline-offset: 2px;
}
a { color: var(--accent); text-underline-offset: .16em; }

.visually-hidden {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  margin: -1px !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

.skip-link {
  position: fixed;
  left: 16px;
  top: -60px;
  z-index: 100;
  padding: 9px 13px;
  background: var(--ink);
  color: var(--surface);
  border-radius: 5px;
}

.skip-link:focus { top: 16px; }

.masthead {
  padding: 34px max(24px, calc((100vw - 1480px) / 2)) 28px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}

.masthead-inner { max-width: 1480px; }

.masthead-top {
  display: flex;
  gap: 18px;
  align-items: flex-start;
  justify-content: space-between;
}

.masthead h1 {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  max-width: none;
  font-family: var(--serif);
  font-size: clamp(1.6rem, 2.8vw, 2.65rem);
  line-height: 1.18;
  letter-spacing: 0;
}

.title-translation,
.title-original { display: block; }

.title-original {
  margin-top: 9px;
  color: var(--secondary);
  font-size: .5em;
  font-weight: 520;
  line-height: 1.3;
}

.theme-toggle {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
}

.theme-toggle:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.theme-toggle svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.theme-icon-sun,
html[data-theme="dark"] .theme-icon-moon { display: block; }
.theme-icon-moon,
html[data-theme="dark"] .theme-icon-sun { display: none; }

.meta-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 0;
  margin-top: 14px;
  color: var(--muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  font-size: .8rem;
}

.meta-item + .meta-item::before {
  content: "·";
  margin: 0 9px;
  color: var(--line-strong);
}

.episode-cover {
  max-width: 1080px;
  margin: 26px 0 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--media-placeholder);
}

.episode-cover img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}

.reading-layout {
  display: grid;
  grid-template-columns: 286px minmax(0, 1fr);
  gap: 44px;
  max-width: 1480px;
  margin: 0 auto;
  padding: 36px 24px 80px;
  transition: grid-template-columns .2s ease, gap .2s ease;
}

.sidebar {
  position: sticky;
  top: 20px;
  align-self: start;
  min-width: 0;
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding: 4px 8px 24px 0;
  transition: opacity .16s ease, transform .2s ease;
}

.sidebar-heading {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding: 2px 0 12px;
}

.sidebar-heading-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 5px;
  align-items: center;
}

.sidebar-theme-toggle,
.sidebar-toggle {
  width: 30px;
  height: 30px;
}

.sidebar-theme-toggle svg,
.sidebar-toggle svg {
  width: 15px;
  height: 15px;
}

.sidebar-title,
.filter-label {
  display: block;
  color: var(--muted);
  font-size: .72rem;
  font-weight: 760;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.sidebar-title { margin: 0 0 8px; }
.filter-label {
  margin: 0 0 4px;
  line-height: 1.3;
}
.sidebar-heading .sidebar-title { margin: 0; }

.sidebar-toggle,
.sidebar-reveal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: var(--surface);
  color: var(--muted);
  cursor: pointer;
}

.sidebar-toggle {
  flex: 0 0 auto;
  border-radius: 50%;
}

.sidebar-toggle:hover,
.sidebar-reveal:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.sidebar-reveal {
  display: none;
  position: fixed;
  top: 50%;
  left: max(16px, calc(50vw - 780px));
  z-index: 40;
  width: 34px;
  height: 40px;
  margin: 0;
  padding: 0;
  border-color: var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
  box-shadow: var(--control-shadow);
  opacity: 1;
  transform: translateY(-50%);
  transition: border-color .16s ease, background .16s ease, color .16s ease,
    box-shadow .16s ease, transform .16s ease;
}

.sidebar-reveal:hover,
.sidebar-reveal:focus-visible {
  box-shadow: 0 5px 14px rgba(28, 37, 32, .16);
  transform: translateY(-50%) translateX(2px);
}

.sidebar-toggle svg,
.sidebar-reveal svg {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.sidebar-reveal svg {
  width: 16px;
  height: 16px;
}

.filter-panel {
  padding: 15px 0 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.filter-field { margin-top: 10px; }

.filter-field:first-child { margin-top: 0; }

.filter-panel select,
.filter-panel input {
  width: 100%;
  max-width: 100%;
  min-height: 40px;
  padding: 8px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: var(--surface);
}

.filter-panel select {
  -webkit-appearance: none;
  appearance: none;
  padding-right: 40px;
  background-image:
    linear-gradient(45deg, transparent 50%, var(--muted) 50%),
    linear-gradient(135deg, var(--muted) 50%, transparent 50%);
  background-position:
    calc(100% - 18px) calc(50% - 2px),
    calc(100% - 13px) calc(50% - 2px);
  background-repeat: no-repeat;
  background-size: 6px 6px;
}

#transcript-search:focus-visible {
  outline: 0;
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 2px var(--focus-ring);
}

.filter-reset {
  display: block;
  width: max-content;
  min-height: 30px;
  margin: 9px 0 0 auto;
  padding: 3px 5px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: .76rem;
  font-weight: 620;
  line-height: 1.35;
}

.filter-reset:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.view-switch {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 2px;
  margin-top: 13px;
  padding: 3px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface-subtle);
}

.view-switch button {
  min-height: 34px;
  padding: 5px 7px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: .82rem;
  font-weight: 680;
}

.view-switch button[aria-pressed="true"] {
  background: var(--accent);
  color: var(--accent-contrast);
  box-shadow: none;
}

.toc {
  display: grid;
  gap: 2px;
  margin-top: 15px;
}

.toc a {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 7px;
  align-items: baseline;
  padding: 8px 7px;
  border-radius: 5px;
  color: var(--muted);
  font-size: .84rem;
  line-height: 1.35;
  text-decoration: none;
}

.toc a:hover,
.toc a.is-active {
  background: var(--accent-soft);
  color: var(--ink);
}

.toc-index,
.toc a time { color: var(--muted); font-size: .72rem; font-variant-numeric: tabular-nums; }
.toc-title { font-weight: 620; }
.toc-title-original { display: none; }

html[data-view="original"] .toc-title-translation { display: none; }
html[data-view="original"] .toc-title-original { display: block; }

.reading-main { min-width: 0; }

.main-toolbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: none;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin: 0 -16px 18px;
  min-height: 50px;
  padding: 5px 16px;
  background: var(--toolbar);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}

.main-toolbar button {
  min-height: 40px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  background: var(--surface);
  cursor: pointer;
  font-size: .88rem;
  line-height: 1;
}

.main-toolbar span {
  color: var(--muted);
  font-size: .76rem;
  line-height: 1.2;
}

.preamble-stack {
  padding: 4px 0 34px;
  border-bottom: 1px solid var(--line-strong);
}

.preamble-stack h2 {
  margin: 0 0 14px;
  font-family: var(--serif);
  font-size: 1.5rem;
  line-height: 1.25;
}

.preamble-stack ul {
  margin: 0;
  padding-left: 1.2em;
}

.preamble-stack li + li { margin-top: 8px; }

.preamble-original {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px dashed var(--line-strong);
  color: var(--secondary);
  font-family: var(--serif);
  line-height: 1.72;
}

.preamble-reference {
  padding: 24px 0 34px;
  border-bottom: 1px solid var(--line-strong);
}

.preamble-reference h2 {
  margin: 0 0 14px;
  font-family: var(--serif);
  font-size: 1.5rem;
  line-height: 1.25;
}

.overview {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(260px, .75fr);
  gap: 34px;
  padding: 4px 0 34px;
  border-bottom: 1px solid var(--line-strong);
}

.overview h2,
.glossary-section h2 {
  margin: 0 0 14px;
  font-family: var(--serif);
  font-size: 1.5rem;
  line-height: 1.25;
  letter-spacing: 0;
}

.overview ul,
.glossary-section ul {
  margin: 0;
  padding-left: 1.2em;
}

.overview li + li { margin-top: 8px; }

.glossary-section {
  padding: 24px 0 36px;
  border-bottom: 1px solid var(--line-strong);
}

.table-wrap { overflow-x: auto; }

table {
  width: 100%;
  border-collapse: collapse;
  font-size: .84rem;
}

th, td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

th {
  color: var(--muted);
  font-size: .72rem;
  font-weight: 760;
  letter-spacing: .04em;
}

.chapter {
  padding-top: 54px;
}

.chapter-header {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 30px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line-strong);
}

.chapter-index {
  margin: 7px 0 0;
  color: var(--warm);
  font-family: var(--serif);
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
}

.chapter h2 {
  margin: 0;
  font-family: var(--serif);
  font-size: clamp(1.65rem, 3vw, 2.65rem);
  line-height: 1.13;
  letter-spacing: 0;
}

.chapter-title-translation,
.chapter-title-original { display: block; }

.chapter-title-original {
  margin-top: 8px;
  color: var(--muted);
  font-size: .42em;
  font-weight: 520;
  line-height: 1.3;
}

.chapter-time {
  margin: 9px 0 0;
  color: var(--muted);
  font-size: .78rem;
  font-variant-numeric: tabular-nums;
}

.turn {
  padding: 23px 0 25px;
  border-bottom: 1px solid var(--line);
}

.turn:last-child { border-bottom: 0; }

.turn-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: .78rem;
}

.speaker { font-weight: 720; }

.turn-actions {
  display: inline-flex;
  flex: 0 0 auto;
  gap: 9px;
  align-items: center;
}

.turn-original-toggle {
  display: none;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--faint);
  cursor: pointer;
  opacity: .68;
}

.turn-original-toggle:hover,
.turn-original-toggle:focus-visible,
.turn-original-toggle[aria-expanded="true"] {
  background: var(--surface-subtle);
  color: var(--accent);
  opacity: 1;
}

.turn-original-toggle svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}

.turn-original-hide-icon,
.turn-original-toggle[aria-expanded="true"] .turn-original-show-icon { display: none; }
.turn-original-toggle[aria-expanded="true"] .turn-original-hide-icon { display: block; }

.timestamp {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  text-decoration: none;
}

.timestamp:hover { color: var(--accent); text-decoration: underline; }

.ad-badge {
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--warm-soft);
  color: var(--warm-ink);
  font-size: .68rem;
}

.turn-copy {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr);
  gap: 34px;
}

.turn-translation,
.turn-original {
  min-width: 0;
}

.turn-translation p,
.turn-original p {
  margin: 0 0 1em;
}

.turn-translation p:last-child,
.turn-original p:last-child { margin-bottom: 0; }

.turn-original {
  color: var(--secondary);
  font-family: var(--serif);
  font-size: .91em;
  line-height: 1.72;
}

.missing-source { color: var(--faint); font-style: italic; }

html[data-view="translation"] .title-original,
html[data-view="translation"] .preamble-original,
html[data-view="translation"] .chapter-title-original,
html[data-view="translation"] .turn-original,
html[data-view="original"] .title-translation,
html[data-view="original"] .preamble-translation,
html[data-view="original"] .chapter-title-translation,
html[data-view="original"] .turn-translation {
  display: none;
}

html[data-view="translation"] .turn-copy,
html[data-view="original"] .turn-copy {
  display: block;
}

html[data-view="translation"] .turn-original-toggle { display: inline-flex; }

html[data-view="translation"] .turn[data-original-expanded="true"] .turn-original {
  display: block;
  margin-top: 14px;
  padding-top: 13px;
  border-top: 1px dashed var(--line-strong);
}

html[data-view="original"] .title-original,
html[data-view="original"] .chapter-title-original {
  margin-top: 0;
  color: var(--ink);
  font-size: 1em;
  font-weight: inherit;
  line-height: inherit;
}

html[data-view="original"] .preamble-original {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
  color: var(--ink);
}

.glossary-term {
  border-bottom: 1px dotted var(--accent);
  cursor: help;
}

.inline-note {
  display: inline-grid;
  place-items: center;
  min-width: 1.55em;
  height: 1.55em;
  margin: 0 .12em;
  border-radius: 50%;
  background: var(--warm-soft);
  color: var(--warm-ink);
  cursor: help;
  font-size: .7em;
  font-weight: 780;
  line-height: 1;
  vertical-align: .1em;
}

.context-tooltip {
  position: fixed;
  z-index: 60;
  width: min(340px, calc(100vw - 24px));
  max-width: calc(100vw - 24px);
  padding: 10px 12px;
  border: 1px solid var(--tooltip-line);
  border-radius: 6px;
  background: var(--tooltip-bg);
  color: var(--tooltip-ink);
  box-shadow: var(--shadow);
  font-family: var(--sans);
  font-size: .78rem;
  font-weight: 500;
  line-height: 1.5;
  overflow-wrap: anywhere;
  pointer-events: none;
}

.context-tooltip[hidden] { display: none; }

.media-frame {
  margin: 22px 0;
}

.media-frame img {
  display: block;
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--media-placeholder);
}

.media-frame figcaption {
  margin-top: 8px;
  color: var(--muted);
  font-size: .78rem;
}

.ad-break {
  margin: 18px 0 24px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-subtle);
}

.ad-break summary {
  padding: 12px 14px;
  cursor: pointer;
  color: var(--muted);
  font-size: .82rem;
  font-weight: 680;
}

.ad-body {
  padding: 0 14px;
  border-top: 1px solid var(--line);
}

.correction-section {
  margin-top: 64px;
  padding-top: 28px;
  border-top: 2px solid var(--line-strong);
}

.correction-section h2 {
  font-family: var(--serif);
  font-size: 1.65rem;
}

.correction-section h3 {
  margin-top: 28px;
  font-size: 1rem;
}

.is-hidden { display: none !important; }

.empty-state {
  display: none;
  padding: 28px 0;
  color: var(--muted);
}

body.is-empty .empty-state { display: block; }

.page-footer {
  max-width: 1050px;
  margin: 0 auto;
  padding: 22px 24px 48px;
  color: var(--muted);
  font-size: .76rem;
}

@media (max-width: 1120px) {
  .reading-layout {
    grid-template-columns: 248px minmax(0, 1fr);
    gap: 30px;
  }

  .turn-copy {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 24px;
  }
}

@media (min-width: 901px) {
  html.sidebar-collapsed .reading-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }

  html.sidebar-collapsed .sidebar { display: none; }
  html.sidebar-collapsed .sidebar-reveal { display: inline-flex; }
}

@media (max-width: 900px) {
  html.nav-open,
  html.nav-open body { overflow: hidden; }

  .masthead { padding: 28px 18px 24px; }
  .theme-toggle { width: 34px; height: 34px; }
  .reading-layout { display: block; padding: 0 16px 64px; }
  .main-toolbar { display: flex; }
  .sidebar-reveal { display: none !important; }
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 80;
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
    width: min(88vw, 340px);
    height: 100vh;
    height: 100dvh;
    max-height: 100vh;
    max-height: 100dvh;
    overflow: hidden;
    padding: calc(16px + env(safe-area-inset-top)) 16px
      calc(16px + env(safe-area-inset-bottom));
    background: var(--surface);
    box-shadow: none;
    transform: translateX(calc(-100% - 2px));
    transition: transform .2s ease, box-shadow .2s ease;
  }

  .sidebar .filter-panel {
    min-height: 0;
    max-height: 45vh;
    max-height: 45dvh;
    padding-right: 8px;
    overflow-y: auto;
    overscroll-behavior: contain;
    touch-action: pan-y;
    -webkit-overflow-scrolling: touch;
  }

  .sidebar .toc {
    align-content: start;
    min-height: 0;
    margin-right: -8px;
    padding-right: 8px;
    padding-bottom: 12px;
    overflow-y: auto;
    overscroll-behavior: contain;
    touch-action: pan-y;
    -webkit-overflow-scrolling: touch;
  }

  body.nav-open .sidebar {
    box-shadow: var(--drawer-shadow);
    transform: translateX(0);
  }

  body.nav-open::after {
    position: fixed;
    inset: 0;
    z-index: 70;
    content: "";
    background: var(--overlay);
  }

  .context-tooltip {
    right: 16px;
    bottom: calc(16px + env(safe-area-inset-bottom));
    left: 16px;
    width: auto;
    max-width: none;
  }

  .overview {
    grid-template-columns: 1fr;
    gap: 26px;
  }

  .turn-copy {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  html[data-view="bilingual"] .turn-original {
    padding-top: 14px;
    border-top: 1px dashed var(--line-strong);
  }

  .chapter { padding-top: 42px; }
  .chapter-header { grid-template-columns: 36px minmax(0, 1fr); gap: 10px; }
}

@media (max-width: 560px) {
  body { line-height: 1.72; }
  .masthead h1 { font-size: 1.5rem; }
  .meta-strip { display: grid; grid-template-columns: 1fr; gap: 4px; }
  .meta-item + .meta-item::before { content: none; }
  .turn-header { align-items: flex-start; }
  .turn { padding: 20px 0; }
  .table-wrap { margin-right: -16px; }
}

@media print {
  .sidebar,
  .main-toolbar,
  .sidebar-reveal,
  .theme-toggle,
  .context-tooltip { display: none !important; }
  .reading-layout { display: block; max-width: none; padding: 0; }
  .turn-copy { display: block; }
  .turn-original { margin-top: 8px; color: #444; }
  .ad-break > summary { display: none; }
  .ad-break > .ad-body { display: block !important; }
}
"""


def build_javascript() -> str:
    return """
(() => {
  const root = document.documentElement;
  const body = document.body;
  const mobileQuery = matchMedia("(max-width: 900px)");
  const systemThemeQuery = matchMedia("(prefers-color-scheme: dark)");
  const viewButtons = [...document.querySelectorAll("[data-view-button]")];
  const themeToggles = [...document.querySelectorAll("[data-theme-toggle]")];
  const turnOriginalToggles = [...document.querySelectorAll("[data-turn-original-toggle]")];
  const speakerFilter = document.querySelector("#speaker-filter");
  const chapterFilter = document.querySelector("#chapter-filter");
  const searchInput = document.querySelector("#transcript-search");
  const resetButton = document.querySelector("#reset-filters");
  const tocToggle = document.querySelector("#toc-toggle");
  const sidebarCollapse = document.querySelector("#sidebar-collapse");
  const sidebarReveal = document.querySelector("#sidebar-reveal");
  const tooltip = document.querySelector("#context-tooltip");
  const tooltipTriggers = [...document.querySelectorAll("[data-tooltip], [data-note]")];
  const turns = [...document.querySelectorAll(".turn")];
  const chapters = [...document.querySelectorAll(".chapter")];
  const tocLinks = [...document.querySelectorAll("[data-section-link]")];
  let activeTooltipTrigger = null;

  function storageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Storage can be unavailable for local files in privacy-restricted browsers.
    }
  }

  const state = {
    view: storageGet("transcript-view") || (mobileQuery.matches ? "translation" : "bilingual"),
    speaker: "all",
    chapter: "all",
    query: "",
  };

  function setTheme(theme, persist = true) {
    const normalized = theme === "dark" ? "dark" : "light";
    root.dataset.theme = normalized;
    themeToggles.forEach((button) => {
      const label = normalized === "dark"
        ? button.dataset.lightLabel
        : button.dataset.darkLabel;
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      button.setAttribute("aria-pressed", String(normalized === "dark"));
    });
    if (persist) storageSet("transcript-theme", normalized);
  }

  function setView(view) {
    state.view = view;
    root.dataset.view = view;
    storageSet("transcript-view", view);
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.viewButton === view));
    });
  }

  function syncSidebarControls() {
    const desktopExpanded = !root.classList.contains("sidebar-collapsed");
    sidebarReveal?.setAttribute("aria-expanded", String(desktopExpanded));
    sidebarCollapse?.setAttribute(
      "aria-expanded",
      String(mobileQuery.matches ? body.classList.contains("nav-open") : desktopExpanded),
    );
  }

  function setSidebarCollapsed(collapsed, persist = true) {
    root.classList.toggle("sidebar-collapsed", collapsed);
    syncSidebarControls();
    if (persist) storageSet("transcript-sidebar-collapsed", String(collapsed));
  }

  function hideTooltip() {
    if (!tooltip || !activeTooltipTrigger) return;
    activeTooltipTrigger.removeAttribute("aria-describedby");
    activeTooltipTrigger = null;
    tooltip.hidden = true;
  }

  function setNavOpen(open) {
    body.classList.toggle("nav-open", open);
    root.classList.toggle("nav-open", open);
    tocToggle?.setAttribute("aria-expanded", String(open));
    syncSidebarControls();
    if (open) hideTooltip();
  }

  function positionTooltip() {
    if (!tooltip || !activeTooltipTrigger || tooltip.hidden) return;
    if (mobileQuery.matches) {
      tooltip.style.removeProperty("top");
      tooltip.style.removeProperty("left");
      tooltip.style.removeProperty("right");
      tooltip.style.removeProperty("bottom");
      return;
    }

    const gutter = 12;
    const targetBox = activeTooltipTrigger.getBoundingClientRect();
    tooltip.style.top = "0px";
    tooltip.style.left = "0px";
    tooltip.style.right = "auto";
    tooltip.style.bottom = "auto";
    const tooltipBox = tooltip.getBoundingClientRect();
    const centeredLeft = targetBox.left + targetBox.width / 2 - tooltipBox.width / 2;
    const left = Math.min(
      Math.max(gutter, centeredLeft),
      Math.max(gutter, window.innerWidth - tooltipBox.width - gutter),
    );
    const above = targetBox.top - tooltipBox.height - 9;
    const below = targetBox.bottom + 9;
    const top = above >= gutter
      ? above
      : Math.min(below, window.innerHeight - tooltipBox.height - gutter);
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.max(gutter, Math.round(top))}px`;
  }

  function showTooltip(trigger) {
    if (!tooltip) return;
    if (activeTooltipTrigger && activeTooltipTrigger !== trigger) {
      activeTooltipTrigger.removeAttribute("aria-describedby");
    }
    activeTooltipTrigger = trigger;
    tooltip.textContent = trigger.dataset.tooltip || trigger.dataset.note || "";
    tooltip.hidden = false;
    trigger.setAttribute("aria-describedby", "context-tooltip");
    positionTooltip();
  }

  function applyFilters() {
    const query = state.query.trim().toLocaleLowerCase();
    let visibleTotal = 0;
    turns.forEach((turn) => {
      const speakerMatches = state.speaker === "all" || turn.dataset.speaker === state.speaker;
      const chapterMatches = state.chapter === "all" || turn.dataset.section === state.chapter;
      const queryMatches = !query || turn.textContent.toLocaleLowerCase().includes(query);
      const visible = speakerMatches && chapterMatches && queryMatches;
      turn.classList.toggle("is-hidden", !visible);
      if (visible) visibleTotal += 1;
    });
    chapters.forEach((chapter) => {
      const hasVisible = [...chapter.querySelectorAll(".turn")].some((turn) => !turn.classList.contains("is-hidden"));
      chapter.classList.toggle("is-hidden", !hasVisible);
    });
    body.classList.toggle("is-empty", visibleTotal === 0);
  }

  themeToggles.forEach((button) => {
    button.addEventListener("click", () => {
      setTheme(root.dataset.theme === "dark" ? "light" : "dark");
    });
  });

  turnOriginalToggles.forEach((button) => {
    button.addEventListener("click", () => {
      const turn = button.closest(".turn");
      if (!turn) return;
      const expanded = turn.dataset.originalExpanded !== "true";
      turn.dataset.originalExpanded = String(expanded);
      button.setAttribute("aria-expanded", String(expanded));
      const label = expanded ? button.dataset.hideLabel : button.dataset.showLabel;
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      const hiddenLabel = button.querySelector(".visually-hidden");
      if (hiddenLabel) hiddenLabel.textContent = label;
    });
  });

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewButton));
  });

  speakerFilter?.addEventListener("change", () => {
    state.speaker = speakerFilter.value;
    applyFilters();
  });

  chapterFilter?.addEventListener("change", () => {
    state.chapter = chapterFilter.value;
    applyFilters();
  });

  searchInput?.addEventListener("input", () => {
    state.query = searchInput.value;
    applyFilters();
  });

  resetButton?.addEventListener("click", () => {
    state.speaker = "all";
    state.chapter = "all";
    state.query = "";
    if (speakerFilter) speakerFilter.value = "all";
    if (chapterFilter) chapterFilter.value = "all";
    if (searchInput) searchInput.value = "";
    applyFilters();
  });

  sidebarCollapse?.addEventListener("click", () => {
    if (mobileQuery.matches) {
      setNavOpen(false);
      tocToggle?.focus();
      return;
    }
    setSidebarCollapsed(true);
    sidebarReveal?.focus();
  });

  sidebarReveal?.addEventListener("click", () => {
    setSidebarCollapsed(false);
    sidebarCollapse?.focus();
  });

  tocToggle?.addEventListener("click", () => {
    setNavOpen(!body.classList.contains("nav-open"));
  });

  tocLinks.forEach((link) => {
    link.addEventListener("click", () => setNavOpen(false));
  });

  tooltipTriggers.forEach((trigger) => {
    trigger.addEventListener("mouseenter", () => {
      if (matchMedia("(hover: hover)").matches) showTooltip(trigger);
    });
    trigger.addEventListener("mouseleave", () => {
      if (document.activeElement !== trigger) hideTooltip();
    });
    trigger.addEventListener("focus", () => showTooltip(trigger));
    trigger.addEventListener("blur", hideTooltip);
    trigger.addEventListener("click", () => showTooltip(trigger));
  });

  document.addEventListener("click", (event) => {
    if (body.classList.contains("nav-open") && !event.target.closest(".sidebar, #toc-toggle")) {
      setNavOpen(false);
    }
    if (activeTooltipTrigger && !event.target.closest("[data-tooltip], [data-note]")) {
      hideTooltip();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const navWasOpen = body.classList.contains("nav-open");
      setNavOpen(false);
      hideTooltip();
      if (navWasOpen) tocToggle?.focus();
    }
  });

  document.addEventListener("scroll", positionTooltip, true);
  window.addEventListener("resize", positionTooltip);

  mobileQuery.addEventListener?.("change", () => {
    setNavOpen(false);
    hideTooltip();
    syncSidebarControls();
  });

  systemThemeQuery.addEventListener?.("change", (event) => {
    if (!storageGet("transcript-theme")) setTheme(event.matches ? "dark" : "light", false);
  });

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      const active = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!active) return;
      tocLinks.forEach((link) => {
        link.classList.toggle("is-active", link.dataset.sectionLink === active.target.id);
      });
    }, { rootMargin: "-15% 0px -70% 0px", threshold: [0, 1] });
    chapters.forEach((chapter) => observer.observe(chapter));
  }

  setTheme(root.dataset.theme || (systemThemeQuery.matches ? "dark" : "light"), false);
  setView(state.view);
  setSidebarCollapsed(root.classList.contains("sidebar-collapsed"), false);
  setNavOpen(false);
  applyFilters();
})();
"""


def render_html_document(
    metadata: dict[str, object],
    preamble: str,
    source_preamble: str,
    sections: list[md.Section],
    source_sections: list[md.Section],
    source_entries: list[md.Entry],
    corrections: str,
    episode_dir: Path,
    language: str,
) -> str:
    zh = language.startswith("zh")
    source_language = md.meta_str(metadata, "source_language") or "en"
    original_title = md.meta_str(metadata, "title") or "Transcript"
    title = (
        (md.meta_str(metadata, "translated_title") if zh else "")
        or original_title
    )
    glossary = parse_glossary(preamble)
    source_lookup = read_source_lookup(source_entries)
    seen = {"translation": set(), "original": set()}
    speakers = collect_speakers(sections)
    url = md.meta_str(metadata, "url")
    cover = render_media(metadata, episode_dir, language)
    info = render_info_rows(metadata, language)
    translation_intro, translation_reference = split_preamble_reference(preamble)
    translation_intro_html = render_markdown_blocks(
        translation_intro, glossary, "translation", seen["translation"]
    )
    original_preamble_html = render_markdown_blocks(
        source_preamble, glossary, "original", seen["original"]
    )
    translation_reference_html = render_markdown_blocks(
        translation_reference, glossary, "translation", seen["translation"]
    )
    preamble_html = (
        '<div class="preamble-stack">'
        f'<section class="preamble-translation" lang="{html.escape(language, quote=True)}">'
        f'{translation_intro_html}</section>'
        + (
            f'<section class="preamble-original" lang="{html.escape(source_language, quote=True)}">'
            f'{original_preamble_html}</section>'
            if original_preamble_html
            else ""
        )
        + "</div>"
        + (
            f'<section class="preamble-reference preamble-translation" '
            f'lang="{html.escape(language, quote=True)}">{translation_reference_html}</section>'
            if translation_reference_html
            else ""
        )
    )
    sections_html = render_sections(
        sections,
        source_sections,
        source_lookup,
        metadata,
        glossary,
        seen,
        url,
        language,
    )
    corrections_html = (
        f'<section class="correction-section">{render_markdown_blocks(corrections)}</section>'
        if corrections.strip()
        else ""
    )
    speaker_options = "".join(
        f'<option value="{html.escape(name, quote=True)}">{html.escape(name)}</option>'
        for name in speakers
    )
    chapter_options = "".join(
        f'<option value="{section.anchor}">{index:02d} · {html.escape(section.title)}</option>'
        for index, section in enumerate(sections, start=1)
    )
    original_label = "原文" if zh else "Source"
    translation_label = "译文" if zh else "Translation"
    bilingual_label = "对照" if zh else "Compare"
    toc_label = "目录与筛选" if zh else "Contents and filters"
    search_placeholder = "搜索正文" if zh else "Search transcript"
    all_speakers = "全部人物" if zh else "All people"
    all_chapters = "全部章节" if zh else "All chapters"
    collapse_sidebar_label = "收起目录与筛选" if zh else "Collapse contents and filters"
    expand_sidebar_label = "展开目录与筛选" if zh else "Expand contents and filters"
    theme_to_light_label = "切换到浅色模式" if zh else "Switch to light mode"
    theme_to_dark_label = "切换到深色模式" if zh else "Switch to dark mode"
    original_title_markup = (
        f'<span class="title-original" lang="{html.escape(source_language, quote=True)}">'
        f'{html.escape(original_title)}</span>'
        if original_title and original_title != title
        else ""
    )
    theme_icons = (
        '<svg class="theme-icon-sun" viewBox="0 0 24 24" aria-hidden="true">'
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42'
        'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42'
        'M17.66 6.34l1.41-1.41"/></svg>'
        '<svg class="theme-icon-moon" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M20.5 14.2A8 8 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"/></svg>'
    )

    return f"""<!doctype html>
<html lang="{html.escape(language, quote=True)}" data-view="bilingual">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="light dark">
  <meta name="description" content="{html.escape(title, quote=True)}">
  <title>{html.escape(title)}</title>
  <script>
    (() => {{
      let theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      try {{
        const storedTheme = localStorage.getItem("transcript-theme");
        if (storedTheme === "light" || storedTheme === "dark") theme = storedTheme;
        if (localStorage.getItem("transcript-sidebar-collapsed") === "true") {{
          document.documentElement.classList.add("sidebar-collapsed");
        }}
      }} catch {{}}
      document.documentElement.dataset.theme = theme;
    }})();
  </script>
  <style>{build_css()}</style>
</head>
<body>
  <a class="skip-link" href="#transcript">跳到正文</a>
  <header class="masthead">
    <div class="masthead-inner">
      <div class="masthead-top">
        <h1><span class="title-translation">{html.escape(title)}</span>{original_title_markup}</h1>
        <button class="theme-toggle masthead-theme-toggle" id="theme-toggle" type="button" data-theme-toggle aria-pressed="false" aria-label="{html.escape(theme_to_dark_label, quote=True)}" title="{html.escape(theme_to_dark_label, quote=True)}" data-light-label="{html.escape(theme_to_light_label, quote=True)}" data-dark-label="{html.escape(theme_to_dark_label, quote=True)}">
          {theme_icons}
        </button>
      </div>
      <div class="meta-strip">{info}</div>
      {cover}
    </div>
  </header>

  <div class="reading-layout">
    <aside class="sidebar" id="sidebar" aria-label="{html.escape(toc_label, quote=True)}">
      <div class="sidebar-heading">
        <p class="sidebar-title">{html.escape(toc_label)}</p>
        <div class="sidebar-heading-actions">
          <button class="theme-toggle sidebar-theme-toggle" type="button" data-theme-toggle aria-pressed="false" aria-label="{html.escape(theme_to_dark_label, quote=True)}" title="{html.escape(theme_to_dark_label, quote=True)}" data-light-label="{html.escape(theme_to_light_label, quote=True)}" data-dark-label="{html.escape(theme_to_dark_label, quote=True)}">
            {theme_icons}
          </button>
          <button class="sidebar-toggle" id="sidebar-collapse" type="button" aria-controls="sidebar" aria-expanded="true" aria-label="{html.escape(collapse_sidebar_label, quote=True)}" title="{html.escape(collapse_sidebar_label, quote=True)}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>
          </button>
        </div>
      </div>
      <div class="filter-panel">
        <div class="filter-field">
          <label class="filter-label" for="speaker-filter">人物</label>
          <select id="speaker-filter">
            <option value="all">{html.escape(all_speakers)}</option>
            {speaker_options}
          </select>
        </div>
        <div class="filter-field">
          <label class="filter-label" for="chapter-filter">章节</label>
          <select id="chapter-filter">
            <option value="all">{html.escape(all_chapters)}</option>
            {chapter_options}
          </select>
        </div>
        <div class="filter-field">
          <label class="filter-label" for="transcript-search">搜索</label>
          <input id="transcript-search" type="search" placeholder="{html.escape(search_placeholder, quote=True)}">
        </div>
        <div class="view-switch" aria-label="显示模式">
          <button type="button" data-view-button="translation" aria-pressed="false">{html.escape(translation_label)}</button>
          <button type="button" data-view-button="bilingual" aria-pressed="true">{html.escape(bilingual_label)}</button>
          <button type="button" data-view-button="original" aria-pressed="false">{html.escape(original_label)}</button>
        </div>
        <button class="filter-reset" id="reset-filters" type="button">重置</button>
      </div>
      <nav class="toc">{render_toc(sections, source_sections)}</nav>
    </aside>

    <main class="reading-main" id="transcript">
      <button class="sidebar-reveal" id="sidebar-reveal" type="button" aria-controls="sidebar" aria-expanded="false" aria-label="{html.escape(expand_sidebar_label, quote=True)}" title="{html.escape(expand_sidebar_label, quote=True)}">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
        <span class="visually-hidden">{html.escape(toc_label)}</span>
      </button>
      <div class="main-toolbar">
        <button id="toc-toggle" type="button" aria-controls="sidebar" aria-expanded="false">目录</button>
        <span>{html.escape(md.meta_str(metadata, "duration"))}</span>
      </div>
      {preamble_html}
      <div id="chapter-list">{sections_html}</div>
      <p class="empty-state">没有符合当前筛选条件的内容。</p>
      {corrections_html}
    </main>
  </div>

  <div class="context-tooltip" id="context-tooltip" role="tooltip" hidden></div>
  <footer class="page-footer">
    <span>Generated from {html.escape(md.meta_str(metadata, "slug"))}</span>
  </footer>
  <script>{build_javascript()}</script>
</body>
</html>
"""


def write_html(
    output: Path,
    metadata: dict[str, object],
    preamble: str,
    source_preamble: str,
    sections: list[md.Section],
    source_sections: list[md.Section],
    source_entries: list[md.Entry],
    corrections: str,
    episode_dir: Path,
    language: str,
) -> str:
    document = render_html_document(
        metadata,
        preamble,
        source_preamble,
        sections,
        source_sections,
        source_entries,
        corrections,
        episode_dir,
        language,
    )
    expected = sum(len(group.timestamps) for section in sections for group in section.groups)
    rendered = document.count("<!-- ts:")
    if rendered != expected:
        raise ValueError(f"HTML timestamp coverage mismatch: expected {expected}, rendered {rendered}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return document


def main() -> int:
    args = parse_args()
    episode_dir = args.episode_dir.expanduser().resolve()
    transcript = args.transcript.expanduser().resolve()
    if not episode_dir.is_dir():
        print(f"Episode directory not found: {episode_dir}", file=sys.stderr)
        return 2
    if not transcript.is_file():
        print(f"Draft not found: {transcript}", file=sys.stderr)
        return 2
    try:
        metadata = md.read_metadata(episode_dir / "metadata.yaml")
        host = str(md.meta_map(metadata, "people").get("host", "主持人"))
        preamble, entries, draft_sections = md.read_drafts([transcript], host)
        fallback_titles: dict[str, str] = {}
        for value in args.section_title:
            key, separator, title = value.partition("=")
            if not separator or not re.fullmatch(r"\d{2}:\d{2}", key):
                raise ValueError(f"Invalid --section-title {value!r}; expected HH:MM=Title")
            fallback_titles[key] = title.strip()
        sections = md.build_sections(
            entries,
            draft_sections,
            args.section_minutes * 60,
            fallback_titles,
            args.max_turn_chars,
            args.language,
        )
        source_preamble = ""
        source_entries: list[md.Entry] = []
        source_sections: list[md.Section] = []
        if args.source_transcript:
            source_paths = [path.expanduser().resolve() for path in args.source_transcript]
            source_preamble, source_entries, source_draft_sections = md.read_drafts(
                source_paths, host
            )
            source_sections = md.build_sections(
                source_entries,
                source_draft_sections,
                args.section_minutes * 60,
                fallback_titles,
                args.max_turn_chars,
                args.language,
            )
        corrections = (
            args.corrections.expanduser().resolve().read_text(encoding="utf-8")
            if args.corrections and args.corrections.expanduser().resolve().is_file()
            else ""
        )
        output = (
            args.output.expanduser().resolve()
            if args.output
            else episode_dir / "index.html"
        )
        write_html(
            output,
            metadata,
            preamble,
            source_preamble,
            sections,
            source_sections,
            source_entries,
            corrections,
            episode_dir,
            args.language,
        )
        print(f"{output} ({len(sections)} sections, {len(source_entries)} source entries)")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
