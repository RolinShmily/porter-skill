"""Tests for subtitle formatting, parsing, translation, transcript generation, and controller."""

import json
from unittest.mock import MagicMock, patch

from porter_skill.config import LLMConfig, PorterConfig
from porter_skill.extractors.base import RawMaterialResult, VideoMetadata
from porter_skill.subtitle.controller import generate_subtitles, has_chinese_translation
from porter_skill.subtitle.formatter import (
    SubtitleItem,
    TranscriptSentence,
    align_bilingual_items,
    generate_bilingual_ass,
    generate_bilingual_srt,
    generate_zh_ass,
    generate_zh_srt,
    merge_short_fragments,
    ms_to_ass_time,
    ms_to_srt_time,
    parse_srt,
    reconstruct_sentences_from_fragments,
    save_transcript_json,
    save_transcript_txt,
    split_chinese_sentence_into_cues,
    split_chinese_text_by_phrase,
    srt_time_to_ms,
)
from porter_skill.subtitle.translator import (
    translate_sentences_with_direct_llm,
    translate_sentences_with_google_http,
    translate_with_google_http,
    translate_with_mymemory_http,
)


def test_time_conversions():
    """Verify time conversion helpers."""
    ms = srt_time_to_ms("01:23:45,678")
    assert ms == 5025678
    assert ms_to_srt_time(ms) == "01:23:45,678"
    assert ms_to_ass_time(ms) == "1:23:45.67"


def test_parse_and_generate_srt():
    """Verify parsing and formatting of SRT content."""
    sample_srt = """1
00:00:01,000 --> 00:00:04,000
你好世界
Hello World

2
00:00:05,500 --> 00:00:08,200
这是第二行
This is line 2
"""
    items = parse_srt(sample_srt)
    assert len(items) == 2
    assert items[0].start_ms == 1000
    assert items[0].end_ms == 4000
    assert items[0].target_text == "你好世界"
    assert items[0].source_text == "Hello World"

    bilingual_srt = generate_bilingual_srt(items)
    assert "你好世界\nHello World" in bilingual_srt

    zh_srt = generate_zh_srt(items)
    assert "你好世界" in zh_srt
    assert "Hello World" not in zh_srt


def test_parse_srt_monolingual_multiline():
    """Verify parsing of monolingual SRT with wrapped lines into single-line items."""
    sample_srt = """1
00:00:01,000 --> 00:00:04,000
This is a long sentence
that was wrapped across two lines.
"""
    items = parse_srt(sample_srt)
    assert len(items) == 1
    assert items[0].source_text == "This is a long sentence that was wrapped across two lines."
    assert items[0].target_text == ""


def test_merge_short_fragments():
    """Verify merging of short subtitle fragments into extended single lines."""
    items = [
        SubtitleItem(1, 0, 3000, "This is my speech to text extension for", ""),
        SubtitleItem(2, 3000, 6000, "pie. Alt M to open up the mic.", ""),
    ]
    merged = merge_short_fragments(items)
    assert len(merged) == 1
    assert (
        merged[0].source_text
        == "This is my speech to text extension for pie. Alt M to open up the mic."
    )
    assert merged[0].start_ms == 0
    assert merged[0].end_ms == 6000


def test_align_bilingual_items():
    """Verify aligning pre-extracted Chinese subtitles with English subtitles."""
    en_items = [
        SubtitleItem(1, 0, 4000, "Hello world", ""),
        SubtitleItem(2, 4000, 8000, "Goodbye world", ""),
    ]
    zh_items = [
        SubtitleItem(1, 0, 4000, "你好世界", ""),
        SubtitleItem(2, 4000, 8000, "再见世界", ""),
    ]
    aligned = align_bilingual_items(en_items, zh_items)
    assert len(aligned) == 2
    assert aligned[0].target_text == "你好世界"
    assert aligned[1].target_text == "再见世界"


def test_reconstruct_sentences_from_fragments():
    """Verify reconstructing raw broken fragments into whole grammatical transcript sentences."""
    fragments = [
        SubtitleItem(1, 1000, 2500, "If you enjoy", ""),
        SubtitleItem(2, 2500, 4000, "this video,", ""),
        SubtitleItem(3, 4000, 6000, "make sure to subscribe.", ""),
        SubtitleItem(4, 7500, 9000, "Today we have", ""),
        SubtitleItem(5, 9000, 11000, "an exciting topic!", ""),
    ]
    sentences = reconstruct_sentences_from_fragments(fragments)
    assert len(sentences) == 2
    assert sentences[0].en_text == "If you enjoy this video, make sure to subscribe."
    assert sentences[0].start_ms == 1000
    assert sentences[0].end_ms == 6000
    assert sentences[0].fragment_indices == [1, 2, 3]

    assert sentences[1].en_text == "Today we have an exciting topic!"
    assert sentences[1].start_ms == 7500
    assert sentences[1].end_ms == 11000
    assert sentences[1].fragment_indices == [4, 5]


