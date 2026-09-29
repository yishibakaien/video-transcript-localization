# 视频标本

[English](README.md) | **简体中文**

把在线视频转换成完整、易读、可检索的**简体中文 HTML 逐字稿**。

本项目由两部分组成：一个 AI 代理技能（[`.agents/skills/video-transcript-localization`](.agents/skills/video-transcript-localization/SKILL.md)），以及已处理完成的视频文稿库。把视频链接交给 AI 编程代理后，它会：

1. 下载字幕；
2. 通读全文、理解上下文；
3. 纠正明显的语音识别错误；
4. 翻译全文；
5. 先渲染 Markdown，再生成独立的 HTML 阅读页。

目前已支持 YouTube；工作流同样覆盖 B 站、抖音、Vimeo、其他 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 支持的网站、用户提供的字幕文件，以及本地语音识别（ASR）。Markdown 文件保留为可检索、可版本控制的中间文档；HTML 阅读页是主要阅读界面。

## 已完成的文稿

[在浏览器中阅读全部文稿](https://yishibakaien.github.io/video-specimen/)

生成的 HTML 是独立的阅读页，支持深浅色主题、响应式布局，以及双语或单语视图。

<!-- episodes:start -->
| # | 标题 | 频道 | 平台 | 时长 |
|:---|:---|:---|:---|:---|
| 001 | [遥视者 #001（美军）：“他们正朝这里来”……｜乔·麦克莫尼格尔](episodes/001-remote-viewer-joe-mcmoneagle/index.html) | Aaron Alexander | YouTube | 01:31:52 |
| 002 | [击碎记忆冠军现实的秘密遥视实验｜尼尔森·德利斯](episodes/002-the-secret-remote-viewing-experiment-that-broke-a-memory-cha/index.html) | THIRD EYE DROPS with Michael Phillip | YouTube | 02:02:24 |
| 003 | [UFO 劫持案亲历者描述可怕的抓捕者｜UFO Witness｜Travel Channel](episodes/003-ufo-abductee-describes-horrifying-captors-ufo-witness-travel/index.html) | Travel Channel | YouTube | 00:08:02 |
<!-- episodes:end -->

## 每份文稿包含什么

- **完整正文**：不删减、不概括，每个字幕时间戳都有覆盖，并由程序校验。
- **结合上下文纠错**：借助全文以及视频简介、章节、赞助链接，修正人名、品牌、网址、数字和术语；重要修正记录在文末附录。
- **准确易读的翻译**：全文使用同一张术语表，以意思为先，去掉口头禅和结巴。
- **保留原文**：外语视频会另外生成校正后的原文文稿，配套 HTML 可按原始语言对照查看。
- **阅读辅助**：导读、术语对照、章节导航和主题分节；长段落自动分段。
- **弱化的说话人信息**：每段上方只有一行小字「名字 · 时间戳」，点击时间戳可跳到视频对应位置。
- **广告默认折叠**：赞助口播放在 `<details>` 折叠块中，不展开就看不到。
- **可检索的元数据**：YAML front matter 记录人物、标签、赞助商、平台和字幕来源。

## 使用方法

直接告诉 AI 代理，例如：

```text
使用 $video-transcript-localization 处理 https://www.youtube.com/watch?v=VIDEO_ID
```

也可以在项目根目录手动运行。`SKILL` 是技能目录，`EP` 是 `init_episode.py` 输出的剧集目录：

```bash
SKILL=.agents/skills/video-transcript-localization
python3 $SKILL/scripts/init_episode.py --url "https://www.youtube.com/watch?v=VIDEO_ID"   # 输出 EP
python3 $SKILL/scripts/extract_captions.py EP             # 字幕 + source.segments.tsv
# 对外语视频，代理先编写并渲染校正后的原文草稿
python3 $SKILL/scripts/render_markdown.py EP EP/drafts/transcript.<source>.annotated.txt \
  --language <source> --role source --no-html
# 然后由代理编写 EP/drafts/transcript.zh-CN.annotated.txt 和 EP/corrections.zh-CN.md
python3 $SKILL/scripts/render_markdown.py EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized --corrections EP/corrections.zh-CN.md
```

渲染时会自动校验，并同步刷新两份 README 中的文稿列表。

需要登录才能获取字幕的 B 站或抖音视频，加上 `--cookies-from-browser chrome`，使用你自己的浏览器登录状态。没有字幕的视频，参见 [platforms.md](.agents/skills/video-transcript-localization/references/platforms.md)。

## 环境要求

- Python 3.9+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（`brew install yt-dlp`）
- 可选，用于没有字幕的视频：[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)（Apple Silicon）或 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

## 隐私

除非你明确把它们推送到你自己的仓库，脚本不会上传 cookie、字幕或译文。B 站和抖音可以在导入时读取你自己浏览器里的登录状态，这些 cookie 只在当次网络请求中使用，不会被保存或转发。

## 许可

代码、脚本和说明文档采用 MIT 许可，见 [LICENSE](LICENSE)。剧集正文另有版权说明，见 [`episodes/LICENSE`](episodes/LICENSE)——原始视频、字幕和音频仍归各自创作者所有。

## 目录结构

```text
.agents/skills/video-transcript-localization/
|-- SKILL.md                    # 代理使用的工作流与质量规则
|-- references/                 # 草稿格式、平台说明
`-- scripts/                    # 初始化、提取、Markdown/HTML 渲染、README 同步
episodes/NNN-slug/
|-- metadata.yaml               # 剧集元数据
|-- source/                     # 原始字幕与视频信息
|-- source.segments.tsv         # 标准化时间轴（不修改）
|-- drafts/                     # 代理编写的标注草稿
|-- corrections.zh-CN.md        # 字幕校正记录
|-- index.html                  # 简体中文双语阅读页（主要成果）
|-- transcript.zh-CN.md         # 用于构建 HTML 的简体中文文稿
`-- transcript.<source>.md      # 外语视频的校正原文文稿
index.html                      # GitHub Pages 上的入口页
```

## README 的维护

`episodes:start` / `episodes:end` 标记之间的文稿列表由 `episodes/*/metadata.yaml` 自动生成，请勿手动修改；每次渲染都会自动刷新。手动刷新：

```bash
python3 .agents/skills/video-transcript-localization/scripts/update_readme.py
```

技能的功能或流程有变化时，请同步更新 `README.md` 和 `README.zh-CN.md` 中的说明文字，保持两份内容一致。
