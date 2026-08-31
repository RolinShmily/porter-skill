"""Pipeline coordinator orchestrating end-to-end video localization."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from porter_skill.config import PorterConfig, get_default_config
from porter_skill.env_check import run_doctor
from porter_skill.extractors.base import RawMaterialResult, get_extractor
from porter_skill.extractors.inspector import inspect_url
from porter_skill.subtitle.controller import SubtitleResult, generate_subtitles
from porter_skill.synthesizer.burn import DualReleaseResult, burn_dual_release


@dataclass
class PipelineResult:
    """Complete execution result of the localization pipeline."""

    task_dir: Path
    raw_materials: RawMaterialResult
    subtitles: SubtitleResult
    synthesis: DualReleaseResult | None = None
    duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None


def run_pipeline(
    url: str,
    output_dir: Path | str = "./porter_output",
    config: PorterConfig | None = None,
    skip_burn: bool = False,
    only_bilingual: bool = False,
    only_zh: bool = False,
    on_progress: Callable[[str, int], None] | None = None,
) -> PipelineResult:
    """
    Execute end-to-end 4-phase video localization pipeline:
    - Phase 0: Environment diagnostic check
    - Phase 1: Platform media extraction and standardization into raw/
    - Phase 2 & 3: Smart subtitle fallback, LLM translation and styling into cooked/
    - Phase 4: FFmpeg high-speed hardsub synthesis into cooked/
    """
    start_time = time.time()
    if config is None:
        config = get_default_config()

    output_base_dir = Path(output_dir).resolve()
    output_base_dir.mkdir(parents=True, exist_ok=True)

    def log(step_name: str, step_num: int) -> None:
        if on_progress:
            on_progress(step_name, step_num)
        print(f"[Phase {step_num}/4] {step_name}...")

    # Phase 0: Environment validation & Pre-flight Link Inspection
    report = run_doctor()
    if not report.passed:
        failing = [r.name for r in report.results if not r.status and not r.is_warning]
        raise RuntimeError(
            f"Environment check failed for: {', '.join(failing)}. Run --doctor for fixes."
        )

    # Pre-flight link probe
    inspection = inspect_url(
        url,
        cookies_file=config.cookies_file,
        cookies_browser=config.cookies_browser,
    )
    if not inspection.is_valid:
        raise RuntimeError(
            f"Link pre-flight check failed for URL: {url}\nReason: {inspection.error_message}"
        )

    if inspection.duration_seconds and inspection.duration_seconds > 300:
        mins = inspection.duration_seconds / 60.0
        print(f"  ℹ Long video detected ({mins:.1f} min). Checkpointing & adaptive tuning enabled.")

    if inspection.is_vertical:
        print(
            "  📱 Vertical video format detected (9:16). Applying mobile-optimized subtitle scaling."
        )

    target_url = inspection.canonical_url

    # Phase 1: Material extraction
    log(f"Extracting raw materials from URL: {target_url}", 1)
    extractor = get_extractor(target_url)
    raw_result = extractor.extract_raw_materials(
        url=target_url,
        output_base_dir=output_base_dir,
        ffmpeg_path=config.ffmpeg.ffmpeg_path,
        cookies_file=config.cookies_file,
        cookies_browser=config.cookies_browser,
    )
    task_dir = raw_result.task_dir
    cooked_dir = task_dir / "cooked"
    cooked_dir.mkdir(parents=True, exist_ok=True)
    print(f"  -> Raw materials ready at: {raw_result.raw_dir}")

    # Phase 2 & 3: Smart subtitle extraction & LLM translation
    log("Processing subtitles (Smart Fallback & LLM Translation)", 2)
    subtitle_result = generate_subtitles(
        raw_material=raw_result,
        cooked_dir=cooked_dir,
        config=config,
    )
    print(f"  -> Subtitles generated in: {cooked_dir}")
    print(f"     • Bilingual: {subtitle_result.subtitle_bilingual_ass.name}")
    print(f"     • Chinese:   {subtitle_result.subtitle_zh_ass.name}")

    # Phase 4: Hardsub synthesis
    synthesis_result: DualReleaseResult | None = None
    if not skip_burn:
        log("Synthesizing release videos with FFmpeg libass hardsubs", 4)
        synthesis_result = burn_dual_release(
            raw_video=raw_result.video_path,
            bilingual_ass=subtitle_result.subtitle_bilingual_ass,
            zh_ass=subtitle_result.subtitle_zh_ass,
            cooked_dir=cooked_dir,
            config=config,
            only_bilingual=only_bilingual,
            only_zh=only_zh,
        )
        if synthesis_result.video_bilingual:
            print(f"  -> Cooked Video (Bilingual): {synthesis_result.video_bilingual}")
        if synthesis_result.video_zh:
            print(f"  -> Cooked Video (Chinese):   {synthesis_result.video_zh}")
    else:
        print("[Phase 4/4] Skipped video synthesis (--skip-burn requested).")

    elapsed = time.time() - start_time
    print(f"\n[OK] Pipeline completed successfully in {elapsed:.2f}s!")
    print(f"     Output directory: {task_dir}")

    return PipelineResult(
        task_dir=task_dir,
        raw_materials=raw_result,
        subtitles=subtitle_result,
        synthesis=synthesis_result,
        duration_seconds=elapsed,
        success=True,
    )
