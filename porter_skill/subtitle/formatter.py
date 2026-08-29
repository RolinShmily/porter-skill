"""Subtitle parsing, styling, and formatting module for SRT and ASS formats."""

import re
from dataclasses import dataclass

from porter_skill.config import SubtitleStyleConfig


@dataclass
class SubtitleItem:
    """A single subtitle entry with timing and bilingual text."""

    index: int
    start_ms: int
    end_ms: int
    source_text: str  # Original language (e.g. English)
    target_text: str  # Translated language (e.g. Chinese)

    @property
    def start_srt(self) -> str:
        return ms_to_srt_time(self.start_ms)

    @property
    def end_srt(self) -> str:
        return ms_to_srt_time(self.end_ms)

    @property
    def start_ass(self) -> str:
        return ms_to_ass_time(self.start_ms)

    @property
    def end_ass(self) -> str:
        return ms_to_ass_time(self.end_ms)


def srt_time_to_ms(time_str: str) -> int:
    """Convert SRT time string (00:01:23,456) or ASS (0:01:23.45) to milliseconds."""
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].split(".")
        s = int(s_parts[0])
        ms_str = (s_parts[1] + "000")[:3] if len(s_parts) > 1 else "000"
        ms = int(ms_str)
        return h * 3600000 + m * 60000 + s * 1000 + ms
    return 0


def ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format: HH:MM:SS,mmm."""
    ms = max(ms, 0)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ms_to_ass_time(ms: int) -> str:
    """Convert milliseconds to ASS time format: H:MM:SS.cc (centiseconds)."""
    ms = max(ms, 0)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    cs = ms // 10  # Centiseconds (2 digits)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def is_cjk(text: str) -> bool:
    """Check if text contains any CJK (Chinese, Japanese, Korean) characters."""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def parse_srt(srt_content: str) -> list[SubtitleItem]:
    """Parse SRT content into SubtitleItem list."""
    if not srt_content or not srt_content.strip():
        return []

    items: list[SubtitleItem] = []
    # Normalize line endings
    blocks = re.split(r"\n\s*\n", srt_content.replace("\r\n", "\n").replace("\r", "\n").strip())

    time_regex = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[\.,]\d{3})"
    )

    index = 1
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if not lines:
            continue

        # Find line with timestamp
        time_match = None
        time_line_idx = -1
        for idx, line in enumerate(lines):
            match = time_regex.search(line)
            if match:
                time_match = match
                time_line_idx = idx
                break

        if not time_match or time_line_idx == -1:
            continue

        start_ms = srt_time_to_ms(time_match.group(1))
        end_ms = srt_time_to_ms(time_match.group(2))
        text_lines = lines[time_line_idx + 1 :]

        if not text_lines:
            continue

        if len(text_lines) == 1:
            raw_text = text_lines[0].strip()
            items.append(
                SubtitleItem(
                    index=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_text=raw_text,
                    target_text="",
                )
            )
        else:
            first_is_cjk = is_cjk(text_lines[0])
            second_is_cjk = is_cjk(text_lines[1])
            if first_is_cjk and not second_is_cjk:
                # Bilingual: line 1 Chinese, line 2 English
                items.append(
                    SubtitleItem(
                        index=index,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_text=" ".join(t.strip() for t in text_lines[1:]),
                        target_text=text_lines[0].strip(),
                    )
                )
            elif not first_is_cjk and second_is_cjk:
                # Bilingual: line 1 English, line 2 Chinese
                items.append(
                    SubtitleItem(
                        index=index,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_text=text_lines[0].strip(),
                        target_text=" ".join(t.strip() for t in text_lines[1:]),
                    )
                )
            else:
                # Monolingual multi-line text (e.g. wrapped English): join with space
                sep = "" if first_is_cjk else " "
                merged_line = sep.join(t.strip() for t in text_lines if t.strip())
                items.append(
                    SubtitleItem(
                        index=index,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_text=merged_line,
                        target_text="",
                    )
                )
        index += 1

    return normalize_subtitle_items(items)


def merge_short_fragments(
    items: list[SubtitleItem],
    max_gap_ms: int = 800,
    max_duration_ms: int = 7000,
    max_len: int = 90,
) -> list[SubtitleItem]:
    """
    Merge overly short consecutive subtitle fragments into natural, single-line sentences.
    Useful for YouTube auto captions and rolling transcripts.
    """
    if not items:
        return []

    merged: list[SubtitleItem] = []
    curr = SubtitleItem(
        index=items[0].index,
        start_ms=items[0].start_ms,
        end_ms=items[0].end_ms,
        source_text=items[0].source_text.strip(),
        target_text=items[0].target_text.strip(),
    )

    for next_item in items[1:]:
        gap = next_item.start_ms - curr.end_ms
        combined_duration = next_item.end_ms - curr.start_ms
        combined_source = (curr.source_text + " " + next_item.source_text.strip()).strip()

        ends_with_punct = bool(re.search(r"[.!?。！？]$", curr.source_text.strip()))

        should_merge = (
            gap <= max_gap_ms
            and combined_duration <= max_duration_ms
            and len(combined_source) <= max_len
            and (not ends_with_punct or combined_duration < 3000)
        )

        if should_merge:
            curr.end_ms = next_item.end_ms
            curr.source_text = combined_source
            if curr.target_text and next_item.target_text:
                sep = "" if is_cjk(curr.target_text) else " "
                curr.target_text = (curr.target_text + sep + next_item.target_text.strip()).strip()
        else:
            merged.append(curr)
            curr = SubtitleItem(
                index=next_item.index,
                start_ms=next_item.start_ms,
                end_ms=next_item.end_ms,
                source_text=next_item.source_text.strip(),
                target_text=next_item.target_text.strip(),
            )

    merged.append(curr)
    for idx, it in enumerate(merged, 1):
        it.index = idx
    return merged


def normalize_subtitle_items(items: list[SubtitleItem]) -> list[SubtitleItem]:
    """Fix overlapping timestamps and trim excess durations for clean rendering."""
    if not items:
        return []

    sorted_items = sorted(items, key=lambda x: (x.start_ms, x.end_ms))
    for i in range(len(sorted_items) - 1):
        curr = sorted_items[i]
        nxt = sorted_items[i + 1]

        # Fix overlapping timestamps (common in YouTube auto captions)
        if curr.end_ms > nxt.start_ms:
            curr.end_ms = max(curr.start_ms + 100, nxt.start_ms)

        if curr.end_ms <= curr.start_ms:
            curr.end_ms = curr.start_ms + 1000

    for idx, item in enumerate(sorted_items, start=1):
        item.index = idx

    return sorted_items


def align_bilingual_items(
    source_items: list[SubtitleItem], zh_items: list[SubtitleItem]
) -> list[SubtitleItem]:
    """Align pre-extracted Chinese subtitle items with source subtitle items."""
    if not source_items:
        return []
    if not zh_items:
        return source_items

    # 1-to-1 match if item counts are identical
    if len(source_items) == len(zh_items):
        for s_item, z_item in zip(source_items, zh_items):
            s_item.target_text = (z_item.source_text or z_item.target_text).strip()
        return source_items

    # Interval overlap alignment
    for s_item in source_items:
        overlapping_texts: list[str] = []
        for z_item in zh_items:
            overlap_start = max(s_item.start_ms, z_item.start_ms)
            overlap_end = min(s_item.end_ms, z_item.end_ms)
            if overlap_end > overlap_start:
                text = (z_item.source_text or z_item.target_text).strip()
                if text and text not in overlapping_texts:
                    overlapping_texts.append(text)
        s_item.target_text = "".join(overlapping_texts)

    return source_items


def generate_bilingual_srt(items: list[SubtitleItem]) -> str:
    """Generate bilingual SRT text (Target / Chinese on line 1, Source / English on line 2)."""
    blocks = []
    for item in items:
        # If target text is empty, just output source
        if item.target_text and item.source_text and item.target_text != item.source_text:
            text = f"{item.target_text}\n{item.source_text}"
        elif item.target_text:
            text = item.target_text
        else:
            text = item.source_text

        blocks.append(f"{item.index}\n{item.start_srt} --> {item.end_srt}\n{text}")

    return "\n\n".join(blocks) + "\n" if blocks else ""


def generate_zh_srt(items: list[SubtitleItem]) -> str:
    """Generate pure Chinese SRT text."""
    blocks = []
    for item in items:
        text = item.target_text if item.target_text else item.source_text
        blocks.append(f"{item.index}\n{item.start_srt} --> {item.end_srt}\n{text}")

    return "\n\n".join(blocks) + "\n" if blocks else ""


def generate_bilingual_ass(
    items: list[SubtitleItem],
    style: SubtitleStyleConfig | None = None,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """Generate styled bilingual ASS content with target-above layout."""
    if style is None:
        style = SubtitleStyleConfig()

    header = f"""[Script Info]
