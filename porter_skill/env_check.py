"""Environment diagnosis and cross-platform dual-track guidance module."""

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from porter_skill.config import get_default_config


@dataclass
class CheckResult:
    """Individual diagnostic check result."""

    name: str
    status: bool  # True = Pass, False = Fail / Warning
    is_warning: bool = False  # If True, status=False is a warning rather than blocker
    message: str = ""
    details: str = ""
    guide: str | None = None


@dataclass
class HardwareProfile:
    """Hardware capability and encoding profile."""

    tier: str
    cpu_cores: int
    hardware_accel: str | None
    recommended_encoder: str
    recommended_preset: str
    recommended_crf: int
    recommended_x264_preset: str
    recommended_x264_crf: int
    details: str


def detect_hardware_profile(ffmpeg_path: str = "ffmpeg") -> HardwareProfile:
    """
    Detect system hardware capability and optimal FFmpeg encoding profile.
    Tiers:
    - Tier A: Hardware acceleration available (Intel QSV / NVIDIA NVENC / VAAPI / Apple VideoToolbox)
    - Tier B: High-Core CPU (>= 8 cores, libx264 veryfast, CRF 18)
    - Tier C: Lightweight CPU (<= 4 cores e.g. N100 / Raspberry Pi / low-end VPS, libx264 ultrafast, CRF 22)
    """
    cpu_cores = os.cpu_count() or 4
    x264_preset = "veryfast" if cpu_cores >= 4 else "ultrafast"
    x264_crf = 18 if cpu_cores >= 8 else (20 if cpu_cores >= 4 else 22)

    encoders_output = ""
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        encoders_output = (proc.stdout or "") + (proc.stderr or "")
    except Exception:  # noqa: BLE001, S110
        pass

    sys_name = platform.system()
    has_dri = Path("/dev/dri").exists()

    # 1. NVIDIA NVENC
    if "h264_nvenc" in encoders_output:
        return HardwareProfile(
            tier="Tier A (NVIDIA NVENC Hardware Accelerated)",
            cpu_cores=cpu_cores,
            hardware_accel="nvenc",
            recommended_encoder="h264_nvenc",
            recommended_preset="p4",
            recommended_crf=19,
            recommended_x264_preset=x264_preset,
            recommended_x264_crf=x264_crf,
            details=f"NVIDIA NVENC detected ({cpu_cores} CPU cores)",
        )

    # 2. Intel QuickSync (QSV)
    if "h264_qsv" in encoders_output and (has_dri or sys_name == "Windows"):
        return HardwareProfile(
            tier="Tier A (Intel QuickSync QSV Hardware Accelerated)",
            cpu_cores=cpu_cores,
            hardware_accel="qsv",
            recommended_encoder="h264_qsv",
            recommended_preset="veryfast",
            recommended_crf=20,
            recommended_x264_preset=x264_preset,
            recommended_x264_crf=x264_crf,
            details=f"Intel QSV detected ({cpu_cores} CPU cores, GPU render device available)",
        )

    # 3. Apple VideoToolbox (macOS)
    if "h264_videotoolbox" in encoders_output and sys_name == "Darwin":
        return HardwareProfile(
            tier="Tier A (Apple VideoToolbox Hardware Accelerated)",
            cpu_cores=cpu_cores,
            hardware_accel="videotoolbox",
            recommended_encoder="h264_videotoolbox",
            recommended_preset="medium",
            recommended_crf=20,
            recommended_x264_preset=x264_preset,
            recommended_x264_crf=x264_crf,
            details=f"Apple Silicon / VideoToolbox detected ({cpu_cores} CPU cores)",
        )

    # 4. Linux VAAPI
    if "h264_vaapi" in encoders_output and has_dri:
        return HardwareProfile(
            tier="Tier A (Linux VAAPI Hardware Accelerated)",
            cpu_cores=cpu_cores,
            hardware_accel="vaapi",
            recommended_encoder="h264_vaapi",
            recommended_preset="veryfast",
            recommended_crf=20,
            recommended_x264_preset=x264_preset,
            recommended_x264_crf=x264_crf,
            details=f"Linux VAAPI /dev/dri detected ({cpu_cores} CPU cores)",
        )

    # 5. Software CPU Fallback: High-Core (Tier B) vs Lightweight (Tier C)
    if cpu_cores >= 8:
        return HardwareProfile(
            tier=f"Tier B (High-Core CPU: {cpu_cores} Cores)",
            cpu_cores=cpu_cores,
            hardware_accel=None,
            recommended_encoder="libx264",
            recommended_preset="veryfast",
            recommended_crf=18,
            recommended_x264_preset=x264_preset,
            recommended_x264_crf=x264_crf,
            details=f"Multi-threaded CPU software encoding ({cpu_cores} cores, preset=veryfast, crf=18)",
        )

    return HardwareProfile(
        tier=f"Tier C (Lightweight CPU: {cpu_cores} Cores - Low Power / Edge)",
        cpu_cores=cpu_cores,
        hardware_accel=None,
        recommended_encoder="libx264",
        recommended_preset="ultrafast",
        recommended_crf=22,
        recommended_x264_preset=x264_preset,
        recommended_x264_crf=x264_crf,
        details=f"Lightweight CPU software encoding ({cpu_cores} cores, preset=ultrafast, crf=22 for 3x speedup)",
    )


