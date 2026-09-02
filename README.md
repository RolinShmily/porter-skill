# Porter Skill (流媒体搬运工)

<p align="center">
  <a href="https://github.com/RolinShmily/porter-skill/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue" alt="Python Versions">
  <img src="https://img.shields.io/badge/FFmpeg-libass-orange.svg" alt="FFmpeg libass">
  <img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="mypy">
</p>

**Porter Skill (`porter-skill`)** 是专为 **AI 智能体（Agent）** 与**个人创作者**打造的跨平台（Windows / Linux / macOS）全自动流媒体搬运、AI 字幕提取、智能翻译与双版本熟肉视频压制出片流水线。

只需给出一个视频链接，即可一键自动输出结构规范的**原始物料资产**与**高质量双版本硬字幕熟肉成品**。

---

## 📺 平台支持与规划 (Supported Platforms & Roadmap)

底层基于平台适配器模式（Adapter Pattern）设计，当前深度适配并首期聚焦 YouTube，其余主流流媒体平台正在逐步规划支持：

- [x] **YouTube** (`youtube.com`, `youtu.be`) —— 深度适配（支持 1080p/4K 分离流下载、JS 签名挑战求解、多语言原生/机翻字幕提取、反爬/大会员 Cookie 会话注入）
- [x] **X / Twitter** (`x.com`, `twitter.com`, `t.co`) —— 深度适配（支持短链重定向秒级展开、推文标题智能清洗、1080p 视频流提取、9:16 竖屏手机画幅自适应排版）
- [x] **Instagram** (`instagram.com`, `instagr.am`, `ig.me`) —— 深度适配（支持 Reels、Posts、IGTV、多视频轮播 Carousels 智能过滤、Caption 标题语义提炼、免登录原生提取与 Embed 降级）
- [x] **TikTok** (`tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`) —— 深度适配（支持 Videos、Embeds、短链展开、原生/自动字幕提取、Caption 语义标题清洗与 9:16 竖屏画幅自适应）
- [x] **Bilibili (哔哩哔哩)** (`bilibili.com`, `b23.tv`, `bilibili.tv`) —— 深度适配（支持标准视频、番剧、课程、B23 短链、CC/AI JSON 字幕解析、SESSDATA/大会员会话注入与画质自适应）

---

## 🌟 核心特性 (Key Features)

- ⚡ **秒级轻量预检与短链展开 (Pre-flight Link Probe)**：
  - 1 秒内完成 URL 重定向展开（`t.co` / `bit.ly` 等）、追踪参数清洗与视频存在性快检；
  - 自动识别视频画幅比例（横屏 16:9 / 竖屏 9:16），提供独立探测指令 `scripts/inspect_link.py <URL>` 与 `--inspect`。
- 📱 **画幅自适应排版 (Aspect-Ratio Aware Styling)**：
  - 智能感知手机竖屏（9:16）与宽屏（16:9），竖屏自动适配 $\le 13$ 字意群断句与防遮挡安全底边距，横竖屏皆获得专业观影体验。
- ⚡ **极简依赖与开箱即用**：
  - 系统底线依赖**仅需 Python (>= 3.10) 与 FFmpeg**。
  - 无需预装任何外部收费工具或复杂的本地大型 ASR 二进制。
- 🚀 **智能字幕极速直连 (Zero-Latency Fast Path)**：
  - 自动探测并并发下载平台原生多语言字幕（如 YouTube `zh-Hans` / `zh` 翻译轨与 `en-orig` 原音轨）；
  - 自动毫秒级中英文语义对齐与长单行合并，**0 延迟、0 API Token 消耗**快速出片。
