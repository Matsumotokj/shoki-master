import pytest

from app.services.bedrock import LLMError
from app.services.summary_review import (
    MAX_BEST_SUMMARY_CHARS,
    MAX_NOTES_CHARS,
    MAX_SOURCE_CHARS,
    MAX_SUMMARY_CHARS,
    review_summary,
)

GOOD = {
    "faithfulness": 42,
    "coverage": 28,
    "clarity": 13,
    "hallucination": False,
    "notes": "忠実性42/50、網羅性28/35、明瞭13/15。",
    "best_summary": "第三四半期は増収増益だった。",
}


class FakeLLM:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    def invoke_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self._payload


def review(payload=None, source="元の文章です。" * 10, summary="要約です。"):
    llm = FakeLLM(GOOD if payload is None else payload)
    return review_summary(llm, source_text=source, summary=summary), llm


class TestRequest:
    def test_source_and_summary_are_sent(self):
        _, llm = review(source="元の文章です。", summary="まとめ。")
        user = llm.calls[0]["user"]
        assert "元の文章です。" in user
        assert "まとめ。" in user

    def test_scoring_is_deterministic(self):
        # 同じ要約に毎回違う点数が付くと、利用者が採点を信用できない
        _, llm = review()
        assert llm.calls[0]["temperature"] == 0.0

    def test_long_source_is_truncated(self):
        _, llm = review(source="あ" * 5000 + "。")
        assert len(llm.calls[0]["user"]) < MAX_SOURCE_CHARS + 200

    def test_long_summary_is_truncated(self):
        _, llm = review(summary="い" * 3000)
        assert llm.calls[0]["user"].count("い") <= MAX_SUMMARY_CHARS

    @pytest.mark.parametrize(
        ("source", "summary"), [("", "要約"), ("元文", ""), ("  ", "要約")]
    )
    def test_missing_input_is_rejected_before_calling(self, source, summary):
        llm = FakeLLM(GOOD)
        with pytest.raises(ValueError):
            review_summary(llm, source_text=source, summary=summary)
        assert llm.calls == []


class TestResult:
    def test_passes_through_the_subscores(self):
        result, _ = review()
        assert result.subscores.faithfulness == 42
        assert result.subscores.coverage == 28
        assert result.subscores.clarity == 13

    def test_score_is_the_sum_of_the_subscores(self):
        # モデルが申告した合計ではなく内訳から計算するので、両者が食い違わない
        result, _ = review()
        assert result.score_raw == 42 + 28 + 13

    def test_hallucination_flag(self):
        result, _ = review({**GOOD, "hallucination": True})
        assert result.hallucination is True

    def test_notes_are_capped(self):
        result, _ = review({**GOOD, "notes": "長" * 500})
        assert len(result.notes) == MAX_NOTES_CHARS

    def test_best_summary_is_capped(self):
        result, _ = review({**GOOD, "best_summary": "要" * 500})
        assert len(result.best_summary) == MAX_BEST_SUMMARY_CHARS

    def test_perfect_and_zero_scores_are_valid(self):
        top, _ = review({**GOOD, "faithfulness": 50, "coverage": 35, "clarity": 15})
        assert top.score_raw == 100
        bottom, _ = review({**GOOD, "faithfulness": 0, "coverage": 0, "clarity": 0})
        assert bottom.score_raw == 0


class TestInvalidResult:
    @pytest.mark.parametrize(
        "broken",
        [
            {"faithfulness": 60},  # 配点の上限を超える
            {"coverage": -1},  # 負の点
            {"clarity": 16},  # 配点の上限を超える
            {"faithfulness": "たくさん"},  # 数値として読めない
            {"hallucination": "たぶん"},  # 真偽値として読めない
        ],
    )
    def test_out_of_range_values_are_rejected(self, broken):
        # 配点を外れた値をそのまま通すと、100 点満点でない結果が表示される
        with pytest.raises(LLMError, match="形式"):
            review({**GOOD, **broken})

    def test_missing_field_is_rejected(self):
        payload = {k: v for k, v in GOOD.items() if k != "faithfulness"}
        with pytest.raises(LLMError):
            review(payload)

    @pytest.mark.parametrize(
        ("raw", "expected"), [("yes", True), ("false", False), (1, True), ("42", 42)]
    )
    def test_unambiguous_values_are_accepted(self, raw, expected):
        # 意味が一意に決まる表記の揺れは受け入れる。拒否しても利用者にエラーが出るだけで、
        # 守りたいのは型そのものではなく配点の範囲であるため。
        key = "faithfulness" if isinstance(expected, int) and expected > 1 else "hallucination"
        result, _ = review({**GOOD, key: raw})
        assert getattr(result, key) == expected
