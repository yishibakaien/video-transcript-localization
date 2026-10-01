# Video Specimen

> A personal open-source project maintained under the `yishibakaien` identity.

[简体中文](README.md) | **English**

Turn online videos into complete, readable, searchable **Simplified Chinese HTML transcripts**. This repository is both an AI-agent skill and a library of processed episodes.

## Quick Start

### 1. Get and open the repository

This skill is not a standalone pip or npm package. Clone this repository and use it as the AI agent workspace:

```bash
git clone https://github.com/yishibakaien/video-transcript-localization.git
cd video-transcript-localization
```

The skill lives at [`.agents/skills/video-transcript-localization`](.agents/skills/video-transcript-localization/SKILL.md). After opening this repository in Kiro, invoke it as `$video-transcript-localization`.

### 2. Install dependencies

Python 3.9+ and `yt-dlp` are required. The repository scripts otherwise use only the Python standard library; there is no `requirements.txt` to install.

```bash
python3 --version
# macOS with Homebrew
brew install yt-dlp

# Linux or another environment with Python and pip
python3 -m pip install --user -U yt-dlp

yt-dlp --version
```

For videos without captions, local ASR is optional: use [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon or [faster-whisper](https://github.com/SYSTRAN/faster-whisper) elsewhere. See [platforms.md](.agents/skills/video-transcript-localization/references/platforms.md) for platform differences, authenticated captions, and ASR import.

### 3. Ask the AI agent to process a video

In a Kiro chat at the repository root, send:

```text
Use $video-transcript-localization to process https://www.youtube.com/watch?v=VIDEO_ID
```

The agent extracts captions, reads the full context, corrects clear recognition errors, writes the Simplified Chinese transcript, and creates `episodes/NNN-slug/index.html`. Foreign-language videos also get a corrected source transcript for bilingual HTML comparison.

> The skill requires the agent to read `source/video.info.json` and the complete `source.segments.tsv`, then write the annotated drafts, correction log, and metadata. Scripts extract, render, and validate; they do not translate or infer speakers by themselves.

## Run Manually

To use the pipeline without an agent, run these commands from the repository root. Substitute `EP` with the directory printed by `init_episode.py`:

```bash
SKILL=.agents/skills/video-transcript-localization
python3 "$SKILL/scripts/init_episode.py" --url "https://www.youtube.com/watch?v=VIDEO_ID"
# Replace EP with the path printed above.
python3 "$SKILL/scripts/extract_captions.py" EP
```

Read `EP/source/video.info.json` and `EP/source.segments.tsv`, then write drafts according to [translation-format.md](.agents/skills/video-transcript-localization/references/translation-format.md).

**Foreign-language video:** write the corrected source draft first, then the Chinese translation and correction log:

```bash
python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.<source>.annotated.txt \
  --language <source> --role source --no-html

python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized --corrections EP/corrections.zh-CN.md
```

**Chinese-source video:** do not translate, but write `transcript.zh-CN.annotated.txt` to correct homophones, punctuation, and speaker labels. The current renderer needs the same draft supplied explicitly as its comparison source:

```bash
python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized \
  --source-transcript EP/drafts/transcript.zh-CN.annotated.txt \
  --corrections EP/corrections.zh-CN.md
```

A successful command validates timestamp coverage, speaker labels, and folded ads, then writes `EP/transcript.zh-CN.md` and `EP/index.html`. For Bilibili or Douyin with your own authenticated account, pass `--cookies-from-browser chrome` to the initialization and extraction commands. Cookies are used only for that local request; they are not saved or forwarded.

## Output and Standards

Every finished transcript contains:

- complete source-timestamp coverage and automated validation;
- context-aware corrections based on the video description, chapters, and sponsor links;
- a summary, glossary, chapter navigation, and video-jump timestamps;
- sponsor reads folded by default;
- searchable YAML metadata and a log of meaningful corrections.

Do not hand-edit generated `transcript.*.md` or `index.html`. Update `drafts/`, `metadata.yaml`, or `corrections.zh-CN.md`, then re-render. The full workflow and quality requirements are in [SKILL.md](.agents/skills/video-transcript-localization/SKILL.md).

## Completed Transcripts

[Read all transcripts online](https://yishibakaien.github.io/video-transcript-localization/). The standalone HTML reader supports light/dark themes, responsive layouts, and bilingual or single-language views.

<!-- episodes:start -->
| # | Title | Channel | Platform | Duration |
|:---|:---|:---|:---|:---|
| 001 | [Remote Viewer #001 (US MILITARY) Sees Them Coming... \| Joe McMoneagle](https://yishibakaien.github.io/video-transcript-localization/episodes/001-remote-viewer-joe-mcmoneagle/index.html) | Aaron Alexander | YouTube | 01:31:52 |
| 002 | [The Secret Remote Viewing Experiment That Broke A Memory Champion's Reality \| Nelson Dellis](https://yishibakaien.github.io/video-transcript-localization/episodes/002-the-secret-remote-viewing-experiment-that-broke-a-memory-cha/index.html) | THIRD EYE DROPS with Michael Phillip | YouTube | 02:02:24 |
| 003 | [UFO Abductee Describes Horrifying Captors \| UFO Witness \| Travel Channel](https://yishibakaien.github.io/video-transcript-localization/episodes/003-ufo-abductee-describes-horrifying-captors-ufo-witness-travel/index.html) | Travel Channel | YouTube | 00:08:02 |
<!-- episodes:end -->

## Project Layout

```text
.agents/skills/video-transcript-localization/
|-- SKILL.md                    # skill workflow and quality rules
|-- references/                 # draft format and platform notes
`-- scripts/                    # initialization, extraction, rendering, README synchronization
episodes/NNN-slug/
|-- metadata.yaml               # episode metadata
|-- source/                     # raw captions and video information
|-- source.segments.tsv         # normalized timeline; do not edit
|-- drafts/                     # annotated drafts written by the agent
|-- corrections.zh-CN.md        # caption correction log
|-- index.html                  # Simplified Chinese bilingual reader (main deliverable)
|-- transcript.zh-CN.md         # Simplified Chinese Markdown used to build HTML
`-- transcript.<source>.md      # corrected source transcript for foreign-language videos
index.html                      # GitHub Pages landing page
```

## Maintaining the Catalog

The list between `<!-- episodes:start -->` and `<!-- episodes:end -->` is generated from `episodes/*/metadata.yaml`; do not edit it manually. Rendering refreshes it automatically. After only editing metadata or adding, removing, or renaming an episode, run:

```bash
python3 .agents/skills/video-transcript-localization/scripts/update_readme.py
```

When features, workflow, commands, dependencies, supported platforms, or the directory layout change, update both the Chinese main README (`README.md`) and English README (`README.en.md`).

## License

Code, scripts, and documentation are MIT licensed — see [LICENSE](LICENSE). Original videos, captions, and audio remain their creators' property; confirm you have the right to process and share a submission.