@dataclass
class DoctorReport:
    """Aggregated doctor diagnostic report."""

    results: list[CheckResult] = field(default_factory=list)
    system: str = platform.system()  # 'Windows', 'Linux', 'Darwin', etc.

    @property
    def passed(self) -> bool:
        """Return True if all non-warning checks passed."""
        return all(r.status for r in self.results if not r.is_warning)


def get_windows_ffmpeg_guide() -> str:
    """Return Windows dual-track installation and configuration guide for FFmpeg."""
    return """[Windows FFmpeg 安装与配置指引（双轨方案）]

【方案 A：极速一键安装（推荐，自动配置环境变量）】
在 Windows 终端（PowerShell 或 CMD）中执行：
  winget install Gyan.FFmpeg
安装完成后请重启终端。

【方案 B：官网手动下载 + 环境变量配置】
1. 访问官方推荐下载源：
   - Gyan.dev: https://www.gyan.dev/ffmpeg/builds/ (下载 ffmpeg-release-essentials.zip)
   - BtbN Releases: https://github.com/BtbN/FFmpeg-Builds/releases
2. 解压文件至无中文的固定路径（例如 C:\\ffmpeg）；
3. 将 FFmpeg 添加到系统环境变量 Path：
   ① 按键盘 Win + S 搜索并打开 “编辑系统环境变量”；
   ② 在窗口下方点击 “环境变量”；
   ③ 在 “系统变量” 列表中选中 Path，点击 “编辑”；
   ④ 点击右侧 “新建”，输入解压后的 bin 目录路径（如 C:\\ffmpeg\\bin）；
   ⑤ 依次点击 “确定” 保存所有设置，重启终端后运行 ffmpeg -version 验证。"""


def get_windows_python_guide() -> str:
    """Return Windows dual-track installation guide for Python >= 3.10."""
    return """[Windows Python 安装与配置指引（双轨方案）]

【方案 A：极速一键安装（推荐）】
在 Windows 终端（PowerShell 或 CMD）中执行：
  winget install Python.Python.3.12

【方案 B：官网手动下载 + 环境变量配置】
1. 访问 Python 官网：https://www.python.org/downloads/
2. 运行安装程序时，【务必勾选】底部的 "Add python.exe to PATH"；
3. 若遗漏勾选，需手动将 Python 安装路径（如 C:\\Users\\<用户名>\\AppData\\Local\\Programs\\Python\\Python312\\ 及 Scripts\\）添加至系统 Path 环境变量。"""


def get_linux_ffmpeg_guide() -> str:
    """Return Linux package manager installation guide for FFmpeg."""
    return """[Linux FFmpeg 安装指引]
根据您的 Linux 发行版执行对应命令：

- Ubuntu / Debian:
    sudo apt update && sudo apt install -y ffmpeg

- Arch Linux / Manjaro:
    sudo pacman -S ffmpeg

- Fedora / RHEL / CentOS:
    sudo dnf install ffmpeg (需启用 RPM Fusion 仓库)"""


