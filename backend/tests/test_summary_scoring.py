import pytest

from app.schemas.scoring import SummarySubscores
from app.services.summary_scoring import (
    HALLUCINATION_SCORE_CAP,
    finalize_summary_score,
    length_penalty,
)

SOURCE = "あ" * 100


def make_subscores(faithfulness=40, coverage=28, clarity=12) -> SummarySubscores:
    return SummarySubscores(
        faithfulness=faithfulness, coverage=coverage, clarity=clarity
    )


class TestLengthPenalty:
    @pytest.mark.parametrize(
        ("summary_length", "expected_penalty"),
        [
            (10, -10),  # 10% : 短すぎ
            (20, -5),  # 20% : やや短い
            (30, 0),  # 30% : 適切
            (50, 0),  # 50% : 適切
            (70, -5),  # 70% : やや長い
            (90, -10),  # 90% : 長すぎ
        ],
    )
    def test_penalty_by_ratio(self, summary_length, expected_penalty):
        penalty, _ = length_penalty(SOURCE, "い" * summary_length)
        assert penalty == expected_penalty

    def test_reason_is_returned_with_penalty(self):
        penalty, reasons = length_penalty(SOURCE, "い" * 10)
        assert penalty < 0
        assert len(reasons) == 1

    def test_no_reason_when_appropriate(self):
        penalty, reasons = length_penalty(SOURCE, "い" * 40)
        assert penalty == 0
        assert reasons == []

    def test_boundary_25_percent_is_not_penalized(self):
        # 閾値ちょうどは「未満」ではないので減点しない
        assert length_penalty(SOURCE, "い" * 25)[0] == 0

    def test_boundary_60_percent_is_not_penalized(self):
        # 閾値ちょうどは「超過」ではないので減点しない
        assert length_penalty(SOURCE, "い" * 60)[0] == 0

    def test_empty_source_is_not_penalized(self):
        assert length_penalty("", "なにか")[0] == 0

    def test_empty_summary_is_penalized_as_too_short(self):
        penalty, _ = length_penalty(SOURCE, "")
        assert penalty == -10


class TestFinalizeSummaryScore:
    def _finalize(self, **overrides):
        kwargs = dict(
            source_text=SOURCE,
            summary="い" * 40,  # 減点のない長さ
            score_raw=80,
            subscores=make_subscores(),
            hallucination=False,
            notes="総評",
            best_summary="模範要約",
        )
        kwargs.update(overrides)
        return finalize_summary_score(**kwargs)

    def test_appropriate_length_keeps_raw_score(self):
        result = self._finalize()
        assert result.score == 80
        assert result.penalty == 0
        assert result.penalty_reasons == []

    def test_short_summary_is_penalized(self):
        result = self._finalize(summary="い" * 10)
        assert result.penalty == -10
        assert result.score == 70
        assert result.penalty_reasons

    def test_hallucination_caps_the_score(self):
        result = self._finalize(score_raw=95, hallucination=True)
        assert result.score == HALLUCINATION_SCORE_CAP
        assert result.hallucination is True

    def test_hallucination_does_not_raise_a_low_score(self):
        result = self._finalize(score_raw=40, hallucination=True)
        assert result.score == 40

    def test_score_never_goes_below_zero(self):
        result = self._finalize(score_raw=5, summary="い" * 5)
        assert result.score == 0

    def test_raw_score_is_preserved_for_display(self):
        result = self._finalize(score_raw=90, summary="い" * 10)
        assert result.score_raw == 90
        assert result.score == 80

    def test_subscores_pass_through(self):
        subscores = make_subscores(faithfulness=50, coverage=35, clarity=15)
        result = self._finalize(subscores=subscores)
        assert result.subscores.faithfulness == 50
        assert result.subscores.coverage == 35
        assert result.subscores.clarity == 15
