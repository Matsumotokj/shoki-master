"""日本語音声の聞き比べ用サンプルを生成する。

使い方:
    python scripts/compare_voices.py [出力先ディレクトリ]

Takumi / Kazuha / Tomoko の 3 音声について、文間の <break> あり・なしを
それぞれ生成する。あわせて各文の開始位置を表示し、句点区切りモードで
停止したときの自然さを確認できるようにする。
"""

import sys
from pathlib import Path
from xml.sax.saxutils import escape

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.script_segmentation import mark_name, split_sentences  # noqa: E402
from app.services.speech import SpeechSynthesizer  # noqa: E402

VOICES = ["Takumi", "Kazuha", "Tomoko"]
BREAK_MS = 350

SAMPLE = (
    "本日はお忙しい中お集まりいただき、誠にありがとうございます。"
    "第三四半期の業績についてご報告いたします。"
    "売上高は前年同期比で十二パーセント増の四十八億円となりました。"
    "特に法人向けサービスが好調で、新規契約数は百二十件に達しています。"
    "一方で、原材料費の高騰により利益率はやや低下しました。"
)


def build_ssml_with_break(sentences: list[str], break_ms: int) -> str:
    """文の間に明示的な無音を入れた SSML を組み立てる。"""
    parts = []
    for i, sentence in enumerate(sentences):
        if i > 0:
            parts.append(f'<break time="{break_ms}ms"/>')
        parts.append(f'<mark name="{mark_name(i)}"/>{escape(sentence)}')
    return f"<speak>{''.join(parts)}</speak>"


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "polly-samples")
    out_dir.mkdir(parents=True, exist_ok=True)

    client = boto3.client("polly", region_name="ap-northeast-1")
    sentences = split_sentences(SAMPLE)
    print(f"題材: {len(SAMPLE)} 文字 / {len(sentences)} 文\n")

    for voice in VOICES:
        synthesizer = SpeechSynthesizer(voice, client=client)

        # break なし（通常の合成）
        plain = synthesizer.synthesize(SAMPLE)
        (out_dir / f"{voice}_nobreak.mp3").write_bytes(plain.audio)

        # break あり（SSML を差し替えて合成）
        ssml = build_ssml_with_break(sentences, BREAK_MS)
        audio = synthesizer._request(ssml, "mp3")
        (out_dir / f"{voice}_break{BREAK_MS}.mp3").write_bytes(audio)

        starts = [s.start_ms for s in plain.sentences]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        print(f"{voice}")
        print(f"  各文の開始位置(ms): {starts}")
        print(f"  文ごとの長さ(ms)  : {gaps}")
        print()

    print(f"出力先: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
