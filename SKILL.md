---
name: porter-skill
description: Automated video localization, multi-engine ASR speech-to-text, subtitle translation, and dual-version FFmpeg hardsub release pipeline for YouTube and other streaming media. Use whenever the user requests downloading a video, generating bilingual or Chinese subtitles, translating YouTube content, transcribing audio, or creating ready-to-publish release videos.
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

1. **自包含与极简系统依赖**：
   - 依赖严格控制在标准 Python 生态与 FFmpeg 范围内；
   - 优先提取 YouTube 官方字幕 / 自动字幕；
   - 具备平台原生字幕极速直连（Fast Path），自动对齐中文译轨，0 延迟、0 消耗出片；
   - 开箱即用，零配置即可 100% 成功出产中英双语与纯中文熟肉视频。
2. **通用 ASR 多引擎逐级回退（链式探测）**：
   - 当视频无原生字幕需 ASR 时，自动按顺序逐个尝试：
     $$\text{bijian (必剪免费)} \longrightarrow \text{jianying (剪映免费)} \longrightarrow \text{whisper-api} \longrightarrow \text{whisper-cpp}$$
   - 任何一个引擎因网络或格式失败，立即无缝尝试下一个，确保转录必定成功。
3. **分层翻译与优化策略（Bing 优先于 Google）**：
   - **大模型增强（配置 LLM 时）**：优先使用 DeepSeek / GPT 上下文语义纠错与优化；
   - **免费双引擎兜底（未配 LLM 时）**：
     $$\text{Bing 翻译 (优先)} \longrightarrow \text{Google 翻译 (回退)}$$
4. **两级规范输出目录**：
   - 一级目录 `raw/`：标准化母版视频 (`video.mp4`)、基准音轨 (`audio.wav`)、封面 (`cover.jpg`)、元数据 (`metadata.json`)、字幕源 (`subtitle.srt`)；
   - 二级目录 `cooked/`：双语/纯中文字幕 (`.srt`, `.ass`)、双语硬字幕熟肉 (`video_bilingual.mp4`)、纯中文硬字幕熟肉 (`video_zh.mp4`)。
5. **无损极速硬压制**：
   - 利用 FFmpeg `libass` 滤镜烧录双语及纯中文硬字幕；
   - 音频采用 `-c:a copy` 直通复制，极速出片且 100% 保持原视频音质。

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
└── tests/                    # 35 个自动化单元与集成测试
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

### 1. 查看与管理配置
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
