"""文字起こしモードの採点。

聞き取った文章と正解文を突き合わせ、正答率と差分を返す。
外部サービスに依存しない純粋なロジックなので、単体テストで担保する。
"""

import re
import unicodedata
from difflib import SequenceMatcher

from app.schemas.scoring import DiffSegment, TranscriptionResult

_WHITESPACE = re.compile(r"\s+")
# 3 桁ごとの区切りのカンマ（1,200 / 1,200,000）。「1,2,3」のような並びは対象外
_THOUSANDS_SEPARATOR = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def normalize(text: str) -> str:
    """採点前の正規化。

    聞いて区別できない違いは同じものとして扱い、聞いて区別できる違いは残す。

    同じとみなすもの:
    - 空白（聞き取りに空白の概念がない）
    - 全角と半角（NFKC で揃える。１５％ → 15%）
    - 「パーセント」と「%」（読み上げは同じ）
    - 桁区切りのカンマ（1,200 と 1200 は読み上げが同じ）

    区別するもの:
    - 句読点、ひらがなとカタカナ、漢字とかな（書記として正確に書き分ける訓練であるため）
    """
    if not text:
        return ""
    normalized = _WHITESPACE.sub("", unicodedata.normalize("NFKC", text))
    normalized = normalized.replace("パーセント", "%")
    return _THOUSANDS_SEPARATOR.sub("", normalized)


def levenshtein_distance(gold: str, typed: str) -> int:
    """挿入・削除・置換の 3 操作による編集距離。

    直前の 1 行だけを保持するローリング配列で計算するため、メモリは O(min(N, M))。
    差分表示には使わない（そちらは SequenceMatcher が担当）ので、距離だけ返す。
    """
    if gold == typed:
        return 0
    if not gold:
        return len(typed)
    if not typed:
        return len(gold)

    # 短い方を内側のループに置いて配列を小さくする
    if len(typed) < len(gold):
        gold, typed = typed, gold

    previous = list(range(len(gold) + 1))
    for i, typed_char in enumerate(typed, start=1):
        current = [i]
        for j, gold_char in enumerate(gold, start=1):
            current.append(
                min(
                    previous[j] + 1,  # 削除
                    current[j - 1] + 1,  # 挿入
                    previous[j - 1] + (gold_char != typed_char),  # 置換
                )
            )
        previous = current
    return previous[-1]


def build_diff(gold: str, typed: str) -> list[DiffSegment]:
    """正解文と入力文の差分を区間単位で組み立てる。"""
    matcher = SequenceMatcher(a=gold, b=typed, autojunk=False)
    return [
        DiffSegment(op=op, gold=gold[i1:i2], typed=typed[j1:j2])
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
    ]


def grade_transcription(source_text: str, user_input: str) -> TranscriptionResult:
    """正答率・編集距離・差分をまとめて返す。

    正答率は「正解文の長さのうち、何文字ぶん誤らなかったか」の割合。
    入力が正解文より極端に長い場合に負の値へ振れないよう 0 で下限を切る。
    """
    gold = normalize(source_text)
    typed = normalize(user_input)

    distance = levenshtein_distance(gold, typed)
    length = len(gold)
    if length == 0:
        accuracy = 100 if not typed else 0
    else:
        accuracy = max(0, round((length - distance) / length * 100))

    return TranscriptionResult(
        accuracy=accuracy,
        distance=distance,
        length=length,
        diff=build_diff(gold, typed),
    )
