"""文字起こしモードの採点。

聞き取った文章と正解文を突き合わせ、正答率と差分を返す。
外部サービスに依存しない純粋なロジックなので、単体テストで担保する。
"""

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.schemas.scoring import DiffSegment, TranscriptionResult

# 句読点。半角の「｡」「､」も NFKC でこれになる
_PUNCTUATION = {"。", "、"}
_PERCENT = "パーセント"
_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_LARGE_UNITS = {"万": 10**4, "億": 10**8, "兆": 10**12}
_KANJI_NUMERALS = _KANJI_DIGITS.keys() | _SMALL_UNITS.keys() | _LARGE_UNITS.keys()


@dataclass(frozen=True)
class Normalized:
    """比べるための文字列と、その各文字が元の文字列のどこから来たか。

    比べるときは正規化した text を使い、利用者に見せるときは元の文字列を使う。
    正規化で「一緒」が「1緒」になっても、表示は元の「一緒」のままにできる。
    """

    text: str
    source: str
    starts: tuple[int, ...]  # text[k] の元になった文字の、source での位置

    def original(self, start: int, end: int) -> str:
        """text の範囲 [start, end) にあたる、元の文字列の部分。

        正規化で消した文字（空白・句読点）は、直前の文字の側に含める。
        """
        return self.source[self._boundary(start) : self._boundary(end)]

    def _boundary(self, index: int) -> int:
        if index >= len(self.starts):
            return len(self.source)
        return 0 if index == 0 else self.starts[index]


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_numeral(char: str) -> bool:
    return _is_digit(char) or char in _KANJI_NUMERALS


def _is_thousands_separator(chars: list[tuple[str, int]], k: int) -> bool:
    """3 桁ごとの区切りのカンマか（1,200 / 1,200,000）。「1,2,3」のような並びは対象外。"""
    if chars[k][0] != "," or k == 0 or not _is_digit(chars[k - 1][0]):
        return False
    following = [c for c, _ in chars[k + 1 : k + 5]]
    return len(following) >= 3 and all(map(_is_digit, following[:3])) and not (
        len(following) == 4 and _is_digit(following[3])
    )


def _parse_number(numeral: str) -> int:
    """漢数字（算用数字が混じってもよい）を数にする。

    二〇二六 → 2026、百二十億 → 12000000000、1万2000 → 12000。
    数字が並んだら桁として続け、十・百・千はその位、万・億・兆はそこまでをまとめる。
    """
    total = section = current = 0
    for char in numeral:
        if _is_digit(char):
            current = current * 10 + int(char)
        elif char in _KANJI_DIGITS:
            current = current * 10 + _KANJI_DIGITS[char]
        elif char in _SMALL_UNITS:
            section += (current or 1) * _SMALL_UNITS[char]
            current = 0
        else:
            total += (section + current or 1) * _LARGE_UNITS[char]
            section = current = 0
    return total + section + current


def normalize_with_source(text: str) -> Normalized:
    """採点前の正規化。聞いて区別できない違いは同じものとして扱い、聞いて区別できる違いは残す。

    同じとみなすもの:
    - 空白（聞き取りに空白の概念がない）
    - 全角と半角（NFKC で揃える。１５％ → 15%）
    - 「パーセント」と「%」（読み上げは同じ）
    - 桁区切りのカンマ（1,200 と 1200 は読み上げが同じ）
    - 漢数字と算用数字（午後五時と午後5時、百二十億と120億は読み上げが同じ）
    - 句読点の有無（どこで区切るかは書き手によって揺れ、聞き取りの正確さとは別のため）

    区別するもの:
    - ひらがなとカタカナ、漢字とかな（書記として正確に書き分ける訓練であるため）

    漢数字は正解と入力の両方で直すので、「一緒」のような言葉も両方で同じく「1緒」になり、
    比べた結果は変わらない（表示には元の文字列を使う）。
    """
    # 1 文字ずつ NFKC にかけ、元の位置を覚えておく（NFKC は 1 文字を複数に展開することがある）
    chars = [(c, i) for i, original in enumerate(text) for c in unicodedata.normalize("NFKC", original)]
    out: list[str] = []
    starts: list[int] = []

    k = 0
    while k < len(chars):
        char, position = chars[k]
        if char.isspace() or char in _PUNCTUATION:
            k += 1
        elif "".join(c for c, _ in chars[k : k + len(_PERCENT)]) == _PERCENT:
            out.append("%")
            starts.append(position)
            k += len(_PERCENT)
        elif _is_numeral(char):
            run = []
            while k < len(chars) and (_is_numeral(chars[k][0]) or _is_thousands_separator(chars, k)):
                if chars[k][0] != ",":
                    run.append(chars[k])
                k += 1
            if any(c in _KANJI_NUMERALS for c, _ in run):
                # 漢数字を含む数は、まとめて算用数字に直す（元の位置は数の先頭）
                digits = str(_parse_number("".join(c for c, _ in run)))
                out.extend(digits)
                starts.extend([run[0][1]] * len(digits))
            else:
                out.extend(c for c, _ in run)
                starts.extend(p for _, p in run)
        else:
            out.append(char)
            starts.append(position)
            k += 1

    return Normalized(text="".join(out), source=text, starts=tuple(starts))


def normalize(text: str) -> str:
    """比べるための文字列だけを返す。"""
    return normalize_with_source(text).text


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


def build_diff(source_text: str, user_input: str) -> list[DiffSegment]:
    """正解文と入力文の差分を区間単位で組み立てる。"""
    return _diff(normalize_with_source(source_text), normalize_with_source(user_input))


def _diff(gold: Normalized, typed: Normalized) -> list[DiffSegment]:
    """正規化した文字列どうしで比べ、各区間には元の文字列を入れる。"""
    matcher = SequenceMatcher(a=gold.text, b=typed.text, autojunk=False)
    return [
        DiffSegment(op=op, gold=gold.original(i1, i2), typed=typed.original(j1, j2))
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
    ]


def grade_transcription(source_text: str, user_input: str) -> TranscriptionResult:
    """正答率・編集距離・差分をまとめて返す。

    正答率は「正解文の長さのうち、何文字ぶん誤らなかったか」の割合。
    入力が正解文より極端に長い場合に負の値へ振れないよう 0 で下限を切る。
    """
    gold = normalize_with_source(source_text)
    typed = normalize_with_source(user_input)

    distance = levenshtein_distance(gold.text, typed.text)
    length = len(gold.text)
    if length == 0:
        accuracy = 100 if not typed.text else 0
    else:
        accuracy = max(0, round((length - distance) / length * 100))

    return TranscriptionResult(
        accuracy=accuracy,
        distance=distance,
        length=length,
        diff=_diff(gold, typed),
    )
