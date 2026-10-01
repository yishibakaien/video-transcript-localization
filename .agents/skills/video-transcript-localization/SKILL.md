---
name: video-transcript-localization
description: Extract captions from YouTube, Bilibili, Douyin, Vimeo, other yt-dlp platforms, or supplied subtitle/ASR files, then quickly produce a complete, context-aware Simplified Chinese Markdown transcript with ASR errors corrected, speakers labeled, a summary, glossary, chapter navigation, clickable timestamps, and advertisements folded away by default.
---

# Video Transcript Localization

Turn one video into one complete, readable, searchable Simplified Chinese HTML reading page — fast.

## Deliverable

`episodes/NNN-slug/index.html`, rendered by `scripts/render_markdown.py`. It contains:

- YAML front matter for search and filtering (people, tags, sponsors, caption provenance);
- episode info, people, **导读** (summary) and **术语对照** (glossary) at the top;
- a chapter list and thematic `##` sections;
- every speaker turn led by a small, non-bold `<sub>Name · [00:12:34](video link)</sub>` line, so the spoken content stays visually dominant; roles are shown once in the people table, and the timestamp jumps to that moment in the video;
- advertisements inside collapsed `<details class="ad">` blocks, so they stay out of sight unless expanded;
- hidden `<!-- ts: [HH:MM:SS] -->` comments proving that every source timestamp is covered;
- the correction log appended at the end.

## Layout

```text
episodes/NNN-slug/
|-- metadata.yaml
|-- source/
|   |-- video.info.json         # title, channel, description, chapters, tags (context for corrections)
|   `-- subtitles/              # raw track (JSON3/SRT/VTT); never edit
|-- source.segments.tsv         # normalized timeline; never edit
|-- drafts/
|   |-- transcript.<source>.annotated.txt  # for foreign-language videos; corrected source text
|   `-- transcript.zh-CN.annotated.txt     # the Chinese translation (or part-NN files)
|-- corrections.zh-CN.md        # significant caption fixes
|-- index.html                  # standalone HTML reading page; never hand-edit
`-- transcript.zh-CN.md         # Markdown intermediate used to build the HTML page; never hand-edit
```

For a foreign-language video, also produce `transcript.<source-language>.md` from a corrected source draft. The HTML reader uses it for bilingual comparison; without it, the “原文” view shows `原文未提供`. Chinese-source videos use the same corrected Chinese draft for both roles and need no separate source transcript.

## Fast Workflow

Scripts live in this skill's `scripts/` directory and need Python 3.9+ and `yt-dlp`.

1. **Init** — `scripts/init_episode.py --url URL`. The title, channel, duration, upload date, platform, and source language are fetched automatically; description, chapters, and tags are saved to `source/video.info.json`. Pass the title positionally only when fetching fails.
2. **Captions** — `scripts/extract_captions.py EPISODE_DIR`. It downloads the best track (human captions first), writes `source.segments.tsv`, and records `caption_source` / `caption_type` in `metadata.yaml`. Use `--cookies-from-browser chrome` for Bilibili/Douyin videos that need the user's own login. When no captions exist, follow `references/platforms.md` (ASR fallback).
3. **Context pass** — read `source/video.info.json` and the whole TSV once before writing anything. Decide, from the full context:
   - who speaks (host, guests, narrator) and where speaker changes happen inside segments;
   - a glossary of names, organizations, products, and technical terms with one fixed Chinese rendering each;
   - every advertisement span and its sponsor;
   - 5–15-minute sections at real topic shifts (prefer the creator's chapters);
   - the ASR fixes to apply (see Quality Rules).
4. **Write the source transcript** — foreign-language videos only. Write `drafts/transcript.<source>.annotated.txt`: preamble (Summary + Glossary), `# section titles`, then speaker turns containing corrected source-language text. Apply the ASR fixes here first, using the same speaker attribution as the translation. Render and validate it:

   ```bash
   scripts/render_markdown.py EP EP/drafts/transcript.<source>.annotated.txt \
     --language <source> --role source --no-html
   ```

   This creates `transcript.<source>.md`.
5. **Write the translation** — `drafts/transcript.zh-CN.annotated.txt`: preamble (导读 + 术语对照), `# 章节标题` lines, then one line per speaker turn with the corrected translation. Read `references/translation-format.md` for the exact syntax before writing.
6. **Corrections** — write `corrections.zh-CN.md` with only the significant fixes (names, brands, URLs, numbers, terms, meaning-changing errors, speaker splits).
7. **Metadata** — update `metadata.yaml` in one edit: `translated_title`, `tags`, `people`, `status: complete`, `quality_review` flags.
8. **Render and validate** — one command; it validates automatically and exits non-zero on problems:

   ```bash
   scripts/render_markdown.py EP EP/drafts/transcript.zh-CN.annotated.txt \
     --language zh-CN --role localized --corrections EP/corrections.zh-CN.md
   ```

   Fix every `ERROR` in the draft (never in the rendered file) and re-render. A successful render also refreshes the transcript lists in the project READMEs (see README Maintenance).
9. **Report** the absolute path of `index.html` and the validation line.

### Long Videos

