"""題材を文に分割し、音声合成用の SSML を組み立てる。

Polly には音声本体とは別に「Speech Marks」を要求でき、SSML に埋めた
<mark> タグが音声上の何ミリ秒の位置にあたるかを返してもらえる。
各文の先頭に mark を置くことで、1 回の合成で文単位の再生制御ができる。
"""

from xml.sax.saxutils import escape

_SENTENCE_END = "。！？"
_OPENERS = "「『（(【〈《［["
_CLOSERS = "」』）)】〉》］]"

# 文ごとの mark 名。Speech Marks の応答と突き合わせるための識別子。
MARK_PREFIX = "s"

# 題材の末尾に置く mark。その位置が音声全体の長さになる。
END_MARK = "end"


def split_sentences(text: str) -> list[str]:
    """題材を句点（。！？）で文に分割する。

    括弧の内側にある句点では分割しない。会話の引用（彼は「了解です。」と答えた）を
    途中で切ってしまうと、文としても音声の区切りとしても不自然になるため、
    括弧の深さを数えながら走査する。

    連続した文末記号（！？）はひとまとまりとして扱い、直後に続く閉じ括弧は
    直前の文に含める。
    """
    if not text or not text.strip():
        return []

    sentences: list[str] = []
    depth = 0
    start = 0
    i = 0
    length = len(text)

    while i < length:
        char = text[i]

        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(0, depth - 1)
        elif char in _SENTENCE_END and depth == 0:
            end = i + 1
            while end < length and text[end] in _SENTENCE_END:
                end += 1
            # 括弧の対応が崩れている題材でも閉じ括弧が次の文頭に残らないようにする
            while end < length and text[end] in _CLOSERS:
                end += 1

            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = i = end
            continue

        i += 1

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return sentences


def mark_name(index: int) -> str:
    """文の番号から mark 名を作る。"""
    return f"{MARK_PREFIX}{index}"


def parse_mark_name(name: str) -> int | None:
    """mark 名から文の番号を取り出す。想定外の名前なら None。"""
    if not name.startswith(MARK_PREFIX):
        return None
    suffix = name[len(MARK_PREFIX) :]
    return int(suffix) if suffix.isdigit() else None


def build_ssml(sentences: list[str], break_ms: int = 0) -> str:
    """文のリストから、各文の先頭に <mark> を置いた SSML を組み立てる。

    題材は LLM の生成物なので、& や < がそのまま含まれると SSML が壊れる。
    必ずエスケープしてから埋め込む。

    break_ms を指定すると文の間に明示的な無音を入れる。句点区切りモードで
    文の終わりに停止したとき、余韻が無いまま切れるのを避けるためのもの。

    末尾には END_MARK を置く。Speech Marks でその位置を受け取れば、
    音声全体の長さが分かる（Polly は長さを直接は返さない）。
    """
    parts: list[str] = []
    for i, sentence in enumerate(sentences):
        if i > 0 and break_ms > 0:
            parts.append(f'<break time="{break_ms}ms"/>')
        parts.append(f'<mark name="{mark_name(i)}"/>{escape(sentence)}')
    if parts:
        parts.append(f'<mark name="{END_MARK}"/>')
    return f"<speak>{''.join(parts)}</speak>"