def get_linux_python_guide() -> str:
    """Return Linux package manager installation guide for Python."""
    return """[Linux Python 安装指引]
根据您的 Linux 发行版执行对应命令：

- Ubuntu / Debian:
    sudo apt update && sudo apt install -y python3 python3-pip

- Arch Linux / Manjaro:
    sudo pacman -S python python-pip

- Fedora / RHEL:
    sudo dnf install python3 python3-pip"""


def check_python() -> CheckResult:
    """Verify Python runtime version >= 3.10."""
    v = sys.version_info
    major, minor = v[0], v[1]
    micro = v[2] if len(v) > 2 else 0
    version_str = f"{major}.{minor}.{micro}"
    passed = (major > 3) or (major == 3 and minor >= 10)

    is_win = platform.system() == "Windows"
    guide = None
    if not passed:
        guide = get_windows_python_guide() if is_win else get_linux_python_guide()

    return CheckResult(
        name="Python Runtime",
        status=passed,
        message=f"Python {version_str}" if passed else f"Python {version_str} (< 3.10)",
        details=f"Executable: {sys.executable}",
        guide=guide,
    )


def check_ffmpeg() -> CheckResult:
    """Verify ffmpeg and ffprobe binaries and libass / subtitles filter support."""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    is_win = platform.system() == "Windows"
    guide = get_windows_ffmpeg_guide() if is_win else get_linux_ffmpeg_guide()

    if not ffmpeg_path or not ffprobe_path:
        missing = []
        if not ffmpeg_path:
            missing.append("ffmpeg")
        if not ffprobe_path:
            missing.append("ffprobe")
        return CheckResult(
            name="FFmpeg & FFprobe",
            status=False,
            message=f"Missing binary: {', '.join(missing)}",
            details="FFmpeg binaries must be installed and accessible via system PATH.",
            guide=guide,
        )

    # Check libass / subtitles filter support
    has_libass = False
    try:
        proc = subprocess.run(
            [ffmpeg_path, "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if "subtitles" in output or "ass" in output:
            has_libass = True
    except Exception:  # noqa: BLE001
        # Fallback to checking ffmpeg -version for --enable-libass
        try:
            proc2 = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            v_output = (proc2.stdout or "") + (proc2.stderr or "")
            if "enable-libass" in v_output or "libass" in v_output:
                has_libass = True
        except Exception:  # noqa: BLE001, S110
            pass

    if not has_libass:
        return CheckResult(
            name="FFmpeg & libass",
            status=False,
            message="FFmpeg found but lacks libass/subtitles filter support",
            details=f"ffmpeg: {ffmpeg_path}, ffprobe: {ffprobe_path}",
            guide=guide,
        )

    return CheckResult(
        name="FFmpeg & libass",
        status=True,
        message="FFmpeg & FFprobe ready (libass supported)",
        details=f"ffmpeg: {ffmpeg_path}, ffprobe: {ffprobe_path}",
        guide=None,
    )


def check_packages() -> CheckResult:
    """Check yt-dlp and videocaptioner availability."""
    # Check yt-dlp
    has_ytdlp = False
    try:
        import yt_dlp

        has_ytdlp = True
        ytdlp_info = f"python module (v{getattr(yt_dlp, '__version__', 'unknown')})"
    except ImportError:
        ytdlp_bin = shutil.which("yt-dlp")
        if ytdlp_bin:
            has_ytdlp = True
            ytdlp_info = f"binary at {ytdlp_bin}"
        else:
            ytdlp_info = "not found"

    # Check videocaptioner (either as binary or python module)
    has_vc = False
    vc_bin = shutil.which("videocaptioner")
    if vc_bin:
        has_vc = True
        vc_info = f"CLI binary at {vc_bin}"
    else:
        import importlib.util

        if importlib.util.find_spec("videocaptioner") is not None:
            has_vc = True
            vc_info = "python module"
        else:
            # Check user local bin
            user_vc = Path.home() / ".local" / "bin" / "videocaptioner"
            if user_vc.is_file() and os.access(user_vc, os.X_OK):
                has_vc = True
                vc_info = f"binary at {user_vc}"
            else:
                vc_info = "not found"

    if not has_ytdlp:
        guide = (
            "Please install yt-dlp:\n"
            "  pip install yt-dlp\n"
            "  or download binary: https://github.com/yt-dlp/yt-dlp/releases"
        )
        return CheckResult(
            name="Core Packages (yt-dlp & videocaptioner)",
            status=False,
            message="yt-dlp is missing",
            details=f"yt-dlp: {ytdlp_info}, videocaptioner: {vc_info}",
            guide=guide,
        )

    if not has_vc:
        return CheckResult(
            name="Core Packages (yt-dlp & videocaptioner)",
            status=True,
            message="yt-dlp ready (VideoCaptioner: optional)",
            details=f"yt-dlp: {ytdlp_info}, videocaptioner: {vc_info} (optional)",
        )

    return CheckResult(
        name="Core Packages (yt-dlp & videocaptioner)",
        status=True,
        message="yt-dlp and videocaptioner are available",
        details=f"yt-dlp: {ytdlp_info}, videocaptioner: {vc_info}",
    )


def check_llm() -> CheckResult:
    """Check LLM API Key and Base URL configuration."""
    config = get_default_config()
    api_key = config.llm.api_key
    api_base = config.llm.api_base
    model = config.llm.model

    if not api_key:
        guide = (
            "LLM API Key is optional (enables enhanced semantic translation & optimization).\n"
            "By default, built-in pure Python translation is used.\n"
            "To enable LLM enhancement:\n"
            "  export OPENAI_API_KEY='sk-...'\n"
            "  export OPENAI_BASE_URL='https://api.deepseek.com/v1'  # Optional\n"
            "  export OPENAI_MODEL='deepseek-chat'                  # Optional"
        )
        return CheckResult(
            name="LLM Configuration (Optional)",
            status=True,
            message="Not configured (using built-in pure Python translation)",
            details="Built-in translation ready (no API key required)",
            guide=guide,
        )

    masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
    return CheckResult(
        name="LLM Configuration",
        status=True,
        message=f"LLM configured (model: {model})",
        details=f"api_base: {api_base or 'https://api.openai.com/v1'}, key: {masked_key}",
    )


def check_hardware() -> CheckResult:
    """Check hardware encoding profile and device capability tier."""
    profile = detect_hardware_profile()
    return CheckResult(
        name="Hardware & Acceleration",
        status=True,
        message=profile.tier,
        details=(
            f"Encoder: {profile.recommended_encoder} | "
            f"Preset: {profile.recommended_preset} | "
            f"CRF: {profile.recommended_crf}"
        ),
    )


def run_doctor() -> DoctorReport:
    """Execute all diagnostic checks and return comprehensive report."""
    results = [
        check_python(),
        check_ffmpeg(),
        check_hardware(),
        check_packages(),
        check_llm(),
    ]
    return DoctorReport(results=results)


def print_doctor_report(report: DoctorReport) -> None:
    """Pretty print the doctor report with colored or clean output."""
    print("=" * 65)
    print(" " * 20 + "PORTER-SKILL DOCTOR")
    print(f" OS: {platform.system()} ({platform.release()}) | Arch: {platform.machine()}")
    print("=" * 65)

    has_guides: list[CheckResult] = []

    for r in report.results:
        if r.status:
            status_icon = " [OK]  "
        elif r.is_warning:
            status_icon = " [WARN]"
        else:
            status_icon = " [FAIL]"

        print(f"{status_icon} {r.name}: {r.message}")
        if r.details:
            print(f"        └─ {r.details}")

        if not r.status and r.guide:
            has_guides.append(r)

    print("-" * 65)
    if report.passed:
        print(" => Environment check PASSED! Ready to run video-porter.")
    else:
        print(" => Environment check FAILED! Please resolve the issues above.")

    if has_guides:
        print("\n" + "=" * 65)
        print("                  REMEDIATION GUIDES")
        print("=" * 65)
        for r in has_guides:
            print(f"\n--- {r.name} ---")
            print(r.guide)
        print("=" * 65)
