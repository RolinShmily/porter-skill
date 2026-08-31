"""Tests for subtitle formatting, parsing, translation, transcript generation, and controller."""

import json
from unittest.mock import MagicMock, patch

from porter_skill.config import LLMConfig, PorterConfig
from porter_skill.extractors.base import RawMaterialResult, VideoMetadata
from porter_skill.subtitle.controller import (
    compute_adaptive_subtitle_style,
    generate_subtitles,
    has_chinese_translation,
    transcribe_with_bcut,
    transcribe_with_google_stt,
)
from porter_skill.subtitle.formatter import (
    SubtitleItem,
    TranscriptSentence,
    align_bilingual_items,
    clean_chinese_subtitle_punctuation,
    generate_bilingual_ass,
    generate_bilingual_srt,
    generate_zh_ass,
    generate_zh_srt,
    merge_short_fragments,
    ms_to_ass_time,
    ms_to_srt_time,
    parse_srt,
    reconstruct_sentences_from_fragments,
    restore_english_punctuation_heuristic,
    save_transcript_json,
    save_transcript_txt,
    split_chinese_sentence_into_cues,
    split_chinese_text_by_phrase,
    split_english_text_to_n_parts,
    srt_time_to_ms,
)
from porter_skill.subtitle.translator import (
    translate_sentences_with_bing_http,
    translate_sentences_with_direct_llm,
    translate_sentences_with_google_http,
    translate_with_bing_http,
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


def test_clean_chinese_subtitle_punctuation():
    """Verify professional punctuation formatting for Chinese subtitles."""
    assert clean_chinese_subtitle_punctuation("这是一个完整句子。") == "这是一个完整句子"
    assert clean_chinese_subtitle_punctuation("这是前半句，") == "这是前半句，"
    assert clean_chinese_subtitle_punctuation("这是问句吗？") == "这是问句吗？"
    assert clean_chinese_subtitle_punctuation("这是感叹句！") == "这是感叹句！"
    assert clean_chinese_subtitle_punctuation("前半句，后半句。") == "前半句，后半句"


def test_split_chinese_text_by_phrase():
    """Verify Chinese phrase splitting by punctuation and linguistic conjunctions."""
    short_text = "这是一个短句。"
    assert split_chinese_text_by_phrase(short_text, max_len=20) == ["这是一个短句"]

    long_text = "如果你喜欢这个视频，请务必订阅我的频道并打开小铃铛。"
    parts = split_chinese_text_by_phrase(long_text, max_len=20)
    assert len(parts) == 2
    assert parts[0] == "如果你喜欢这个视频，"
    assert parts[1] == "请务必订阅我的频道并打开小铃铛"


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
    assert cues[1].target_text == "请务必订阅我的频道"
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
    assert "这是整句中文翻译" in bi_ass
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


def test_translate_sentences_with_bing_http_mock():
    """Verify pure Python Bing HTTP translator on transcript sentences."""
    sentences = [
        TranscriptSentence(
            sentence_id=1,
            start_ms=0,
            end_ms=3000,
            en_text="We need to move fast.",
            zh_text="",
        )
    ]
    with patch("porter_skill.subtitle.translator.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Mock translator page response with IG, IID and AbusePreventionHelper
        mock_page_resp = MagicMock()
        mock_page_resp.text = (
            'IG:"1234567890ABCDEF" data-iid="translator.5025" '
            'params_AbusePreventionHelper = [1788099292818,"mock_token_key",3600000];'
        )
        mock_session.get.return_value = mock_page_resp

        # Mock translate post response
        mock_trans_resp = MagicMock()
        mock_trans_resp.status_code = 200
        mock_trans_resp.json.return_value = [{"translations": [{"text": "我们需要快速行动。"}]}]
        mock_session.post.return_value = mock_trans_resp

        res = translate_sentences_with_bing_http(sentences)
        assert len(res) == 1
        assert res[0].zh_text == "我们需要快速行动。"

        item_res = translate_with_bing_http(
            [
                SubtitleItem(
                    index=1,
                    start_ms=0,
                    end_ms=3000,
                    source_text="We need to move fast.",
                    target_text="",
                )
            ]
        )
        assert len(item_res) == 1
        assert item_res[0].target_text == "我们需要快速行动。"


def test_transcribe_with_bcut_mock(tmp_path):
    """Verify pure Python Bcut ASR with mocked HTTP upload and result polling."""
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"dummy wav data")
    out_srt = tmp_path / "out.srt"

    with (
        patch("porter_skill.subtitle.controller.requests.post") as mock_post,
        patch("porter_skill.subtitle.controller.requests.put") as mock_put,
        patch("porter_skill.subtitle.controller.requests.get") as mock_get,
    ):
        # Mock resource create
        mock_create = MagicMock()
        mock_create.status_code = 200
        mock_create.json.return_value = {
            "data": {
                "in_boss_key": "k",
                "resource_id": "r",
                "upload_id": "u",
                "upload_urls": ["https://mock.upload/part1"],
                "per_size": 1024 * 1024,
            }
        }
        # Mock commit complete
        mock_commit = MagicMock()
        mock_commit.status_code = 200
        mock_commit.json.return_value = {"data": {"download_url": "https://mock.dl/a.wav"}}
        # Mock create task
        mock_task = MagicMock()
        mock_task.status_code = 200
        mock_task.json.return_value = {"data": {"task_id": "task_123"}}

        mock_post.side_effect = [mock_create, mock_commit, mock_task]

        # Mock put part
        mock_put_resp = MagicMock()
        mock_put_resp.headers = {"Etag": "etag_123"}
        mock_put.return_value = mock_put_resp

        # Mock query result
        mock_q_resp = MagicMock()
        mock_q_resp.status_code = 200
        mock_q_resp.json.return_value = {
            "data": {
                "state": 4,
                "result": json.dumps(
                    {
                        "utterances": [
                            {"start_time": 0, "end_time": 2000, "transcript": "Hello from Bcut ASR"}
                        ]
                    }
                ),
            }
        }
        mock_get.return_value = mock_q_resp

        success = transcribe_with_bcut(audio_file, out_srt)
        assert success is True
        assert out_srt.is_file()
        assert "Hello from Bcut ASR" in out_srt.read_text(encoding="utf-8")


def test_transcribe_with_google_stt_mock(tmp_path):
    """Verify pure Python Google Web Speech STT with mocked FFmpeg VAD and speechrecognition."""
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"dummy wav data")
    out_srt = tmp_path / "out.srt"
    cfg = PorterConfig()

    with (
        patch("subprocess.run") as mock_subproc,
        patch("speech_recognition.Recognizer") as mock_r_cls,
        patch("speech_recognition.AudioFile"),
    ):
        # Mock ffmpeg silencedetect & ffprobe duration
        mock_vad = MagicMock()
        mock_vad.stderr = (
            "[silencedetect @ 0x...] silence_start: 2.0\n[silencedetect @ 0x...] silence_end: 2.5"
        )
        mock_probe = MagicMock()
        mock_probe.stdout = "5.0\n"
        mock_subproc.side_effect = [mock_vad, mock_probe]

        mock_r = MagicMock()
        mock_r.recognize_google.return_value = "Hello from Google STT"
        mock_r_cls.return_value = mock_r

        success = transcribe_with_google_stt(audio_file, out_srt, cfg)
        assert success is True
        assert out_srt.is_file()


