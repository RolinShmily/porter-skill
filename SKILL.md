---
name: porter-skill
description: Automated video localization, multi-engine ASR speech-to-text, subtitle translation, and dual-version FFmpeg hardsub release pipeline for YouTube, X (Twitter), and other streaming media. Use whenever the user requests downloading a video, generating bilingual or Chinese subtitles, translating YouTube/X content, transcribing audio, or creating ready-to-publish release videos.
---

# Porter Skill (流媒体搬运工)

Porter Skill (`porter-skill`) 是专为 AI Agent 设计的跨平台（Windows / Linux）全自动流媒体搬运与熟肉制作流水线。

本仓库本身即为一个**完整自包含的 Agent Skill 目录**，可通过 `skills` 客户端一键安装或直接克隆至 Agent Skills 目录中使用：

```bash
# 推荐：使用 npx skills add 一键安装
npx skills add RolinShmily/porter-skill -g

# 或手动 Git Clone 到 Agent 技能目录
git clone https://github.com/RolinShmily/porter-skill.git ~/.pi/agent/skills/porter-skill
```

系统环境底线**仅需 Python (>= 3.10) 与 FFmpeg**。无需预装任何外部收费工具或本地 ASR 二进制。

---

## 核心设计与特性

1. **跨平台支持与极简系统依赖**：
   - 深度支持 **YouTube** (`youtube.com`, `youtu.be`) 与 **X / Twitter** (`x.com`, `twitter.com`, `t.co`)；
   - 依赖严格控制在标准 Python 生态与 FFmpeg 范围内；
   - 具备秒级轻量预检探针（Pre-flight Probe），1 秒内完成短链展开、追踪参数清洗与有效性校验；
   - 具备画幅自适应排版（Aspect-Ratio Aware Styling）：横屏 16:9 与竖屏 9:16 自适应断句与底边距，开箱即用 100% 成功出片。
2. **通用 ASR 多引擎逐级回退（纯 Python 零 Key 兜底）**：
   - 当视频无原生字幕需 ASR 时，自动按优先级链式尝试：
     $$\text{Whisper API (若配Key)} \longrightarrow \text{Pure Python Bcut 必剪 (免Key免费)} \longrightarrow \text{Google Web STT + VAD (免Key免费)} \longrightarrow \text{VideoCaptioner CLI (可选增强)}$$
   - 在仅有 Python + FFmpeg 的极端环境下亦能 100% 独立完成语音转录。
3. **分层翻译与高可用容灾（LLM ➔ Bing ➔ Google ➔ MyMemory）**：
   - **大模型增强（配置 LLM 时）**：优先使用 DeepSeek / GPT 上下文语义纠错与优化；
   - **免配置多级容灾（未配 LLM 时）**：
     $$\text{Pure Python Bing (Copilot 免费)} \longrightarrow \text{Google HTTP (多端轮换/反爬伪装)} \longrightarrow \text{MyMemory 免费 API 兜底} \longrightarrow \text{VideoCaptioner CLI}$$
   - **汉化质量自检（CJK 校验）**：流水线内置中文字符自动检测与自愈机制，杜绝未翻译假熟肉。
4. **结构化台词本与中文意群断句（Transcript & Chinese Phrasing）**：
   - 自动将破碎的 ASR / 平台字幕碎片按语法、静音间隙（$>0.6\text{s}$）与标点重构成完整的英文句子台词本（`raw/transcript.json` 与 `raw/transcript.txt`）；
   - 基于完整语句进行语义翻译（避免碎词直译导致语序颠倒）；
   - 根据中文句读与自然连词进行意群截断（单行 $\le 20$ 字），时间戳按意群字数比例平滑分配，彻底杜绝生硬截断与阅读疲劳。
5. **解耦字幕下载与反爬容错**：
   - 字幕与音视频流下载解耦，若单一语言轨遭遇 429 不会丢弃已成功下载的源文字幕，避免误回退到慢速 ASR。
6. **两级规范输出目录**：
   - 一级目录 `raw/`：标准化母版视频 (`video.mp4`)、基准音轨 (`audio.wav`)、结构化台词本 (`transcript.json`, `transcript.txt`)、封面 (`cover.jpg`)、元数据 (`metadata.json`)、字幕源 (`subtitle.srt`)；
   - 二级目录 `cooked/`：双语/纯中文字幕 (`.srt`, `.ass`)、双语硬字幕熟肉 (`video_bilingual.mp4`)、纯中文硬字幕熟肉 (`video_zh.mp4`)。
