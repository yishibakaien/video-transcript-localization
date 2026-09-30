# Video Specimen

> Personal open-source project, maintained under the `yishibakaien` identity.

**English** | [简体中文](README.zh-CN.md)

Turn online videos into complete, readable, searchable **Simplified Chinese HTML transcripts**.

The project is an agent skill ([`.agents/skills/video-transcript-localization`](.agents/skills/video-transcript-localization/SKILL.md)) plus a library of processed episodes. You give an AI coding agent a video link. It then:

1. downloads the captions;
2. reads the whole transcript to understand the context;
3. fixes obvious speech-recognition errors;
4. translates the transcript;
5. renders the Markdown and then a standalone HTML reading page.

YouTube is supported today. Bilibili, Douyin, Vimeo, other [yt-dlp](https://github.com/yt-dlp/yt-dlp) sites, supplied subtitle files, and local speech recognition (ASR) are covered by the workflow as well. The Markdown file remains as a searchable, versionable intermediate document; the HTML page is the main reading interface.

## Transcripts

[Read all transcripts online](https://yishibakaien.github.io/video-transcript-localization/)

The generated HTML is a standalone reading page: it supports light/dark themes, responsive layouts, and bilingual or single-language views.

<!-- episodes:start -->
| # | Title | Channel | Platform | Duration |
|:---|:---|:---|:---|:---|
| 001 | [Remote Viewer #001 (US MILITARY) Sees Them Coming... \| Joe McMoneagle](https://yishibakaien.github.io/video-transcript-localization/episodes/001-remote-viewer-joe-mcmoneagle/index.html) | Aaron Alexander | YouTube | 01:31:52 |
| 002 | [The Secret Remote Viewing Experiment That Broke A Memory Champion's Reality \| Nelson Dellis](https://yishibakaien.github.io/video-transcript-localization/episodes/002-the-secret-remote-viewing-experiment-that-broke-a-memory-cha/index.html) | THIRD EYE DROPS with Michael Phillip | YouTube | 02:02:24 |
| 003 | [UFO Abductee Describes Horrifying Captors \| UFO Witness \| Travel Channel](https://yishibakaien.github.io/video-transcript-localization/episodes/003-ufo-abductee-describes-horrifying-captors-ufo-witness-travel/index.html) | Travel Channel | YouTube | 00:08:02 |
<!-- episodes:end -->

## What Each Transcript Contains

- **Complete text** — nothing is summarized away; every caption timestamp is covered and machine-verified.
- **Context-aware corrections** — names, brands, URLs, numbers, and terms are fixed using the whole transcript plus the video's description, chapters, and sponsor links. Significant fixes are logged in an appendix.
- **Accurate, readable translation** — one consistent glossary, meaning-first wording, and no filler words or stutters.
- **Original text included** — foreign-language videos also produce a corrected source-language transcript, so the companion HTML can show each turn in the original language.
- **Reading aids** — summary (导读), glossary (术语对照), chapter navigation, and thematic sections. Long answers are split into paragraphs.
- **Quiet speaker labels** — a small `name · timestamp` line above each turn; the timestamp jumps to that moment in the video.
- **Ads folded away** — sponsor reads are collapsed in `<details>` blocks, so they stay out of sight unless expanded.
- **Searchable metadata** — YAML front matter with people, tags, sponsors, platform, and caption provenance.

## Usage

Ask your agent, for example:

```text
Use $video-transcript-localization to process https://www.youtube.com/watch?v=VIDEO_ID
```

Or run the pipeline by hand from the project root. `SKILL` is the skill directory and `EP` is the episode directory that `init_episode.py` prints:

```bash
SKILL=.agents/skills/video-transcript-localization
python3 $SKILL/scripts/init_episode.py --url "https://www.youtube.com/watch?v=VIDEO_ID"   # prints EP
python3 $SKILL/scripts/extract_captions.py EP             # captions + source.segments.tsv
# For foreign-language videos, the agent writes the corrected source draft first
python3 $SKILL/scripts/render_markdown.py EP EP/drafts/transcript.<source>.annotated.txt \
  --language <source> --role source --no-html
# The agent then writes EP/drafts/transcript.zh-CN.annotated.txt and EP/corrections.zh-CN.md
python3 $SKILL/scripts/render_markdown.py EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized --corrections EP/corrections.zh-CN.md
```

Rendering validates the result and refreshes the transcript lists in both READMEs.

For Bilibili or Douyin videos that require your own login, add `--cookies-from-browser chrome`. For videos without captions, see [platforms.md](.agents/skills/video-transcript-localization/references/platforms.md).

## Requirements

- Python 3.9+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`brew install yt-dlp`)
- Optional, for videos without captions: [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (Apple Silicon) or [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

## Privacy

The workflow never uploads cookies, captions, or transcripts anywhere unless
you explicitly push them to a repository you control. Bilibili/Douyin
imports can read cookies from your own browser to authenticate as you;
those cookies are only used for the network request in the running command
and are not stored or forwarded.

## License

Code, scripts, and documentation are MIT licensed — see [LICENSE](LICENSE).
Source videos, captions, and original audio remain the property of their respective creators.

## Project Layout

```text
.agents/skills/video-transcript-localization/
|-- SKILL.md                    # workflow and quality rules for the agent
|-- references/                 # draft format, platform notes
`-- scripts/                    # init, extract, Markdown/HTML rendering, README sync
episodes/NNN-slug/
|-- metadata.yaml               # episode record
|-- source/                     # raw subtitles and video info
|-- source.segments.tsv         # normalized timeline (never edited)
|-- drafts/                     # annotated drafts written by the agent
|-- corrections.zh-CN.md        # caption correction log
|-- index.html                  # Simplified Chinese bilingual reading page (main deliverable)
|-- transcript.zh-CN.md         # Simplified Chinese transcript used to build the HTML page
`-- transcript.<source>.md      # corrected source transcript for foreign-language videos
index.html                      # landing page for GitHub Pages
```

## Keeping the READMEs Current

The transcript lists between the `episodes:start` / `episodes:end` markers are generated from `episodes/*/metadata.yaml`; do not edit them by hand. They refresh automatically on every render. To refresh them manually:

```bash
python3 .agents/skills/video-transcript-localization/scripts/update_readme.py
```

When the skill's features or workflow change, update the prose in both `README.md` and `README.zh-CN.md` so they stay in sync.