def test_restore_english_punctuation_heuristic():
    """Verify heuristic English punctuation and capitalization restoration for raw ASR streams."""
    # Case 1: Multiple run-on sentences with pronoun starters
    raw1 = "understanding group theory doesn't clog your working memory It doesn't compete with your active thinking But it kind of expands What your brain can do"
    res1 = restore_english_punctuation_heuristic(raw1)
    assert res1.startswith("Understanding")
    assert "memory." in res1
    assert "It doesn't compete" in res1
    assert "thinking," in res1
    assert "what your brain can do." in res1

    # Case 2: Proper nouns and questions
    raw2 = "did you know that OpenAI and Google use Python for AI research"
    res2 = restore_english_punctuation_heuristic(raw2)
    assert res2 == "Did you know that OpenAI and Google use Python for AI research?"

    # Case 3: Subordinating conjunctions in long sentences
    raw3 = "if you practice every day you will master this skill because consistency is key and it will pay off"
    res3 = restore_english_punctuation_heuristic(raw3)
    assert "skill, because" in res3
    assert "key, and" in res3


def test_split_english_text_clause_aware():
    """Verify clause-aware and hanging-conjunction-free English text splitting."""
    en_text = (
        "Understanding group theory doesn't clog your working memory. "
        "It doesn't compete with your active thinking, but it kind of expands what your brain can do."
    )
    zh_lengths = [27, 14]
    parts = split_english_text_to_n_parts(en_text, 2, zh_lengths)

    assert len(parts) == 2
    # Ensure "But" / "but" is NOT left hanging at the end of Part 1
    assert not parts[0].endswith(("but", "But", "and", "And", "or", "Or"))
    assert parts[0].endswith(",")
    assert parts[1].startswith("but it kind of expands")


