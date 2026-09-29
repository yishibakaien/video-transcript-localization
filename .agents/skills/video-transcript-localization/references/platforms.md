# Caption Acquisition by Platform

Priority: creator/human captions → platform captions (including auto-generated) → ASR. `extract_captions.py` applies this order automatically when `source/video.info.json` lists the available tracks. Always keep the raw file under `source/subtitles/`.

## YouTube

```bash
scripts/init_episode.py --url "https://www.youtube.com/watch?v=ID"
scripts/extract_captions.py EPISODE_DIR
```

- Human tracks (`en`) win over automatic ones (`en-orig`). Automatic YouTube captions are usually punctuated but mangle names, brands, and URLs; expect to correct them.
- If the default client fails (`The page needs to be reloaded`, empty results), the scripts retry with `android_vr`. Override with `--player-client NAME` (repeatable).
- HTTP 429 means rate limiting: wait before retrying and do not loop.
- Timestamp links use `&t=SECONDSs`.

## Bilibili

```bash
scripts/init_episode.py --url "https://www.bilibili.com/video/BV..." --cookies-from-browser chrome
scripts/extract_captions.py EPISODE_DIR --cookies-from-browser chrome
```

- Tracks: uploader subtitles (`zh-Hans`, `zh-CN`, `en-US`, …) and AI subtitles (`ai-zh`). AI subtitles usually require login, hence the user's own browser cookies.
- The source language is detected as `zh-CN`; the workflow then corrects and formats the Chinese instead of translating.
- Danmaku (`danmaku.xml`) is not a transcript; ignore it.
- Multi-part videos (`?p=2`): process each part as its own episode, or ask the user.
- Timestamp links use `?t=SECONDS`.

## Douyin / TikTok

- Videos rarely carry subtitle tracks, and yt-dlp's Douyin extractor usually needs fresh cookies (`--cookies-from-browser chrome`).
- If `extract_captions.py` finds no subtitles, use the ASR fallback below.
- Burned-in on-screen captions are not extractable as text; use ASR.
- Douyin has no deep-link timestamp parameter, so rendered times are plain text.

## Vimeo and Other yt-dlp Sites

Try `extract_captions.py` first; inspect tracks with `yt-dlp --list-subs URL` when the language is missing. Vimeo timestamp links use `#t=SECONDSs`.

## Supplied Subtitle Files

```bash
scripts/extract_captions.py EPISODE_DIR --subtitle-file /path/to/file.srt
```

Accepts `.srt`, `.vtt`, and `.json3`. Compare the final timestamp with the video duration to confirm the file is complete.

## ASR Fallback

Use ASR when no captions exist (typical for Douyin) or when the user asks. Download audio only, transcribe to SRT, then import it:

```bash
yt-dlp -f "bestaudio/best" --no-playlist -o "EPISODE_DIR/source/audio.%(ext)s" URL
# Apple Silicon (fast):   pip install mlx-whisper
mlx_whisper EPISODE_DIR/source/audio.m4a --model mlx-community/whisper-large-v3-turbo \
  --output-format srt --output-dir EPISODE_DIR/source/subtitles
# Other machines:         pip install faster-whisper   (or whisper.cpp)
scripts/extract_captions.py EPISODE_DIR --subtitle-file EPISODE_DIR/source/subtitles/audio.srt
```

- Pass `--language zh` or `--language en` to the ASR tool when known; it reduces errors.
- Set `caption_type: "asr"` and a `caption_source` naming the tool and model (for example `mlx-whisper large-v3-turbo`) in `metadata.yaml`.
- ASR has no speaker diarization by default; infer speakers from context and keep `speaker_attribution: "inferred"`.
- Delete or keep `source/audio.*` according to the user's preference; it is not needed after transcription.

## Access Restrictions

Cookies are for the user's own logged-in session only. For members-only, paid, age-restricted, or region-locked content, use material the user is authorized to access, or ask for an exported subtitle file. Never bypass access controls.