; Script generated by Video Porter Skill
Title: Bilingual Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.zh_font},{style.zh_font_size},{style.zh_primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},2,{style.margin_l},{style.margin_r},{style.margin_v},1
Style: SubtitleZh,{style.zh_font},{style.zh_font_size},{style.zh_primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},2,{style.margin_l},{style.margin_r},{style.margin_v},1
Style: SubtitleEn,{style.en_font},{style.en_font_size},{style.en_primary_color},&H000000FF,{style.outline_color},&H80000000,0,0,0,0,100,100,0,0,1,{style.outline_width * 0.7:.1f},{style.shadow * 0.7:.1f},2,{style.margin_l},{style.margin_r},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for item in items:
        start = item.start_ass
        end = item.end_ass

        if item.target_text and item.source_text and item.target_text != item.source_text:
            # Target on top (larger, zh_font), Source on bottom (smaller, secondary color, en_font)
            zh_clean = item.target_text.replace("\n", " ").strip()
            en_clean = item.source_text.replace("\n", " ").strip()
            text = f"{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{zh_clean}{{\\r}}\\N{{\\fn{style.en_font}\\fs{style.en_font_size}\\c{style.en_primary_color}&\\b0}}{en_clean}"
        elif item.target_text:
            clean_t = item.target_text.replace("\n", " ").strip()
            text = f"{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{clean_t}"
        else:
            clean_s = item.source_text.replace("\n", " ").strip()
            text = f"{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{clean_s}"

        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    return header + "\n".join(events) + "\n"


def generate_zh_ass(
    items: list[SubtitleItem],
    style: SubtitleStyleConfig | None = None,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """Generate styled pure Chinese single-line ASS content."""
    if style is None:
        style = SubtitleStyleConfig()

    header = f"""[Script Info]
; Script generated by Video Porter Skill
Title: Chinese Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.zh_font},{style.zh_font_size},{style.zh_primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},2,{style.margin_l},{style.margin_r},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for item in items:
        start = item.start_ass
        end = item.end_ass
        text = (
            (item.target_text if item.target_text else item.source_text).replace("\n", " ").strip()
        )
        events.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{text}"
        )

    return header + "\n".join(events) + "\n"