def test_split_chinese_text_by_phrase():
    """Verify Chinese phrase splitting by punctuation and linguistic conjunctions."""
    short_text = "这是一个短句。"
    assert split_chinese_text_by_phrase(short_text, max_len=20) == ["这是一个短句。"]

    long_text = "如果你喜欢这个视频，请务必订阅我的频道并打开小铃铛。"
    parts = split_chinese_text_by_phrase(long_text, max_len=20)
    assert len(parts) == 2
    assert parts[0] == "如果你喜欢这个视频，"
    assert parts[1] == "请务必订阅我的频道并打开小铃铛。"


def test_split_chinese_sentence_into_cues():
    """Verify splitting a translated whole sentence into proportional visual subtitle cues."""
    en = "If you enjoy this video, make sure to subscribe to the channel."
    zh = "如果你喜欢这个视频，请务必订阅我的频道。"
    cues = split_chinese_sentence_into_cues(
        en_text=en, zh_text=zh, start_ms=1000, end_ms=7000, start_index=1, max_cjk_len=15
    )
    assert len(cues) == 2
    assert cues[0].index == 1
    assert cues[0].target_text == "如果你喜欢这个视频，"
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms < 7000

    assert cues[1].index == 2
    assert cues[1].target_text == "请务必订阅我的频道。"
    assert cues[1].end_ms == 7000


def test_save_transcript_files(tmp_path):
    """Verify saving transcript to structured JSON and readable TXT files."""
    json_path = tmp_path / "transcript.json"
    txt_path = tmp_path / "transcript.txt"

    sentences = [
        TranscriptSentence(
            sentence_id=1,
            start_ms=1000,
            end_ms=4000,
            en_text="Hello world.",
            zh_text="你好世界。",
            fragment_indices=[1, 2],
        )
    ]

    save_transcript_json(sentences, json_path)
    save_transcript_txt(sentences, txt_path)

    assert json_path.exists()
    assert txt_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["en_text"] == "Hello world."
    assert data[0]["zh_text"] == "你好世界。"

    txt_content = txt_path.read_text(encoding="utf-8")
    assert "[1] 00:00:01,000 --> 00:00:04,000" in txt_content
    assert "EN: Hello world." in txt_content
    assert "ZH: 你好世界。" in txt_content


def test_generate_ass_styling():
    """Verify generation of styled ASS scripts with fade transitions and margin anchoring."""
    items = [
        SubtitleItem(
            index=1,
            start_ms=1000,
            end_ms=4500,
            source_text="Welcome to the video",
            target_text="欢迎观看本期视频",
        )
    ]

    bi_ass = generate_bilingual_ass(items)
    assert "[Script Info]" in bi_ass
    assert "[V4+ Styles]" in bi_ass
    assert "欢迎观看本期视频" in bi_ass
    assert "Welcome to the video" in bi_ass
    assert "0:00:01.00,0:00:04.50" in bi_ass
    assert "\\fad(120,120)" in bi_ass
    assert "SubtitleZh" in bi_ass
    assert "SubtitleEn" in bi_ass

    zh_ass = generate_zh_ass(items)
    assert "欢迎观看本期视频" in zh_ass
    assert "Welcome to the video" not in zh_ass
    assert "\\fad(120,120)" in zh_ass


def test_generate_asynchronous_bilingual_ass():
    """Verify asynchronous dual-track independent events in ASS."""
    zh_items = [
        SubtitleItem(1, 1000, 7000, "", "这是整句中文翻译。"),
    ]
    en_items = [
        SubtitleItem(1, 1000, 3500, "This is part one,", ""),
        SubtitleItem(2, 3600, 7000, "and part two.", ""),
    ]

    bi_ass = generate_bilingual_ass(zh_items=zh_items, en_items=en_items)
    assert "这是整句中文翻译。" in bi_ass
    assert "This is part one," in bi_ass
    assert "and part two." in bi_ass
    assert "SubtitleZh" in bi_ass
    assert "SubtitleEn" in bi_ass
    assert "\\fad(120,120)" in bi_ass


def test_translate_with_google_http_mock():
    """Verify pure python Google HTTP translator function."""
    items = [SubtitleItem(index=1, start_ms=0, end_ms=1000, source_text="Hello", target_text="")]
    with patch("requests.get") as mock_get:
        mock_resp = patch("requests.Response").start()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [[["你好", "Hello"]]]
        mock_get.return_value = mock_resp

        res = translate_with_google_http(items)
        assert len(res) == 1
        assert res[0].target_text == "你好"


def test_translate_sentences_with_google_http_mock():
    """Verify pure python Google HTTP translator function on transcript sentences."""
    sentences = [
        TranscriptSentence(
            sentence_id=1,
            start_ms=0,
            end_ms=3000,
            en_text="Hello world.",
            zh_text="",
        )
    ]
    with patch("requests.get") as mock_get:
        mock_resp = patch("requests.Response").start()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [[["你好世界", "Hello world."]]]
        mock_get.return_value = mock_resp

        res = translate_sentences_with_google_http(sentences)
        assert len(res) == 1
        assert res[0].zh_text == "你好世界"