- 🎙️ **多引擎 ASR 链式自适应回退与广播级人声增强（双轨隔离 & 纯 Python 零 Key 闭环）**：
  - **双轨隔离声学增强 (`raw/audio_enhanced.wav`)**：内置 FFmpeg 原生三合一人声链（80~8000Hz 人声带通 + `afftdn` 自适应 FFT 降噪 + `dynaudnorm` 动态人声均衡），在 0.2 秒内消除电流麦与低频轰鸣并拉齐音量，大幅提升复杂视频与嘈杂演讲的 ASR 字准率；
  - **母版原音直通 (`-c:a copy`)**：Phase 4 成片压制依然直通复制 `raw/audio.wav` 原声，100% 保持成片音色真实与音质纯净；
  - 当源视频无原生字幕时，流水线按序自动尝试语音转录：
    $$\text{Whisper API (若配Key)} \longrightarrow \text{Pure Python Bcut 必剪 (免Key免费/长音频直连)} \longrightarrow \text{Google Web STT + 双层VAD递归切片 (免Key免费)} \longrightarrow \text{VideoCaptioner CLI (可选增强)}$$
  - Bcut ASR 独立直连突破代理并支持长音频大文件分块；Google STT 具备双层 VAD + 10s 上限递归硬切片保护，彻底杜绝连续对话/播客场景丢句断流；
  - 在纯净 Python + FFmpeg 环境下 100% 独立完成语音转录，无需下载 GB 级离线权重。
- 🌐 **多层次翻译与高可用容灾**：
  - **LLM 大模型驱动（配置 API 时）**：支持 DeepSeek / OpenAI / Claude 等模型，智能断句并修正专业同音错词；
  - **多级免配置兜底（零配置时）**：
    $$\text{Pure Python Bing (Copilot 免费)} \longrightarrow \text{Google HTTP (多端轮换/反爬伪装)} \longrightarrow \text{MyMemory 免费 API 兜底} \longrightarrow \text{VideoCaptioner CLI}$$
  - **中文字符自检 (CJK Validation)**：自动检验并修复未翻译假熟肉，确保 100% 汉化成功。
- ⚙️ **算力分级与硬件自适应极速压制**：
  - 自动探测宿主机硬件加速与 CPU 算力（Tier A: NVENC/QSV、Tier B: 8+核多线程、Tier C: N100/树莓派低功耗工控机）；
  - 自适应调优编码 Preset（`veryfast` / `ultrafast`）与 CRF，在低功耗轻量设备上压制提速 60%+；
  - 媒体下载优选 1080p 规格并优先采用无损流复制（Remuxing），避免重复重编码画质损失。
- 📝 **结构化台词本与中文意群句读 (Transcript & Chinese Phrasing)**：
  - 自动将破碎的 ASR / 平台字幕碎片按语法、静音间隙（$>0.6\text{s}$）与标点重构成完整的英文句子台词本（`raw/transcript.json` 与 `raw/transcript.txt`）；
  - 基于完整语句进行上下文语义翻译，杜绝碎词直译导致语序颠倒；
  - 根据中文句读与自然连词进行意群截断（单行 $\le 20$ 字），时间戳按意群字数比例平滑分配，彻底杜绝生硬截断与阅读疲劳。
- 🎨 **专业级排版与确定性无损压制**：
  - 中文主导排版：大号清晰中文字幕在上，自适应比例高亮英文字幕在下，单行居中不遮挡；
  - 采用 FFmpeg `libass` 矢量渲染，音频 `-c:a copy` 直通复制，极速压制且音质 0 损耗。
- 🍪 **反爬与大会员 Cookie 自动提取**：
  - 原生支持 `--cookies-from-browser chrome/edge/firefox` 直接读取浏览器会话，轻松跨越 429 限流与年龄限制。

---

## 📁 极简两级输出目录规范

每个任务以 `<video_id>_<safe_title>` 创建独立文件夹，保持极简的两级扁平结构：

