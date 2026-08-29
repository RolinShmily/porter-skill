# 系统架构规划方案 (ARCHITECTURE.md)

本文档详述 **Video Porter Skill（流媒体搬运工）** 的系统设计、平台适配层架构、跨平台环境诊断体系、执行流水线规范及跨平台兼容方案。

---

## 一、 平台适配器架构设计 (Platform Extensibility)

不同流媒体平台（YouTube、Bilibili、Twitter/X 等）在视频分流机制、音频编码格式、防盗链机制、元数据结构以及字幕提供方式上存在显著差异：

| 差异维度 | YouTube | Bilibili | Twitter / 其他 |
| :--- | :--- | :--- | :--- |
| **音视频流** | DASH/HLS 分离流 (VP9/AV1/Opus) | 音视频流分离 (m4s 格式) | 单一合成流 (大多为 H.264+AAC) |
| **字幕生态** | 人工多语言字幕 + 自动 ASR 字幕 | CC 字幕 / AI 总结字幕 | 无官方字幕，全靠画面压制或无字幕 |
| **防盗链与验证** | PO Token / JS 签名挑战 / 年龄限制 | SESSDATA / WBI 签名 | 访客 Token / 速率限制 |

### 1. 适配器接口契约 (Adapter Interface)
为了保持核心处理链路（转码、ASR、翻译、压制）的纯粹性，系统采用抽象基类解耦物料抓取层：

```python
class BasePlatformExtractor(ABC):
    """流媒体平台物料抓取抽象基类"""
    
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """判断当前平台适配器是否支持该 URL"""
        pass

    @abstractmethod
    def extract_raw_materials(self, url: str, raw_dir: Path) -> RawMaterialResult:
        """
        抓取原始物料并输出至 raw/ 目录:
        - raw/video.mp4 (标准化 H.264+AAC 母版)
        - raw/audio.wav (16kHz 单声道基准音轨)
        - raw/cover.jpg (高清封面)
        - raw/subtitle.srt (官方/人工字幕，若存在)
        """
        pass
```

### 2. 首期范围锁定：YouTube 深度适配 (v1 Scope)
* **明确边界**：首期版本**显式声明仅支持 YouTube 平台**（`YouTubeExtractor`）。
* **YouTube 专用抓取策略**：
  1. **格式优选器**：利用 `yt-dlp` 指定 `bestvideo+bestaudio/best` 保证最高画质；
  2. **字幕分流识别**：严格区分 `subtitles`（官方/人工上传）与 `automatic_captions`（平台自动机翻）；
  3. **母版标准化**：无论拉取到的是 AV1、VP9 还是 Opus 音频，全部经由 FFmpeg 强制规整为广播级兼容标准（H.264 + AAC + yuv420p + faststart）。

---

## 二、 跨平台环境自检与双轨引导架构 (`env_check`)

### 1. 诊断检测项
在流水线启动前或运行 `--doctor` 时，系统执行 4 项诊断：
1. **Python 运行时检测**：检查是否满足 `>= 3.10`；
2. **FFmpeg & libass 检测**：检查 `ffmpeg` / `ffprobe` 二进制是否存在，以及是否编译了 `libass` / `subtitles` 滤镜；
3. **Python 核心包检测**：检测 `yt_dlp` 与 `videocaptioner`；
4. **LLM 与 ASR 配置检测**：检测 API Key 与 Base URL。

### 2. 跨平台双轨引导输出设计
当检测未通过时，系统根据操作系统输出结构化、针对性的指引：

* **Windows 平台**：
  - **路径 A（一键包管理器）**：输出 `winget install Python.Python.3.12` 与 `winget install Gyan.FFmpeg`；
  - **路径 B（官网手动下载 + 环境变量配置）**：
    - Python 官网链接（提醒勾选 `Add python.exe to PATH`）；
    - FFmpeg Gyan.dev 编译包下载链接；
    - 输出 4 步将 `C:\ffmpeg\bin` 添加至 Windows 系统变量 `Path` 的图文式控制台说明。
* **Linux 平台**：
  - 自动识别发行版（Debian/Ubuntu/Arch/Fedora），输出对应的 `apt` / `pacman` / `dnf` 安装指令。

---

## 三、 确定性 4 阶段流水线数据流