7. **硬件分级与自适应极速压制**：
   - 自动检测主机硬件算力（Tier A: NVENC/QSV 硬件加速、Tier B: 8+核多线程 CPU、Tier C: N100/树莓派轻量级算力）；
   - 依据硬件算力自适应调优压制预设（Preset: `veryfast` / `ultrafast`）与 CRF 编码质量，低功耗工控机压制耗时降低 60%+；
   - 媒体下载格式优选 1080p 并采用无损流复制（0.5 秒极速 Remuxing），杜绝二次重编码失真与画质降级；
   - 利用 FFmpeg `libass` 滤镜烧录双语及纯中文硬字幕，音频采用 `-c:a copy` 直通复制保持原视频音质。

---

## 目录结构说明

```
porter-skill/
├── SKILL.md                  # 核心技能规约 (name: porter-skill)
├── config.example.json       # 配置模板 (LLM / ASR / 字幕样式)
├── pyproject.toml            # Python 依赖与打包配置
├── README.md                 # 项目使用文档
├── references/               # 深度技术手册
│   ├── ARCHITECTURE.md       # 四阶段流水线与底层架构设计规范
│   └── CONFIG_GUIDE.md       # ASR 多引擎回退与配置手册
├── scripts/                  # 便捷执行与环境安装脚本
│   ├── run_porter.py         # 免安装直接运行入口
│   └── setup_env.sh          # 环境一键初始化脚本
├── porter_skill/             # Python 核心实现源码
└── tests/                    # 58 个自动化单元与集成测试
```

---

## 配置文件规范 (`config.json`)

可在 Skill 仓库根目录下复制 `config.example.json` 为 `config.json` 并配置：

```json
{
  "llm": {
    "api_key": "sk-your-openai-or-deepseek-api-key",
    "api_base": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  },
  "asr": {
    "engine": "bijian",
    "language": "auto",
    "whisper_api_key": "sk-your-openai-key",
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

详细配置说明请参阅 [references/CONFIG_GUIDE.md](references/CONFIG_GUIDE.md)。

---

## 常用命令与 Agent 指南

### 1. 链接快速预检与探活 (Pre-flight Probe)
```bash
# 1 秒内嗅探链接平台、时长、画幅比例与有效性（不产生实际下载）
python scripts/inspect_link.py "<URL>"
# 或通过主 CLI 参数
python -m porter_skill "<URL>" -i
```

### 2. 查看与管理配置
```bash
# 查看当前已生效配置（自动脱敏）
python -m porter_skill --config-show
# 或直接运行脚本
python scripts/run_porter.py --config-show

# 一键设置配置项
python -m porter_skill --config-set asr.engine="jianying"
python -m porter_skill --config-set llm.api_key="sk-..."
```

### 2. 环境自检
```bash
python -m porter_skill --doctor
```

### 3. 标准搬运执行（下载 + 提取 + 翻译 + 压制）
```bash
python -m porter_skill "<YOUTUBE_URL>" -o "./output"
```

### 4. 进阶参数
- `--skip-burn`：仅提取素材和生成字幕，不执行视频硬字幕压制
- `--only-bilingual`：仅压制双语版本熟肉
- `--only-zh`：仅压制纯中文版本熟肉
- `--cookies <file>` / `--cookies-from-browser <browser>`：携带 Cookie 下载受限视频

---

## 智能体最佳实践与验证工作流 (Agent Best Practices)

当 AI 智能体（Agent）调用本 Skill 执行视频搬运任务时，应遵循以下闭环工作流：

1. **调用入口与虚拟环境自愈**：
   - 使用绝对路径直接调用 runner 脚本：
     `python <SKILL_DIR>/scripts/run_porter.py "<URL>" -o "./output"`
   - runner 脚本已内置虚拟环境自动探测与 `os.execv` 自举，无需手动激活环境或探测 Python 解释器。
2. **合理设置工具调用超时（Timeout Provisioning）**：
   - 包含高清下载与双版本压制的完整流水线（尤其是 $>5$ 分钟的 1080P 60fps 视频），请在 bash 工具调用时提供充足的超时时间（如 `timeout: 1200`）；
   - 若遇到单次压制超时，重新执行相同命令即可——流水线内置断点续传（Phase 1~4 Checkpointing），会自动复用已完成的母版物料与字幕，秒级恢复断点。
3. **反爬与限流自愈**：
   - 若遇到 YouTube 登录验证或 429 报错，主动携带浏览器 Cookie 参数重试：
     `python <SKILL_DIR>/scripts/run_porter.py "<URL>" -o "./output" --cookies-from-browser chrome`
4. **两阶段闭环质检验收 (Two-Stage Verification)**：
   - **字幕质检**：使用 `read` 工具抽检 `cooked/subtitle_bilingual.srt` 前 10 行，确认中文字幕行包含正常中文字符（CJK）；
   - **视频完整性核验**：使用 `ffprobe -v error -show_entries format=duration,probe_score -of default=noprint_wrappers=1:nokey=1 <video_path>` 确认成片有效且 `moov atom` 索引完好，杜绝任何因中断导致的损坏文件。
