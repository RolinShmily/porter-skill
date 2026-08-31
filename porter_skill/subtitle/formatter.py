"""Subtitle parsing, styling, transcript reconstruction, and formatting module for SRT and ASS formats."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from porter_skill.config import SubtitleStyleConfig

CHINESE_CONJUNCTIONS = [
    "但是",
    "所以",
    "因为",
    "而且",
    "如果",
    "虽然",
    "并且",
    "以及",
    "然后",
    "同时",
    "为了",
    "另外",
    "不过",
    "由于",
    "从而",
    "通过",
    "比如",
    "例如",
    "即便",
    "只要",
    "除非",
]


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


@dataclass
class TranscriptSentence:
    """A reconstructed full sentence in the raw transcript script book."""

    sentence_id: int
    start_ms: int
    end_ms: int
    en_text: str
    zh_text: str = ""
    fragment_indices: list[int] | None = None

    @property
    def start_srt(self) -> str:
        return ms_to_srt_time(self.start_ms)

    @property
    def end_srt(self) -> str:
        return ms_to_srt_time(self.end_ms)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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


def reconstruct_sentences_from_fragments(
    items: list[SubtitleItem],
    max_silence_gap_ms: int = 600,
    max_duration_ms: int = 7000,
    max_words: int = 20,
) -> list[TranscriptSentence]:
    """
    Reconstruct raw, broken ASR/caption fragments into grammatically coherent, whole sentences.
    Uses 3D criteria:
    1. Punctuation terminal (.?!—--)
    2. Silence gap > 600ms between fragments
    3. Length/Duration bounds (duration >= 6.0s or words >= 18 with next capitalized)
    """
    if not items:
        return []

    sentences: list[TranscriptSentence] = []
    curr_id = 1
    curr_start = items[0].start_ms
    curr_end = items[0].end_ms
    curr_texts = [items[0].source_text.strip()]
    curr_zh_texts = [items[0].target_text.strip()] if items[0].target_text.strip() else []
    curr_frags = [items[0].index]

    for next_item in items[1:]:
        next_text = next_item.source_text.strip()
        if not next_text:
            continue

        gap = next_item.start_ms - curr_end
        combined_text = " ".join(curr_texts)
        words_count = len(combined_text.split())
        curr_duration = curr_end - curr_start

        # Check terminal punctuation at end of current combined text
        ends_terminal_punct = bool(re.search(r"[.!?。！？]$", combined_text))
        ends_dash = combined_text.endswith(("—", "--"))

        # Check if next text starts with a capital letter
        next_is_capital = next_text[0].isupper() if next_text else False

        should_split = (
            ends_terminal_punct
            or ends_dash
            or gap > max_silence_gap_ms
            or curr_duration >= max_duration_ms
            or (words_count >= max_words and next_is_capital)
        )

        if should_split:
            sentences.append(
                TranscriptSentence(
                    sentence_id=curr_id,
                    start_ms=curr_start,
                    end_ms=curr_end,
                    en_text=" ".join(curr_texts),
                    zh_text="".join(curr_zh_texts),
                    fragment_indices=list(curr_frags),
                )
            )
            curr_id += 1
            curr_start = next_item.start_ms
            curr_end = next_item.end_ms
            curr_texts = [next_text]
            curr_zh_texts = [next_item.target_text.strip()] if next_item.target_text.strip() else []
            curr_frags = [next_item.index]
        else:
            curr_end = next_item.end_ms
            curr_texts.append(next_text)
            if next_item.target_text.strip():
                curr_zh_texts.append(next_item.target_text.strip())
            curr_frags.append(next_item.index)

    if curr_texts:
        sentences.append(
            TranscriptSentence(
                sentence_id=curr_id,
                start_ms=curr_start,
                end_ms=curr_end,
                en_text=" ".join(curr_texts),
                zh_text="".join(curr_zh_texts),
                fragment_indices=list(curr_frags),
            )
        )

    return sentences


def clean_chinese_subtitle_punctuation(text: str) -> str:
    """
    Format Chinese subtitle text according to professional subtitle standards:
    - Preserve internal commas (，), pauses (、), question marks (？), exclamation marks (！), colons (：).
    - Remove trailing period (。) and trailing commas.
    - Normalize whitespace and punctuation.
    """
    text = text.strip()
    if not text:
        return ""
    # Strip trailing punctuation like 。 . ； ; ， ,
    text = re.sub(r"[。\.；;，,]+$", "", text).strip()
    return text


def split_chinese_text_by_phrase(zh_text: str, max_len: int = 28) -> list[str]:
    """
    Split Chinese text naturally by punctuation and linguistic conjunctions/phrases.
    Ensures single lines don't exceed max_len while keeping phrases and words intact.
    """
    zh_text = zh_text.strip()
    if not zh_text or len(zh_text) <= max_len:
        return [clean_chinese_subtitle_punctuation(zh_text)] if zh_text else []

    # Step 1: Split on punctuation while preserving punctuation with preceding segment
    raw_pieces = re.findall(r"[^，、；。！？,;!?]+[，、；。！？,;!?]?", zh_text)
    if not raw_pieces:
        raw_pieces = [zh_text]

    refined_pieces: list[str] = []
    for piece in raw_pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= max_len:
            refined_pieces.append(piece)
        else:
            # Try splitting by conjunctions
            split_pos = -1
            for conj in CHINESE_CONJUNCTIONS:
                idx = piece.find(conj)
                if 4 <= idx <= max_len:
                    split_pos = idx
                    break
            if split_pos != -1:
                p1 = piece[:split_pos].strip()
                p2 = piece[split_pos:].strip()
                if p1:
                    refined_pieces.append(p1)
                if p2:
                    refined_pieces.append(p2)
            else:
                # If no conjunction match, split near middle
                mid = len(piece) // 2
                p1 = piece[:mid].strip()
                p2 = piece[mid:].strip()
                if p1:
                    refined_pieces.append(p1)
                if p2:
                    refined_pieces.append(p2)

    # Step 2: Merge adjacent small pieces if combined length <= max_len
    merged: list[str] = []
    if not refined_pieces:
        return [clean_chinese_subtitle_punctuation(zh_text)]

    curr = refined_pieces[0]
    for next_p in refined_pieces[1:]:
        if len(curr) + len(next_p) <= max_len:
            curr += next_p
        else:
            merged.append(clean_chinese_subtitle_punctuation(curr))
            curr = next_p
    merged.append(clean_chinese_subtitle_punctuation(curr))

    return [p for p in merged if p]


def split_english_text_to_n_parts(en_text: str, n_parts: int, zh_lengths: list[int]) -> list[str]:
    """
    Split an English sentence into n_parts aligning with the Chinese sub-phrases.
    Prioritizes punctuation/clause boundaries, falling back to proportional word-count allocation.
    """
    en_text = en_text.strip()
    if n_parts <= 1 or not en_text:
        return [en_text]

    clauses = [
        c.strip()
        for c in re.split(r"[,;—\-]|\band\b|\bbut\b|\bso\b|\bbecause\b", en_text)
        if c.strip()
    ]
    if len(clauses) == n_parts:
        return clauses

    words = en_text.split()
    if len(words) <= n_parts:
        return [en_text] + [""] * (n_parts - 1)

    total_zh_len = sum(zh_lengths) if zh_lengths else n_parts
    ratios = [(length / total_zh_len) for length in zh_lengths]

    en_parts: list[str] = []
    current_idx = 0
    total_words = len(words)

    for i in range(n_parts):
        if i == n_parts - 1:
            part_words = words[current_idx:]
        else:
            count = max(1, round(ratios[i] * total_words))
            count = min(count, total_words - current_idx - (n_parts - i - 1))
            part_words = words[current_idx : current_idx + count]
            current_idx += count
        en_parts.append(" ".join(part_words))

    return en_parts


def split_chinese_sentence_into_cues(
    en_text: str,
    zh_text: str,
    start_ms: int,
    end_ms: int,
    start_index: int = 1,
    max_cjk_len: int = 20,
) -> list[SubtitleItem]:
    """
    Convert a translated whole sentence into visual SubtitleItem cues.
    Splits long Chinese sentences by natural phrasing while proportionally interpolating timestamps.
    """
    zh_text = zh_text.strip()
    en_text = en_text.strip()

    if not zh_text or len(zh_text) <= max_cjk_len:
        return [
            SubtitleItem(
                index=start_index,
                start_ms=start_ms,
                end_ms=end_ms,
                source_text=en_text,
                target_text=zh_text,
            )
        ]

    zh_pieces = split_chinese_text_by_phrase(zh_text, max_len=max_cjk_len)
    if len(zh_pieces) <= 1:
        return [
            SubtitleItem(
                index=start_index,
                start_ms=start_ms,
                end_ms=end_ms,
                source_text=en_text,
                target_text=zh_text,
            )
        ]

    zh_lengths = [len(p) for p in zh_pieces]
    total_zh_len = sum(zh_lengths)
    en_pieces = split_english_text_to_n_parts(en_text, len(zh_pieces), zh_lengths)

    duration = max(end_ms - start_ms, 500)
    cues: list[SubtitleItem] = []
    curr_t = start_ms

    for idx, (zh_p, en_p, z_len) in enumerate(zip(zh_pieces, en_pieces, zh_lengths)):
        if idx == len(zh_pieces) - 1:
            next_t = end_ms
        else:
            cue_dur = int(duration * (z_len / total_zh_len))
            next_t = min(curr_t + cue_dur, end_ms - 200)

        cues.append(
            SubtitleItem(
                index=start_index + idx,
                start_ms=curr_t,
                end_ms=max(next_t, curr_t + 200),
                source_text=en_p,
                target_text=zh_p,
            )
        )
        curr_t = next_t

    return cues


def save_transcript_json(sentences: list[TranscriptSentence], path: Path) -> None:
    """Save structured transcript to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [s.to_dict() for s in sentences]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_transcript_txt(sentences: list[TranscriptSentence], path: Path) -> None:
    """Save human-readable bilingual transcript to text file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for s in sentences:
        blocks.append(
            f"[{s.sentence_id}] {s.start_srt} --> {s.end_srt}\n"
            f"EN: {s.en_text}\n"
            f"ZH: {s.zh_text or '(Pending Translation)'}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


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
    items: list[SubtitleItem] | None = None,
    style: SubtitleStyleConfig | None = None,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    zh_items: list[SubtitleItem] | None = None,
    en_items: list[SubtitleItem] | None = None,
) -> str:
    """
    Generate styled bilingual ASS content with asynchronous dual-track layers,
    fixed vertical margin anchoring, and smooth alpha fade transitions.
    """
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
Style: Default,{style.zh_font},{style.zh_font_size},{style.zh_primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},2,{style.margin_l},{style.margin_r},{style.bilingual_zh_margin_v},1
Style: SubtitleZh,{style.zh_font},{style.zh_font_size},{style.zh_primary_color},&H000000FF,{style.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},2,{style.margin_l},{style.margin_r},{style.bilingual_zh_margin_v},1
Style: SubtitleEn,{style.en_font},{style.en_font_size},{style.en_primary_color},&H000000FF,{style.outline_color},&H80000000,0,0,0,0,100,100,0,0,1,{style.outline_width * 0.7:.1f},{style.shadow * 0.7:.1f},2,{style.margin_l},{style.margin_r},{style.bilingual_en_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    fade_tag = f"{{\\fad({style.fade_in_ms},{style.fade_out_ms})}}"

    if zh_items is not None and en_items is not None:
        # Dual-track asynchronous independent events
        for z in zh_items:
            zh_raw = (z.target_text or z.source_text).replace("\n", " ").strip()
            zh_clean = clean_chinese_subtitle_punctuation(zh_raw)
            if zh_clean:
                text = f"{fade_tag}{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{zh_clean}"
                events.append(f"Dialogue: 1,{z.start_ass},{z.end_ass},SubtitleZh,,0,0,0,,{text}")

        for e in en_items:
            en_clean = e.source_text.replace("\n", " ").strip()
            if en_clean:
                text = f"{fade_tag}{{\\fn{style.en_font}\\fs{style.en_font_size}\\c{style.en_primary_color}&\\b0}}{en_clean}"
                events.append(f"Dialogue: 0,{e.start_ass},{e.end_ass},SubtitleEn,,0,0,0,,{text}")
    elif items:
        # Standard combined items list
        for item in items:
            start = item.start_ass
            end = item.end_ass

            if item.target_text and item.source_text and item.target_text != item.source_text:
                zh_clean = clean_chinese_subtitle_punctuation(
                    item.target_text.replace("\n", " ").strip()
                )
                en_clean = item.source_text.replace("\n", " ").strip()
                zh_text = f"{fade_tag}{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{zh_clean}"
                en_text = f"{fade_tag}{{\\fn{style.en_font}\\fs{style.en_font_size}\\c{style.en_primary_color}&\\b0}}{en_clean}"
                events.append(f"Dialogue: 1,{start},{end},SubtitleZh,,0,0,0,,{zh_text}")
                events.append(f"Dialogue: 0,{start},{end},SubtitleEn,,0,0,0,,{en_text}")
            elif item.target_text:
                clean_t = clean_chinese_subtitle_punctuation(
                    item.target_text.replace("\n", " ").strip()
                )
                text = f"{fade_tag}{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{clean_t}"
                events.append(f"Dialogue: 1,{start},{end},SubtitleZh,,0,0,0,,{text}")
            else:
                clean_s = item.source_text.replace("\n", " ").strip()
                text = f"{fade_tag}{{\\fn{style.en_font}\\fs{style.en_font_size}\\c{style.en_primary_color}&\\b0}}{clean_s}"
                events.append(f"Dialogue: 0,{start},{end},SubtitleEn,,0,0,0,,{text}")

    # Sort events by start time
    events.sort(key=lambda line: line.split(",")[1] if "," in line else "")

    return header + "\n".join(events) + "\n"


def generate_zh_ass(
    items: list[SubtitleItem],
    style: SubtitleStyleConfig | None = None,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """Generate styled pure Chinese single-line ASS content with fade transitions."""
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
    fade_tag = f"{{\\fad({style.fade_in_ms},{style.fade_out_ms})}}"
    for item in items:
        start = item.start_ass
        end = item.end_ass
        text = clean_chinese_subtitle_punctuation(
            (item.target_text if item.target_text else item.source_text).replace("\n", " ").strip()
        )
        events.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{fade_tag}{{\\fn{style.zh_font}\\fs{style.zh_font_size}\\b1}}{text}"
        )

    return header + "\n".join(events) + "\n"
