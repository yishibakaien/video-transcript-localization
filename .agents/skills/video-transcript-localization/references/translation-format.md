# Draft Format and Output Reference (format version 3)

You write annotated drafts (`drafts/transcript.<target>.annotated.txt`, or ordered `part-NN.txt` files). `scripts/render_markdown.py` turns them into the final Markdown and validates them. Never hand-edit the rendered `.md`; fix the draft or `metadata.yaml` and re-render.

For a foreign-language video, write the corrected source draft first (`drafts/transcript.<source>.annotated.txt`) and render it with `--language <source> --role source --no-html`. Use the same section boundaries and speaker labels as the translation, but keep the body in the source language. The localization render then discovers that source draft automatically for the HTML original/translation comparison. For a Chinese-source video, write only the Chinese annotated draft.

## Draft Syntax

A draft has three kinds of content:

1. **Preamble** — any Markdown before the first timestamp line. Rendered verbatim after the episode info. Use it for `## 导读` and `## 术语对照`. Do not use `# ` (single-hash) headings here.
2. **Section markers** — a line `# 标题` starts a new `##` section at the next entry.
3. **Entries** — `[HH:MM:SS] 标签：正文`. One line per speaker turn. A following line without a timestamp is a new paragraph in the same turn.

```text
## 导读

- 麦克莫尼格尔解释星门计划的真实来历：它最初叫“贡多拉愿望”，目的是评估遥视是否构成威胁。
- 他认为时间与空间是人的行为“创造”出来的矩阵，并以自己的濒死体验说明。
- 后半段讨论意识、死亡、外星生命与人类文明的风险。

## 术语对照

| 原文 | 译名 | 说明 |
|:---|:---|:---|
| Stargate Project | 星门计划 | 美国军方遥视研究项目 |
| remote viewing | 遥视 | |
| Monroe Institute | 门罗研究所 | |

# 星门计划到底是什么
[00:00:00] 主持人｜Aaron Alexander：星门计划是什么？
[00:00:01] 嘉宾｜Joe McMoneagle：我可以告诉你，网上关于星门计划的说法，九成都是胡说八道。
[00:00:01] 主持人｜Aaron Alexander：在你看来，地球上最强大的实体是谁？
[00:01:10] 嘉宾｜Joe McMoneagle：我的意思是，很多年前……我们不断建造这张矩阵。
你听过这种说法：人死后，会在一瞬间回顾自己的一生……
[00:14:13] 广告口播｜Aaron Alexander｜ButcherBox：我想花一点时间，介绍一位我真心喜欢的赞助商……
[00:15:00] 广告口播｜Aaron Alexander：……网址是 butcherbox.com/align。
[00:15:00] 主持人｜Aaron Alexander：你能和过去、未来的自己对话吗？
```

Rules:

- Every timestamp in `source.segments.tsv` must appear at least once, in source order. Do not invent, shift, or renumber timestamps.
- When a segment contains several speakers (or an ad followed by conversation), repeat its timestamp on several lines, one per speaker/part.
- Consecutive lines from the same speaker are merged into one turn by the renderer. A sentence split across two segments is re-joined automatically when the first part does not end with sentence punctuation.
- Break long monologues into paragraphs at natural topic shifts (about every 150–300 Chinese characters) using continuation lines.
- Do not put Markdown formatting in speaker labels.

## Speaker Labels

| Draft label | Use for |
|:---|:---|
| `主持人｜Name` | host |
| `嘉宾｜Name` | guest |
| `其他发言者｜Name / Role` | anyone else identified |
| `未知说话人` | attribution cannot be established |
| `旁白` | narration or voice-over (rendered as a NOTE callout) |
| `音乐｜Music / Lyrics` | meaningful lyrics or vocal music (NOTE callout) |
| `广告口播｜Host｜Sponsor` | host-read sponsor message; the sponsor field is needed only on the first line of each ad |
| `广告旁白｜Sponsor` | separate advertising voice |

`广告口播` without a name defaults to `people.host` from `metadata.yaml`.

## Sections

- Place a `# 标题` line roughly every 5–15 minutes, at real topic shifts. Prefer the creator's chapters in `source/video.info.json` when they exist.
- Titles are descriptive, about 8–20 characters, and never mention sponsors or ads.
- If a draft has no `# ` lines, the renderer falls back to fixed 10-minute sections (`--section-minutes`, `--section-title HH:MM=Title`), which reads worse — avoid it.

## Preamble

- `## 导读`: 3–6 bullets covering the core ideas, claims, and conclusions of the video, not its sponsors.
- `## 术语对照`: the glossary from the context pass — names, organizations, works, and technical terms with the chosen rendering. It fixes terminology and lets English terms be searched.
- Keep the preamble short; the transcript is the main content.

## Ambiguity Markers

Keep inline notes short and rare:

- `[可能为：…]` — context-supported but uncertain correction.
- `[原文字面：…]` — literal wording when the meaning is unclear.
- `[听不清]` — unintelligible audio.
- `（注：…）` — a brief explanation of a cultural reference or genuine ambiguity.

## Correction Log

`corrections.<target>.md` is appended verbatim after the transcript, so it must not contain front matter. Record only significant fixes; skip trivial punctuation or filler cleanup.

```markdown
## 原字幕校正记录

原始字幕完整保留在 `source.segments.tsv`；以下是翻译前依据上下文所做的重要校正。

### 人名、机构与专有名词

| 时间 | 原字幕 | 校正为 | 依据 |
|:---|:---|:---|:---|
| 00:00:38 | `Joe McMagle` | `Joe McMoneagle` | 视频标题与访谈上下文 |
```

Suggested groups: people/organizations/terms; brands and URLs; speaker splits and attribution; other meaning-changing fixes. Omit the file when there are no significant corrections.

## Rendered Output

The renderer produces, in order: front matter → title → TIP note → 本期信息 → 人物 → preamble → 章节导航 → sections → correction log.

- Dialogue turn — speaker info is small and attached to its text; the content is the only full-size element. Hosts, guests, and other named speakers show only their name (roles live in the 人物 table); narration, ads, and unknown speakers show the role:

  ```markdown
  <!-- ts: [00:36:17] -->
  <sub>Aaron Alexander · [00:36:17](https://www.youtube.com/watch?v=ID&t=2177s)</sub><br>
  译文……

  下一段译文……
  ```

- Advertisement (collapsed by default in VS Code, GitHub, Obsidian, Typora):

  ```markdown
  <a id="ad-00-14-13"></a>
  <details class="ad">
  <summary>广告｜ButcherBox · 00:14:13 起，约 1 分 20 秒（已折叠，点击展开）</summary>

  <!-- ts: [00:14:13] -->
  <sub>广告口播｜Aaron Alexander · …</sub><br>
  广告译文……

  </details>
  ```

- Timestamp links work for YouTube, Bilibili, and Vimeo; other platforms show plain times.
- Front matter fields `contains_ads`, `ad_break_count`, `ad_segment_count`, `sponsors`, and `format_version` are computed from the draft. Everything else comes from `metadata.yaml`.

## Metadata Fields You Fill

In `metadata.yaml` after translating:

```yaml
translated_title: "中文标题"
status: "complete"
tags:
  - 播客
  - 访谈
people:
  host: "Aaron Alexander"
  guest: "Joe McMoneagle"
quality_review:
  full_context_read: true
  caption_errors_corrected: true
  speaker_attribution_reviewed: true
  advertisements_folded: true
  translation_reviewed: true
```

Tags should be useful for later retrieval: format (播客 / 访谈 / 讲座 / 纪录片), main topics, and key named subjects.
