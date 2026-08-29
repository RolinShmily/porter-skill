# 任务实施规划清单 (TASKS.md)

---

## 一、 里程碑与阶段拆解 (Milestones)

### Milestone 1: 规范定稿与设计对齐 (Plan Phase) - [已完成]
- [x] 确立极简两级输出目录规范（一级 `raw/` 原始物料，二级 `cooked/` 熟肉成品）；
- [x] 确立平台支持范围：架构预留多流媒体抽象，首期（v1）专注于 **YouTube 深度适配**；
- [x] 确立跨平台（Windows & Linux）双轨引导策略（命令一键安装 + 官网下载手动配 PATH 步骤）；
- [x] 确立智能字幕回退策略（官方人工字幕优先，无字幕/仅机翻回退 ASR）；
- [x] 确立双版本熟肉压制规范（双语硬字幕版 + 纯中文硬字幕版，音频 copy 极速出片）；
- [x] 完善 `README.md`、`ARCHITECTURE.md` 与 `TASKS.md` 规划文档。

---

### Milestone 2: 跨平台环境自检与双轨引导模块 (`porter_skill.env_check`) - [已完成]
- [x] 实现 `check_python()`：验证 Python 版本是否 >= 3.10，输出跨平台引导；
- [x] 实现 `check_ffmpeg()`：跨平台检索 `ffmpeg` / `ffprobe` 二进制与 `libass` 滤镜支持；
- [x] 实现 Windows 双轨引导输出（winget 命令 + 官网下载链接 + 环境变量 Path 添加说明）；
- [x] 实现 Linux 多发行版包管理器引导输出（apt / pacman / dnf）；
- [x] 实现 `check_packages()`：检查 `yt_dlp` 与 `videocaptioner` 安装情况；
- [x] 实现 `check_llm()`：检查 LLM API Key 与 Base URL 配置；
- [x] 编写 `--doctor` 命令行诊断入口。

---

### Milestone 3: 平台物料抓取与标准化模块 (`porter_skill.extractors.youtube`) - [已完成]
- [x] 抽象 `BasePlatformExtractor` 基类与工厂入口；
- [x] 实现 `YouTubeExtractor`：
  - 调用 `yt_dlp` 下载最佳画质视频流与封面图；
  - 智能区分 YouTube `subtitles`（人工官方）与 `automatic_captions`（自动机翻）；
- [x] 实现 FFmpeg 标准化转码：强制规整为 H.264 High Profile + AAC 192k + yuv420p + faststart 的 `raw/video.mp4`；
- [x] 实现 16kHz 16bit 单声道 WAV 音轨抽取 `raw/audio.wav`；
- [x] 完成一级目录 `raw/` 构建与元数据 JSON 保存。

---

### Milestone 4: 字幕智能提取、优化与排版模块 (`porter_skill.subtitle`) - [已完成]
- [x] 实现智能回退控制器：若存在有效 `raw/subtitle.srt` 则直接作为基准源，否则调用 VideoCaptioner 执行 ASR 识别；
- [x] 对接 VideoCaptioner / LLM 执行标点修复、语义断句与双语翻译；
- [x] 输出二级目录字幕文件：
  - `cooked/subtitle_bilingual.srt` & `cooked/subtitle_bilingual.ass`（双语对照排版）
  - `cooked/subtitle_zh.srt` & `cooked/subtitle_zh.ass`（纯中文单行排版）。

---

### Milestone 5: FFmpeg 极速硬字幕压制模块 (`porter_skill.synthesizer`) - [已完成]
- [x] 实现 Windows / Linux 跨平台 FFmpeg 滤镜路径转义函数；
- [x] 实现双语硬字幕熟肉压制 `cooked/video_bilingual.mp4`；
- [x] 实现纯中文硬字幕熟肉压制 `cooked/video_zh.mp4`；
- [x] 确保音频流采用 `-c:a copy` 直通复制，保证无损音质与高压制速度。

---

### Milestone 6: 流水线总控与 Pi Agent Skill 注册 (`porter_skill.pipeline` & `SKILL.md`) - [已完成]
- [x] 整合端到端总调度流水线 `run_pipeline(url, output_dir)`；
- [x] 实现 CLI 命令行入口 `python -m porter_skill "<YOUTUBE_URL>" -o <output_dir>`；
- [x] 编写 Pi Agent 规范文件 `SKILL.md`，注册到 `~/.pi/agent/skills/video-porter/`；
- [x] 使用真实 YouTube 链接执行端到端验收测试。