```text
porter_output/<video_id>_<safe_title>/
├── raw/                              # 【一级：原始物料区 (Raw Assets)】
│   ├── video.mp4                     # 原始标准母版 (H.264 + AAC 广播级封装, faststart)
│   ├── audio.wav                     # 原始基准音轨 (16kHz 16bit 单声道 WAV)
│   ├── audio_enhanced.wav (可选)     # ASR 专属增强音轨 (三合一人声带通降噪均衡)
│   ├── transcript.json               # 结构化台词本 (句级起止时间/中英双语对/原始片段映射)
│   ├── transcript.txt                # 纯文本台词本 (带时间轴中英对照, 便于人工核对与检索)
│   ├── subtitle.srt                  # 原始英文/源语言字幕 (长单行规整版)
│   ├── subtitle_zh.srt (可选)        # 原始平台提取中文字幕 (若平台提供)
│   ├── cover.jpg                     # 原始高清封面图
│   └── metadata.json                 # 视频标题、标签、描述及抓取元数据
│
└── cooked/                           # 【二级：熟肉成品区 (Cooked Releases)】
    ├── subtitle_bilingual.srt        # 中英双语字幕 (SRT 纯文本)
    ├── subtitle_bilingual.ass        # 中英双语字幕 (ASS 矢量排版样式)
    ├── subtitle_zh.srt               # 纯中文字幕 (SRT 纯文本)
    ├── subtitle_zh.ass               # 纯中文字幕 (ASS 矢量排版样式)
    ├── video_bilingual.mp4           # 【熟肉成品 1】烧录双语硬字幕高清视频
    └── video_zh.mp4                  # 【熟肉成品 2】烧录纯中文硬字幕高清视频
```

---

## 🛠️ 安装与快速上手 (Installation & Quickstart)

### 1. 环境准备 (Windows / Linux / macOS)

确保系统中已安装 **Python 3.10+** 和 **FFmpeg**（需包含 `libass` 库）：

- **Windows 用户**（使用 winget 极速安装）：
  ```powershell
  winget install Python.Python.3.12
  winget install Gyan.FFmpeg
  ```
- **Ubuntu / Debian 用户**：
  ```bash
  sudo apt update && sudo apt install -y ffmpeg python3 python3-pip
  ```
- **macOS 用户**：
  ```bash
  brew install ffmpeg python
  ```

### 2. 方式 A: 通过 `npx skills add` 一键为 AI Agent 安装（推荐）

适用于各类支持 Agent Skills 规范的 AI 编程助手（如 Pi Coding Agent, Claude Code, Cursor, Windsurf 等）：

```bash
# 全局安装到所有检测到的 AI Agent (推荐)
npx skills add RolinShmily/porter-skill -g

# 或安装到当前项目工作区
npx skills add RolinShmily/porter-skill

# 指定特定 Agent 并自动确认 (如 pi, claude-code)
npx skills add RolinShmily/porter-skill -g -a pi -y
```

### 3. 方式 B: 作为独立 Python CLI 工具安装

```bash
# 克隆仓库
git clone https://github.com/RolinShmily/porter-skill.git
cd porter-skill

# 使用一键环境脚本配置（推荐）
bash scripts/setup_env.sh

# 或通过 pip / uv 安装
pip install -e .
```

### 4. 方式 C: 手动 Git Clone 到 Agent 技能目录

本仓库符合标准 Agent Skill 规范，亦可直接克隆到 Agent 的技能目录（如 `pi-coding-agent`）：

```bash
git clone https://github.com/RolinShmily/porter-skill.git ~/.pi/agent/skills/porter-skill
```

---

## 💻 命令行使用指南 (CLI Usage)

### 1. 环境体检与诊断
```bash
porter --doctor
# 或使用免安装脚本:
python scripts/run_porter.py --doctor
```

### 2. 标准搬运执行（下载 ➔ 提取 ➔ 翻译 ➔ 双版本出片）
```bash
# 标准出片
porter "https://www.youtube.com/watch?v=gYxZt9Qe0fk" -o "./porter_output"

# 使用免安装脚本执行
python scripts/run_porter.py "https://www.youtube.com/watch?v=gYxZt9Qe0fk" -o "./porter_output"
```

### 3. 常用进阶参数
```bash
# 携带 Chrome 浏览器 Cookie（防 429 与年龄限制）
porter "<URL>" --cookies-from-browser chrome

# 仅生成原始物料与字幕文件，跳过视频压制
porter "<URL>" --skip-burn

# 仅压制双语版本熟肉
porter "<URL>" --only-bilingual

# 仅压制纯中文版本熟肉
porter "<URL>" --only-zh
```

---

## ⚙️ 配置文件与环境设置 (`config.json`)

系统默认具备 0 配置兜底能力。若需使用 DeepSeek/OpenAI 大模型翻译或自定义字幕字体样式，可复制 `config.example.json` 为 `config.json`：

