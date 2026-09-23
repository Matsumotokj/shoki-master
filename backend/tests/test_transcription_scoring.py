import pytest

from app.services.transcription_scoring import (
    build_diff,
    grade_transcription,
    levenshtein_distance,
    normalize,
)


class TestNormalize:
    def test_removes_all_whitespace(self):
        assert normalize("本日は お忙しい中\n お集まり") == "本日はお忙しい中お集まり"

    def test_unifies_fullwidth_and_halfwidth(self):
        assert normalize("ＡＢＣ１２３") == "ABC123"
        assert normalize("ｶﾀｶﾅ") == "カタカナ"

    def test_keeps_punctuation(self):
        assert normalize("はい。そうです、確かに。") == "はい。そうです、確かに。"

    def test_distinguishes_hiragana_from_katakana(self):
        assert normalize("あい") != normalize("アイ")

    def test_empty(self):
        assert normalize("") == ""


class TestLevenshteinDistance:
    def test_identical(self):
        assert levenshtein_distance("本日は晴天なり", "本日は晴天なり") == 0

    def test_substitution(self):
        assert levenshtein_distance("本日は晴天", "本日わ晴天") == 1

    def test_deletion(self):
        assert levenshtein_distance("本日は晴天", "本日晴天") == 1

    def test_insertion(self):
        assert levenshtein_distance("本日晴天", "本日は晴天") == 1

    def test_empty_gold(self):
        assert levenshtein_distance("", "あいう") == 3

    def test_empty_typed(self):
        assert levenshtein_distance("あいう", "") == 3

    def test_both_empty(self):
        assert levenshtein_distance("", "") == 0

    def test_symmetric(self):
        a, b = "取り調べの記録", "取調べの記憶"
        assert levenshtein_distance(a, b) == levenshtein_distance(b, a)

    def test_transposition_costs_two(self):
        # 隣接の入れ替えは Levenshtein では置換 2 回ぶんになる（Damerau との違い）
        assert levenshtein_distance("あいう", "あうい") == 2


class TestBuildDiff:
    def test_identical_is_single_equal_segment(self):
        diff = build_diff("本日は晴天", "本日は晴天")
        assert [s.op for s in diff] == ["equal"]
        assert diff[0].gold == diff[0].typed == "本日は晴天"

    def test_replace_segment(self):
        diff = build_diff("本日は晴天", "本日わ晴天")
        replaced = [s for s in diff if s.op == "replace"]
        assert len(replaced) == 1
        assert replaced[0].gold == "は"
        assert replaced[0].typed == "わ"

    def test_delete_segment_has_empty_typed(self):
        diff = build_diff("本日は晴天", "本日晴天")
        deleted = [s for s in diff if s.op == "delete"]
        assert len(deleted) == 1
        assert deleted[0].gold == "は"
        assert deleted[0].typed == ""

    def test_insert_segment_has_empty_gold(self):
        diff = build_diff("本日晴天", "本日は晴天")
        inserted = [s for s in diff if s.op == "insert"]
        assert len(inserted) == 1
        assert inserted[0].gold == ""
        assert inserted[0].typed == "は"

    def test_segments_reconstruct_both_texts(self):
        gold, typed = "取り調べの記録を残す", "取調べの記憶を残した"
        diff = build_diff(gold, typed)
        assert "".join(s.gold for s in diff) == gold
        assert "".join(s.typed for s in diff) == typed


class TestGradeTranscription:
    def test_perfect_answer(self):
        result = grade_transcription("本日は晴天なり。", "本日は晴天なり。")
        assert result.accuracy == 100
        assert result.distance == 0
        assert result.length == 8

    def test_whitespace_only_difference_is_perfect(self):
        result = grade_transcription("本日は晴天なり。", "本日は 晴天なり。\n")
        assert result.accuracy == 100

    def test_one_mistake_in_ten_chars(self):
        result = grade_transcription("あいうえおかきくけこ", "あいうえおかきくけそ")
        assert result.distance == 1
        assert result.accuracy == 90

    def test_completely_wrong(self):
        result = grade_transcription("あいうえお", "かきくけこ")
        assert result.accuracy == 0

    def test_empty_input_scores_zero(self):
        result = grade_transcription("本日は晴天なり。", "")
        assert result.accuracy == 0
        assert result.distance == 8

    def test_excessively_long_input_floors_at_zero(self):
        result = grade_transcription("あい", "あい" + "う" * 100)
        assert result.accuracy == 0

    @pytest.mark.parametrize("user_input", ["", "なにか"])
    def test_empty_source(self, user_input):
        result = grade_transcription("", user_input)
        assert result.length == 0
        assert result.accuracy == (100 if not user_input else 0)

    def test_diff_is_included(self):
        result = grade_transcription("本日は晴天", "本日わ晴天")
        assert any(s.op == "replace" for s in result.diff)