```text
               ┌────────────────────────────────────────────────────────┐
               │             输入：单个 YouTube 视频链接 (URL)           │
               └───────────────────────────┬────────────────────────────┘
                                           │
                        ┌──────────────────▼──────────────────┐
                        │   Phase 0: 跨平台环境自检与引导     │
                        │ (Python 3.10+ / FFmpeg+libass / LLM) │
                        └──────────────────┬──────────────────┘
                                           │
                        ┌──────────────────▼──────────────────┐
                        │ Phase 1: YouTube 物料抓取与标准化   │
                        │   (yt-dlp 抓取 + FFmpeg 母版转码)   │
                        └──────────────────┬──────────────────┘
                                           │
                 ┌─────────────────────────┴─────────────────────────┐
                 │                                                   │
                 ▼ 【一级输出: raw/】                                 ▼
         ┌─────────────────────────┐                     ┌─────────────────────────┐
         │ • raw/video.mp4         │                     │ • 提取 16kHz WAV 音轨   │
         │ • raw/audio.wav         │                     └────────────┬────────────┘
         │ • raw/cover.jpg         │                                  │
         │ • raw/subtitle.srt (可选)│                                  │
         └─────────────────────────┘                                  │
                                                                      │
                        ┌─────────────────────────────────────────────▼─────────┐
                        │ Phase 2: 智能字幕提取 (Smart Fallback 策略)           │
                        │ ├─ 存在官方/人工字幕 ──> 直接采用                     │
                        │ └─ 无人工字幕/仅机翻 ──> 调用 VideoCaptioner ASR      │
                        └─────────────────────────────┬─────────────────────────┘
                                                      │
                        ┌─────────────────────────────▼─────────────────────────┐
                        │ Phase 3: LLM 语义优化与双语翻译                       │
                        │ • 标点修复 / 语义断句 / 上下文翻译                    │
                        │ • 输出双语字幕与纯中文字幕 (SRT / ASS 矢量排版)       │
                        └─────────────────────────────┬─────────────────────────┘
                                                      │
                        ┌─────────────────────────────▼─────────────────────────┐
                        │ Phase 4: FFmpeg libass 硬字幕全量压制                 │
                        │ • 双语 ASS ──> cooked/video_bilingual.mp4             │
                        │ • 中文 ASS ──> cooked/video_zh.mp4                    │
                        │ • 音频流 stream copy (无损极速)                       │
                        └─────────────────────────────┬─────────────────────────┘
                                                      │
                                                      ▼ 【二级输出: cooked/】
                                        ┌───────────────────────────────────────┐
                                        │ • cooked/subtitle_bilingual.{srt,ass} │
                                        │ • cooked/subtitle_zh.{srt,ass}        │
                                        │ • cooked/video_bilingual.mp4          │
                                        │ • cooked/video_zh.mp4                 │
                                        └───────────────────────────────────────┘
```

---

## 四、 关键技术细节与命令规范

### 1. 母版转码标准 (一级输出 `raw/video.mp4`)
```bash
ffmpeg -y -i "download_raw.mp4" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 44100 \
  -movflags +faststart \
  "raw/video.mp4"
```

### 2. 基准音频提取 (一级输出 `raw/audio.wav`)
```bash
ffmpeg -y -i "raw/video.mp4" \
  -vn -acodec pcm_s16le -ar 16000 -ac 1 \
  "raw/audio.wav"
```

### 3. 字幕生成与自适应排版 (二级输出 `cooked/subtitle_*`)
* 利用 `videocaptioner` 执行：
  - **双语版本** (`target-above` 布局，中文在上，英文在下)：生成 `.srt` 和带描边样式的 `.ass`。
  - **中文版本** (`target-only` 布局，纯中文字幕)：生成 `.srt` 和单行居中 `.ass`。

### 4. 熟肉视频硬压制标准 (二级输出 `cooked/video_*`)
```bash
# 双语熟肉视频
ffmpeg -y -i "raw/video.mp4" \
  -vf "ass='cooked/subtitle_bilingual.ass'" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  "cooked/video_bilingual.mp4"

# 纯中文熟肉视频
ffmpeg -y -i "raw/video.mp4" \
  -vf "ass='cooked/subtitle_zh.ass'" \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart \
  "cooked/video_zh.mp4"
```

---

## 五、 跨平台兼容性设计 (Windows & Linux)

1. **FFmpeg 滤镜路径安全转义**：
   - 封装 `escape_ffmpeg_path()`，在 Windows 环境将反斜杠替换为正斜杠，并将冒号转义为 `\:`（例如 `C\:/output/sub.ass`）。
2. **文本编码一致性**：
   - 所有 SRT、ASS、JSON 文件强制显式使用 `utf-8-sig` / `utf-8` 编码读写，杜绝 Windows 默认 GBK 编码导致的字符错乱。