For videos longer than about 30 minutes, write the draft in parts of roughly 15–20 minutes (`drafts/transcript.zh-CN.part-01.txt`, `part-02.txt`, …) and pass all parts to the renderer in order. Part 01 carries the preamble.

For a foreign-language long video, write the corrected source draft in matching numbered parts as well (`drafts/transcript.<source>.part-01.txt`, `part-02.txt`, …). The renderer discovers these parts automatically for the comparison HTML when `--source-transcript` is omitted. When passing parts explicitly, keep both lists in the same order.

When subagents are available, translate parts in parallel: first write `drafts/context.md` (summary, people, glossary, ad spans, section outline, correction decisions); then give each subagent `context.md`, its TSV line range, the two neighboring lines on each side, and `references/translation-format.md`. Afterwards, check part boundaries for split sentences and terminology drift.

### Chinese-Source Videos

When the source is already Chinese (typical for Bilibili and Douyin), do not translate. Correct ASR homophones and wrong characters, add punctuation, remove filler, label speakers, fold ads, and use the same draft format. Convert Traditional characters to Simplified.

## Quality Rules

### Correct obvious errors before translating

Use evidence in this order: repeated or clearly spoken mentions elsewhere in the transcript → `video.info.json` (title, description, chapters, tags, channel name) → sponsor URLs and discount codes → well-established public facts.

- **Certain** (evidence supports exactly one reading): translate the corrected meaning directly. Log it in `corrections.zh-CN.md` if it touches a name, brand, URL, number, term, or the meaning of a sentence.
- **Probable**: translate the most plausible meaning and add `[可能为：…]`.
- **Unrecoverable**: translate literally and add `[原文字面：…]`, or write `[听不清]` for unintelligible audio.
- Never invent facts, names, or numbers.

Typical ASR failures: split or garbled names (`McMagle` → `McMoneagle`), brand/URL mangling (`quint.com` → `quince.com`), homophones, show names (`the line podcast` → `the Align podcast` when the sponsor URLs end in `/align`), dropped negations (`can` / `can't`), broken numbers, duplicated words, and mis-segmented sentences. For Chinese ASR: 同音字、近音词、专有名词错字、缺标点。

### Translate from the whole context

- Keep one glossary rendering per term; first mention of a person, organization, or work is `中文译名（Original）`, later mentions use the Chinese name. Keep brands, products, URLs, and discount codes in their original form.
- Translate meaning, not word order. Write fluent written Chinese that still sounds like the speaker; keep tone, hedges, humor, emphasis, and uncertainty.
- Remove pure disfluencies (um, uh, you know, stutters, false starts, `the the the`) but never drop information, even when repetitive.
- Resolve pronouns and ellipses from context when English is ambiguous; if the source is genuinely ambiguous, keep the ambiguity or add a short `（注：…）`.
- Keep original units and add a conversion only when it aids understanding: `6 英尺（约 1.8 米）`.
- Never summarize the transcript body. Every segment, including intros, recaps, sponsor reads, and closing lines, is translated.

### Speakers

- Labels come from the video's context, not the caption service's guesses. `>>` in captions often marks a speaker change.
- When one TSV segment contains several speakers, split it into several draft lines that reuse the same timestamp.
- Use the role alone (`嘉宾`, `未知说话人`) until the video establishes the person's name.

### Advertisements

- Mark as ads: third-party sponsor reads (including the lead-in such as "let me take a moment to talk about our sponsor" and the call to action), and paid promotion of the creator's own products, courses, or memberships.
- Do not mark as ads: brief "like and subscribe" reminders or ordinary mentions of products inside the conversation.
- Label ads `广告口播｜Host｜Sponsor` or `广告旁白｜Sponsor`. The renderer folds consecutive ad lines into one collapsed block and counts them in the front matter.
- Translate ads fully (they stay folded), but never mention sponsors in section titles or the 导读.

## README Maintenance

The project root has `README.md` (Simplified Chinese, primary) and `README.en.md` (English). Each links to the other at the top. Keep both in sync with the project:

- **Transcript lists** — the block between `<!-- episodes:start -->` and `<!-- episodes:end -->` is generated from `episodes/*/metadata.yaml`. Both READMEs link each episode's GitHub Pages reading page. `render_markdown.py` refreshes it after every successful render. After adding, deleting, or renaming an episode, or editing its title, channel, platform, or duration in `metadata.yaml` without re-rendering, run `scripts/update_readme.py`. Never hand-edit the block.
- **Prose** — when you change this skill's features, workflow, commands, requirements, supported platforms, or directory layout, update the matching sections in both READMEs in the same change, English first, then Chinese with identical meaning.

## Non-Negotiable Checks (enforced by the renderer's validation)

- Every timestamp in `source.segments.tsv` appears, in order; the first and last match.
- Every turn has a speaker label.
- Every advertisement is inside a folded block; `contains_ads`, `ad_break_count`, and `ad_segment_count` match the document.
- Required front matter is present (fill `tags` and `people` in `metadata.yaml`).
- Automatic or ASR captions are disclosed through `caption_type` / `caption_source`.

## References

- `references/translation-format.md` — draft syntax, labels, preamble, sections, correction-log format. Read before writing a draft.
- `references/platforms.md` — caption acquisition per platform, login cookies, and the ASR fallback.