def test_split_chinese_sentence_into_cues_with_restoration():
    """Verify end-to-end cue splitting with punctuation and alignment."""
    raw_en = "understanding group theory doesn't clog your working memory It doesn't compete with your active thinking But it kind of expands What your brain can do"
    zh_text = (
        "理解群论不会堵塞你的工作记忆，它不会与你的主动思维竞争，但它有点扩展了你大脑能做的事情"
    )

    cues = split_chinese_sentence_into_cues(
        en_text=raw_en,
        zh_text=zh_text,
        start_ms=114090,
        end_ms=124390,
        start_index=1,
        max_cjk_len=28,
    )

    assert len(cues) == 2
    assert "，" in cues[0].target_text
    assert cues[0].source_text.endswith(",")
    assert not cues[0].source_text.endswith(("but", "But"))
    assert cues[1].source_text.startswith("but it kind of")


def test_compute_adaptive_subtitle_style():
    """Verify adaptive styling across diverse video aspect ratios and physical resolutions."""
    # 1. 1106x720 (~1.53:1 3:2/4:3-like compact screen from user screenshot)
    b_st, z_st, px, py = compute_adaptive_subtitle_style(1106, 720)
    assert px == 1106
    assert py == 720
    assert b_st.zh_font_size >= 38  # Boosted for compact screen
    assert b_st.en_font_size >= 24
    assert z_st.zh_font_size > b_st.zh_font_size  # Pure ZH is larger
    assert b_st.bilingual_zh_margin_v > b_st.bilingual_en_margin_v

    # 2. 1920x1080 (Standard 16:9 1080p)
    b_1080, z_1080, px_1080, py_1080 = compute_adaptive_subtitle_style(1920, 1080)
    assert px_1080 == 1920
    assert py_1080 == 1080
    assert b_1080.zh_font_size == 52
    assert b_1080.en_font_size == 34
    assert z_1080.zh_font_size == 58

    # 3. 1080x1920 (Vertical 9:16)
    b_vert, z_vert, px_vert, py_vert = compute_adaptive_subtitle_style(1080, 1920)
    assert px_vert == 1080
    assert py_vert == 1920
    assert b_vert.zh_font_size == 56
    assert b_vert.bilingual_zh_margin_v == 220
    assert z_vert.zh_font_size == 64

    # 4. 960x960 (Square 1:1)
    b_sq, z_sq, px_sq, py_sq = compute_adaptive_subtitle_style(960, 960)
    assert px_sq == 960
    assert py_sq == 960
    assert b_sq.zh_font_size >= 55  # Boosted for square screen
    assert z_sq.zh_font_size >= 60
