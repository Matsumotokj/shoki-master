"""要約モードの採点のうち、LLM に任せない部分。

LLM は観点別スコアとハルシネーション判定を返すが、要約の「長さが適切か」は
文字数を数えれば決まる決定的な要素なので、アプリ側で加点・減点する。
LLM 呼び出しから切り離しておくことで、この部分は単体テストで固定できる。
"""

from app.schemas.scoring import SummaryResult, SummarySubscores

# (元文に対する要約の長さの比がこの値未満なら, 減点, 理由)
# 上から順に評価し、最初に該当したものを適用する。
_TOO_SHORT_RULES: tuple[tuple[float, int, str], ...] = (
    (0.15, -10, "要約が短すぎます"),
    (0.25, -5, "要約がやや短いです"),
)

# (この値を超えたら, 減点, 理由)
_TOO_LONG_RULES: tuple[tuple[float, int, str], ...] = (
    (0.80, -10, "要約が長すぎます"),
    (0.60, -5, "要約がやや長いです"),
)

# 元文にない内容を付け足していた場合の上限点
HALLUCINATION_SCORE_CAP = 70


def length_penalty(source_text: str, summary: str) -> tuple[int, list[str]]:
    """要約の長さに応じた減点と、その理由を返す。

    要約は元文の 25〜60% 程度に収まっているのが望ましい、という前提を置く。
    短すぎれば情報が落ち、長すぎれば要約になっていないため。
    """
    if not source_text:
        return 0, []

    ratio = len(summary) / len(source_text)

    for threshold, penalty, reason in _TOO_SHORT_RULES:
        if ratio < threshold:
            return penalty, [reason]

    for threshold, penalty, reason in _TOO_LONG_RULES:
        if ratio > threshold:
            return penalty, [reason]

    return 0, []


def finalize_summary_score(
    *,
    source_text: str,
    summary: str,
    score_raw: int,
    subscores: SummarySubscores,
    hallucination: bool,
    notes: str,
    best_summary: str,
) -> SummaryResult:
    """LLM の素点に長さの減点とハルシネーション上限を適用し、最終スコアを決める。"""
    penalty, penalty_reasons = length_penalty(source_text, summary)

    cap = HALLUCINATION_SCORE_CAP if hallucination else 100
    score = max(0, min(cap, score_raw + penalty))

    return SummaryResult(
        score=score,
        score_raw=score_raw,
        penalty=penalty,
        hallucination=hallucination,
        subscores=subscores,
        penalty_reasons=penalty_reasons,
        notes=notes,
        best_summary=best_summary,
    )
