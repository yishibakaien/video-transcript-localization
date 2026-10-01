# 视频标本

> 由 `yishibakaien` 维护的个人开源项目。

**简体中文** | [English](README.en.md)

将在线视频转换成完整、易读、可检索的**简体中文 HTML 逐字稿**。本仓库同时是一个可供 AI 编程代理调用的 skill，以及已处理视频的文稿库。

## 快速开始

### 1. 获取并打开仓库

这个 skill 不是通过 pip 或 npm 发布的独立软件包；请直接克隆本仓库，并将它作为 AI 代理的工作区使用：

```bash
git clone https://github.com/yishibakaien/video-transcript-localization.git
cd video-transcript-localization
```

skill 定义位于 [`.agents/skills/video-transcript-localization`](.agents/skills/video-transcript-localization/SKILL.md)。在 Kiro 中打开本仓库后，可以用 `$video-transcript-localization` 调用它。

### 2. 安装依赖

需要 Python 3.9+ 和 `yt-dlp`。仓库脚本只依赖 Python 标准库，不需要安装 `requirements.txt`。

```bash
python3 --version
# macOS（Homebrew）
brew install yt-dlp

# Linux 或其他已安装 Python/pip 的环境
python3 -m pip install --user -U yt-dlp

yt-dlp --version
```

没有字幕时可选用本地语音识别（ASR）：Apple Silicon 安装 [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)，其他机器安装 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。平台差异、登录字幕和 ASR 导入方式见 [platforms.md](.agents/skills/video-transcript-localization/references/platforms.md)。

### 3. 交给 AI 代理处理

在仓库根目录的 Kiro 对话中发送：

```text
使用 $video-transcript-localization 处理 https://www.youtube.com/watch?v=VIDEO_ID
```

代理会提取字幕，通读上下文，纠正明显的识别错误，撰写简体中文文稿，并生成 `episodes/NNN-slug/index.html`。外语视频还会生成校正后的原文，HTML 页面可切换双语对照。

> skill 需要代理实际阅读 `source/video.info.json` 和完整 `source.segments.tsv`，再编写标注草稿、校正记录和元数据；脚本负责提取、渲染与校验，并不会自动翻译或判断说话人。

## 手动运行

如果不通过代理，可以在仓库根目录按以下流程操作。`init_episode.py` 输出的剧集目录用 `EP` 代替：

```bash
SKILL=.agents/skills/video-transcript-localization
python3 "$SKILL/scripts/init_episode.py" --url "https://www.youtube.com/watch?v=VIDEO_ID"
# 将上一条命令输出的目录填入 EP
python3 "$SKILL/scripts/extract_captions.py" EP
```

随后先阅读 `EP/source/video.info.json` 与 `EP/source.segments.tsv`，并按 [translation-format.md](.agents/skills/video-transcript-localization/references/translation-format.md) 编写草稿。

**外语视频**：先写校正后的原文草稿，再写中文翻译和校正记录：

```bash
python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.<source>.annotated.txt \
  --language <source> --role source --no-html

python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized --corrections EP/corrections.zh-CN.md
```

**中文源视频**：不翻译，但仍要写 `transcript.zh-CN.annotated.txt`，完成同音字、标点和说话人校正。当前渲染器需要将同一份草稿显式用作对照原文：

```bash
python3 "$SKILL/scripts/render_markdown.py" EP EP/drafts/transcript.zh-CN.annotated.txt \
  --language zh-CN --role localized \
  --source-transcript EP/drafts/transcript.zh-CN.annotated.txt \
  --corrections EP/corrections.zh-CN.md
```

命令成功时会校验时间戳覆盖、说话人标注和广告折叠，并生成 `EP/transcript.zh-CN.md` 与 `EP/index.html`。B 站或抖音需要自己的登录状态时，在初始化和提取命令中加入 `--cookies-from-browser chrome`；cookie 仅用于本机当次请求，不会被保存或转发。

## 产物与规范

每个完成的文稿都包含：

- 完整覆盖原始字幕时间轴的正文，以及自动校验；
- 结合视频简介、章节、赞助链接所做的上下文纠错；
- 导读、术语对照、章节导航和可跳转的视频时间戳；
- 默认折叠的广告口播；
- 可检索的 YAML 元数据和重要校正记录。

不要手改渲染产生的 `transcript.*.md` 或 `index.html`；应修改 `drafts/`、`metadata.yaml` 或 `corrections.zh-CN.md` 后重新渲染。完整工作流与质量规则见 [SKILL.md](.agents/skills/video-transcript-localization/SKILL.md)。

## 已完成的文稿

[在浏览器中阅读全部文稿](https://yishibakaien.github.io/video-transcript-localization/)。HTML 阅读页支持深浅色主题、响应式布局，以及双语或单语视图。

<!-- episodes:start -->
| # | 标题 | 频道 | 平台 | 时长 |
|:---|:---|:---|:---|:---|
| 001 | [遥视者 #001（美军）：“他们正朝这里来”……｜乔·麦克莫尼格尔](https://yishibakaien.github.io/video-transcript-localization/episodes/001-remote-viewer-joe-mcmoneagle/index.html) | Aaron Alexander | YouTube | 01:31:52 |
| 002 | [击碎记忆冠军现实的秘密遥视实验｜尼尔森·德利斯](https://yishibakaien.github.io/video-transcript-localization/episodes/002-the-secret-remote-viewing-experiment-that-broke-a-memory-cha/index.html) | THIRD EYE DROPS with Michael Phillip | YouTube | 02:02:24 |
| 003 | [UFO 劫持案亲历者描述可怕的抓捕者｜UFO Witness｜Travel Channel](https://yishibakaien.github.io/video-transcript-localization/episodes/003-ufo-abductee-describes-horrifying-captors-ufo-witness-travel/index.html) | Travel Channel | YouTube | 00:08:02 |
<!-- episodes:end -->

## 项目结构

```text
.agents/skills/video-transcript-localization/
|-- SKILL.md                    # skill 工作流与质量规则
|-- references/                 # 草稿格式、平台说明
`-- scripts/                    # 初始化、提取、Markdown/HTML 渲染、README 同步
episodes/NNN-slug/
|-- metadata.yaml               # 剧集元数据
|-- source/                     # 原始字幕与视频信息
|-- source.segments.tsv         # 标准化时间轴（不修改）
|-- drafts/                     # 由代理编写的标注草稿
|-- corrections.zh-CN.md        # 字幕校正记录
|-- index.html                  # 简体中文双语阅读页（主要成果）
|-- transcript.zh-CN.md         # 用于构建 HTML 的简体中文文稿
`-- transcript.<source>.md      # 外语视频的校正原文文稿
index.html                      # GitHub Pages 入口页
```

## 文稿目录维护

`<!-- episodes:start -->` 与 `<!-- episodes:end -->` 之间的列表由 `episodes/*/metadata.yaml` 自动生成，请勿手动修改。成功渲染时会自动刷新；仅改动元数据、增删或重命名剧集后，可手动运行：

```bash
python3 .agents/skills/video-transcript-localization/scripts/update_readme.py
```

功能、工作流、命令、依赖、支持平台或目录结构变更时，请同步更新中文主 README（`README.md`）和英文 README（`README.en.md`）。

## 许可

代码、脚本和说明文档采用 MIT 许可，见 [LICENSE](LICENSE)。原始视频、字幕和音频仍归各自创作者所有；提交内容前请确认自己有权处理和分享。