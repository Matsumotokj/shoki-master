"""Amazon Polly による音声合成。

題材の全文を 1 本の音声にまとめ、あわせて各文が音声上の何ミリ秒から始まるかを
取得する。音声を文ごとに分けて合成すると、合成もアップロードも文の数だけ必要に
なるうえ、一部だけ失敗した状態が生まれる。1 本にまとめることで呼び出しは
「音声」と「Speech Marks」の 2 回で済み、成功か失敗かが明確になる。
"""

import json
from dataclasses import dataclass

import boto3

from app.schemas.problem import Sentence
from app.services.script_segmentation import (
    END_MARK,
    build_ssml,
    parse_mark_name,
    split_sentences,
)

# 日本語で最も自然なエンジン。Polly の Generative エンジンは ja-JP 非対応。
ENGINE = "neural"
LANGUAGE_CODE = "ja-JP"
OUTPUT_FORMAT = "mp3"

# 既定の話者。聞き比べたうえで選択（scripts/compare_voices.py）。
DEFAULT_VOICE_ID = "Takumi"

# 文の間に入れる無音。句点区切りモードで停止したときに余韻を残すため。
SENTENCE_BREAK_MS = 350


@dataclass(frozen=True)
class Synthesis:
    """合成結果。音声データそのもの、文ごとの開始位置、音声全体の長さ。"""

    audio: bytes
    sentences: list[Sentence]
    duration_ms: int


def parse_speech_marks(raw: bytes) -> dict[int, int]:
    """Polly が返す Speech Marks を {文の番号: 開始ミリ秒} に変換する。

    応答は「1 行 1 JSON」の形式で、JSON 配列ではない点に注意。
    自分が埋めた mark 以外の行（Polly が付ける他の種別）は無視する。
    """
    starts: dict[int, int] = {}
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        mark = json.loads(line)
        index = parse_mark_name(mark.get("value", ""))
        if index is not None:
            starts[index] = int(mark["time"])
    return starts


def parse_end_mark(raw: bytes) -> int | None:
    """題材の末尾に置いた mark の位置（＝音声全体の長さ）を取り出す。"""
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            mark = json.loads(line)
            if mark.get("value") == END_MARK:
                return int(mark["time"])
    return None


def build_sentences(texts: list[str], starts: dict[int, int]) -> list[Sentence]:
    """文のリストと開始位置を突き合わせる。

    Polly から位置が返らなかった文があれば、その時点で異常とみなす。
    位置の欠けた文は再生位置を決められず、静かに壊れた問題が出来てしまうため。
    """
    missing = [i for i in range(len(texts)) if i not in starts]
    if missing:
        raise ValueError(f"音声上の開始位置を取得できない文があります: {missing}")

    return [
        Sentence(index=i, text=text, start_ms=starts[i])
        for i, text in enumerate(texts)
    ]


class SpeechSynthesizer:
    """Polly の呼び出しをまとめた薄いアダプタ。"""

    def __init__(
        self,
        voice_id: str = DEFAULT_VOICE_ID,
        client=None,
        region_name: str | None = None,
        break_ms: int = SENTENCE_BREAK_MS,
    ):
        self._voice_id = voice_id
        self._break_ms = break_ms
        self._client = client or boto3.client("polly", region_name=region_name)

    def synthesize(self, text: str) -> Synthesis:
        """題材の全文から、音声と文ごとの開始位置を作る。"""
        texts = split_sentences(text)
        if not texts:
            raise ValueError("音声にするテキストがありません")

        ssml = build_ssml(texts, break_ms=self._break_ms)
        audio = self._request(ssml, OUTPUT_FORMAT)
        marks = self._request(ssml, "json", speech_mark_types=["ssml"])

        sentences = build_sentences(texts, parse_speech_marks(marks))
        # 末尾の mark が返らなかった場合も作問は止めず、最後の文の開始位置で代用する
        duration_ms = parse_end_mark(marks) or sentences[-1].start_ms
        return Synthesis(audio=audio, sentences=sentences, duration_ms=duration_ms)

    def _request(
        self, ssml: str, output_format: str, speech_mark_types: list[str] | None = None
    ) -> bytes:
        params = {
            "Text": ssml,
            "TextType": "ssml",
            "VoiceId": self._voice_id,
            "Engine": ENGINE,
            "LanguageCode": LANGUAGE_CODE,
            "OutputFormat": output_format,
        }
        if speech_mark_types:
            params["SpeechMarkTypes"] = speech_mark_types

        response = self._client.synthesize_speech(**params)
        return response["AudioStream"].read()
