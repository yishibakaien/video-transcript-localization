# Contributing

Thanks for your interest in improving this project.

## Adding a new episode

New episodes follow the existing agent skill workflow. If you submit one, please include:

1. `metadata.yaml` matching `format_version: 3`
2. raw captions and timeline under `source/`
3. annotated source and Simplified-Chinese drafts under `drafts/`
4. corrected source and localized transcripts at the episode root
5. a correction log if any speech-recognition errors were fixed

Render with:

```bash
python3 .agents/skills/video-transcript-localization/scripts/render_markdown.py \
  <EP> <EP>/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized --corrections <EP>/corrections.zh-CN.md
```

`<EP>` is the episode directory printed by `init_episode.py`. The importer
refreshes both README tables and the root site listing.

## Editing code

- Keep generated HTML self-contained: no external CSS or JavaScript files.
- Run `render_markdown.py` after changing a draft; do not edit regenerated
  Markdown or HTML by hand.
- Keep Chinese and English READMEs in sync.

## Licensing

Code and documentation are MIT licensed. Episode content carries its own
notice in [`episodes/LICENSE`](episodes/LICENSE), because the original
videos and captions belong to their respective creators. Please only submit
episodes you have the right to process and share in this research format.