```bash
cp config.example.json config.json
```

```json
{
  "llm": {
    "api_key": "sk-your-deepseek-or-openai-key",
    "api_base": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  },
  "asr": {
    "engine": "bijian",
    "language": "auto",
    "whisper_api_key": "",
    "whisper_api_base": "https://api.openai.com/v1",
    "whisper_model": "whisper-1"
  },
  "style": {
    "zh_font": "Microsoft YaHei",
    "en_font": "Arial",
    "zh_font_size": 52,
    "en_font_size": 34,
    "zh_primary_color": "&H00FFFFFF",
    "en_primary_color": "&H0000FFFF",
    "outline_color": "&H00000000",
    "outline_width": 3.5,
    "shadow": 1.5,
    "margin_v": 30
  },
  "cookies_browser": "chrome",
  "cookies_file": ""
}
```

### 动态配置命令
```bash
# 查看当前生效配置（自动脱敏 Key）
porter --config-show

# 快速修改配置项
porter --config-set llm.api_key="sk-..."
porter --config-set cookies_browser="chrome"
```

---

## 🏗️ 架构与扩展 (Architecture)

流水线采用高度解耦的四阶段流水线设计（Pipeline & Adapter Pattern）：

```
[ 输入视频链接 ]
       │
       ▼
┌────────────────────────────────────────┐
│  Phase 1: 素材抓取 (Extractors)        │ ──> H.264 母版、16kHz WAV、原始字幕、高清封面
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Phase 2: 字幕提取与翻译 (Subtitle)    │ ──> 原生字幕对齐 / 多引擎 ASR / LLM 语义优化
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Phase 3: 字幕排版 (Formatting)        │ ──> 生成中英双语与纯中文 SRT / ASS 矢量样式
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Phase 4: FFmpeg 硬字幕压制 (Burn)     │ ──> video_bilingual.mp4 & video_zh.mp4
└────────────────────────────────────────┘
```

详细技术架构与各阶段输入输出规约请参阅 [references/ARCHITECTURE.md](references/ARCHITECTURE.md)。

---

## 🧪 自动化测试与质量保障

项目配备了严格的类型检查与单元测试套件：

```bash
# 运行单元与集成测试
pytest

# 代码格式化与规范检查
ruff check .
ruff format --check .

# 严格静态类型检查
mypy porter_skill
```

---

## 💖 鸣谢与致谢 (Acknowledgements)

本项目站在巨人的肩膀上，借鉴与集成了以下卓越开源项目的优秀设计与技术能力，特此致谢：

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**：根据 **The Unlicense** 许可证借鉴与调用，提供跨平台流媒体音视频与字幕的高效解析与提取能力；
- **[VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)**：根据 **GPL-3.0 License** 许可证借鉴其优秀的音视频断句对齐、ASR 语音转录与字幕处理设计思路；
- **[FFmpeg](https://ffmpeg.org/)** (含 `libass`)：根据 **LGPL-2.1+ / GPL-2.0+** 许可证作为多媒体标准化、音频处理、声学降噪与专业 ASS 矢量字幕渲染核心基石。

<details>
<summary><b>📜 点击展开查看各开源项目许可证详情 (Open Source Licenses)</b></summary>

### 1. yt-dlp (The Unlicense)

```text
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
```

### 2. VideoCaptioner (GNU General Public License v3.0)

```text
GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
Everyone is permitted to copy and distribute verbatim copies
of this license document, but changing it is not allowed.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```

### 3. FFmpeg & libass (LGPL-2.1+ / GPL-2.0+ / ISC)

```text
FFmpeg is licensed under the GNU Lesser General Public License (LGPL) version 2.1 or later.
However, FFmpeg incorporates several optional parts and optimizations that are covered by the
GNU General Public License (GPL) version 2 or later (e.g. libx264).

libass is licensed under the ISC License (a permissive license functionally equivalent to the 2-clause BSD license):
Copyright (c) 2006-2024 libass contributors
Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted.
```

</details>

---

## 📄 开源许可证 (License)

本项目基于 [MIT License](LICENSE) 协议开源。