def test_translate_sentences_with_direct_llm_mock():
    """Verify translating transcript sentences using LLM API."""
    sentences = [
        TranscriptSentence(
            sentence_id=1,
            start_ms=0,
            end_ms=3000,
            en_text="Hello world.",
            zh_text="",
        )
    ]
    cfg = PorterConfig(llm=LLMConfig(api_key="sk-test-mock"))

    with patch("porter_skill.subtitle.translator.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_choice = MagicMock()
        mock_choice.message.content = '[{"id": 1, "en": "Hello world.", "zh": "你好，世界。"}]'
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp

        res = translate_sentences_with_direct_llm(sentences, cfg)
        assert len(res) == 1
        assert res[0].zh_text == "你好，世界。"


def test_generate_subtitles_fallback_flow(tmp_path):
    """Verify subtitle controller fallback, transcript generation, and file outputs."""
    raw_dir = tmp_path / "raw"
    cooked_dir = tmp_path / "cooked"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cooked_dir.mkdir(parents=True, exist_ok=True)

    # Create synthetic raw video & audio
    video_path = raw_dir / "video.mp4"
    audio_path = raw_dir / "audio.wav"
    video_path.write_bytes(b"dummy video")
    audio_path.write_bytes(b"dummy audio")

    # Scenario: No raw/subtitle.srt exists -> calls ASR
    raw_result = RawMaterialResult(
        task_dir=tmp_path,
        raw_dir=raw_dir,
        video_path=video_path,
        audio_path=audio_path,
        metadata=VideoMetadata(
            id="test",
            title="Test",
            safe_title="Test",
            url="https://youtube.com/watch?v=test",
            has_official_subtitle=False,
        ),
    )

    with (
        patch("porter_skill.subtitle.controller.run_asr_transcription") as mock_asr,
        patch(
            "porter_skill.subtitle.controller.translate_with_videocaptioner_cli"
        ) as mock_vc_trans,
    ):

        def fake_asr(audio_p, out_srt, cfg):
            out_srt.write_text(
                "1\n00:00:01,000 --> 00:00:03,000\nThis is ASR transcript.\n",
                encoding="utf-8",
            )
            return True

        mock_asr.side_effect = fake_asr
        mock_vc_trans.return_value = False

        with patch(
            "porter_skill.subtitle.controller.translate_sentences_with_direct_llm"
        ) as mock_llm_trans:
            mock_llm_trans.return_value = [
                TranscriptSentence(
                    sentence_id=1,
                    start_ms=1000,
                    end_ms=3000,
                    en_text="This is ASR transcript.",
                    zh_text="这是语音识别转录文本。",
                    fragment_indices=[1],
                )
            ]

            cfg = PorterConfig(llm=LLMConfig(api_key="sk-mock-test"))
            result = generate_subtitles(
                raw_material=raw_result,
                cooked_dir=cooked_dir,
                config=cfg,
            )

            assert result.used_asr is True
            assert result.subtitle_bilingual_srt.exists()
            assert result.subtitle_bilingual_ass.exists()
            assert result.subtitle_zh_srt.exists()
            assert result.subtitle_zh_ass.exists()
            assert (raw_dir / "transcript.json").exists()
            assert (raw_dir / "transcript.txt").exists()
            assert len(result.items) == 1
            assert result.items[0].target_text == "这是语音识别转录文本。"


def test_transcribe_with_whisper_api(tmp_path):
    """Verify pure Python Whisper API transcription helper."""
    from porter_skill.subtitle.controller import transcribe_with_whisper_api

    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"dummy wav data")
    out_srt = tmp_path / "out.srt"

    cfg = PorterConfig(
        asr=PorterConfig().asr.model_copy(update={"whisper_api_key": "sk-test-whisper"})
    )

    with patch("porter_skill.subtitle.controller.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = (
            "1\n00:00:00,000 --> 00:00:02,000\nHello from Whisper API\n"
        )

        success = transcribe_with_whisper_api(audio_file, out_srt, cfg)
        assert success is True
        assert out_srt.is_file()
        assert "Hello from Whisper API" in out_srt.read_text(encoding="utf-8")


def test_has_chinese_translation():
    """Verify CJK detection helper in subtitle controller."""
    items_with_zh = [
        SubtitleItem(index=1, start_ms=0, end_ms=1000, source_text="Hello", target_text="你好"),
        SubtitleItem(index=2, start_ms=1000, end_ms=2000, source_text="World", target_text="世界"),
    ]
    assert has_chinese_translation(items_with_zh) is True

    items_without_zh = [
        SubtitleItem(index=1, start_ms=0, end_ms=1000, source_text="Hello", target_text="Hello"),
        SubtitleItem(index=2, start_ms=1000, end_ms=2000, source_text="World", target_text="World"),
    ]
    assert has_chinese_translation(items_without_zh) is False


def test_translate_with_mymemory_http():
    """Verify MyMemory fallback translation logic with mocked HTTP response."""
    items = [
        SubtitleItem(index=1, start_ms=0, end_ms=1000, source_text="Hello", target_text=""),
    ]

    with patch("porter_skill.subtitle.translator.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"responseData": {"translatedText": "你好"}}
        mock_get.return_value = mock_resp

        results = translate_with_mymemory_http(items)
        assert len(results) == 1
        assert results[0].target_text == "你好"
