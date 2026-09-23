import io
import json

import pytest

from app.services.script_segmentation import split_sentences
from app.services.speech import (
    ENGINE,
    SpeechSynthesizer,
    build_sentences,
    parse_speech_marks,
)


def speech_marks_payload(entries: list[tuple[str, int]]) -> bytes:
    """Polly の Speech Marks 応答（1 行 1 JSON）を作る。"""
    lines = [
        json.dumps({"time": time, "type": "ssml", "start": 0, "value": value})
        for value, time in entries
    ]
    return "\n".join(lines).encode("utf-8")


class FakePollyClient:
    """synthesize_speech の呼び出しを記録し、あらかじめ決めた応答を返す。"""

    def __init__(self, audio: bytes = b"mp3-bytes", marks: bytes = b""):
        self.audio = audio
        self.marks = marks
        self.calls: list[dict] = []

    def synthesize_speech(self, **params):
        self.calls.append(params)
        body = self.marks if params["OutputFormat"] == "json" else self.audio
        return {"AudioStream": io.BytesIO(body)}


class TestParseSpeechMarks:
    def test_extracts_time_per_mark(self):
        raw = speech_marks_payload([("s0", 12), ("s1", 4712), ("s2", 8617)])
        assert parse_speech_marks(raw) == {0: 12, 1: 4712, 2: 8617}

    def test_ignores_marks_we_did_not_create(self):
        raw = (
            speech_marks_payload([("s0", 0)])
            + b'\n{"time": 100, "type": "word", "value": "\\u672c\\u65e5"}'
        )
        assert parse_speech_marks(raw) == {0: 0}

    def test_ignores_blank_lines(self):
        raw = b"\n" + speech_marks_payload([("s0", 5)]) + b"\n\n"
        assert parse_speech_marks(raw) == {0: 5}

    def test_empty_payload(self):
        assert parse_speech_marks(b"") == {}


class TestBuildSentences:
    def test_pairs_text_with_start_time(self):
        sentences = build_sentences(["一つ目。", "二つ目。"], {0: 0, 1: 1500})
        assert [s.index for s in sentences] == [0, 1]
        assert [s.text for s in sentences] == ["一つ目。", "二つ目。"]
        assert [s.start_ms for s in sentences] == [0, 1500]

    def test_missing_position_is_an_error(self):
        # 位置の欠けた文をそのまま通すと、再生位置の無い問題が静かに出来てしまう
        with pytest.raises(ValueError, match="1"):
            build_sentences(["一つ目。", "二つ目。"], {0: 0})

    def test_empty(self):
        assert build_sentences([], {}) == []


class TestSpeechSynthesizer:
    def _synthesize(self, text="一つ目です。二つ目です。", **kwargs):
        # Polly は文の数だけ mark を返すので、題材に合わせて用意する
        count = len(split_sentences(text))
        marks = speech_marks_payload([(f"s{i}", i * 2000) for i in range(count)])
        client = FakePollyClient(audio=b"AUDIO", marks=marks)
        synthesizer = SpeechSynthesizer(client=client, **kwargs)
        return synthesizer.synthesize(text), client

    def test_returns_audio_and_sentences(self):
        result, _ = self._synthesize()
        assert result.audio == b"AUDIO"
        assert [s.text for s in result.sentences] == ["一つ目です。", "二つ目です。"]
        assert [s.start_ms for s in result.sentences] == [0, 2000]

    def test_calls_polly_exactly_twice(self):
        # 文の数に関わらず「音声」と「Speech Marks」の 2 回で済むことが設計の要
        _, client = self._synthesize("一。二。三。四。五。六。")
        assert len(client.calls) == 2

    def test_requests_audio_then_marks(self):
        _, client = self._synthesize()
        assert client.calls[0]["OutputFormat"] == "mp3"
        assert client.calls[1]["OutputFormat"] == "json"
        assert client.calls[1]["SpeechMarkTypes"] == ["ssml"]

    def test_both_calls_use_the_same_ssml(self):
        # 音声と Speech Marks が別の SSML から作られると位置がずれる
        _, client = self._synthesize()
        assert client.calls[0]["Text"] == client.calls[1]["Text"]

    def test_uses_neural_engine_and_ssml(self):
        _, client = self._synthesize()
        assert client.calls[0]["Engine"] == ENGINE
        assert client.calls[0]["TextType"] == "ssml"

    def test_default_voice_is_takumi(self):
        _, client = self._synthesize()
        assert client.calls[0]["VoiceId"] == "Takumi"

    def test_voice_can_be_overridden(self):
        _, client = self._synthesize(voice_id="Kazuha")
        assert client.calls[0]["VoiceId"] == "Kazuha"

    def test_break_is_inserted_between_sentences(self):
        _, client = self._synthesize(break_ms=350)
        assert '<break time="350ms"/>' in client.calls[0]["Text"]

    def test_break_can_be_disabled(self):
        _, client = self._synthesize(break_ms=0)
        assert "<break" not in client.calls[0]["Text"]

    def test_empty_text_is_rejected(self):
        client = FakePollyClient()
        with pytest.raises(ValueError):
            SpeechSynthesizer(client=client).synthesize("   ")
        assert client.calls == []
