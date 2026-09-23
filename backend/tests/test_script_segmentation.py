import pytest

from app.services.script_segmentation import (
    build_ssml,
    mark_name,
    parse_mark_name,
    split_sentences,
)


class TestSplitSentences:
    def test_splits_on_kuten(self):
        assert split_sentences("本日は晴天です。明日は雨です。") == [
            "本日は晴天です。",
            "明日は雨です。",
        ]

    @pytest.mark.parametrize("mark", ["。", "！", "？"])
    def test_all_sentence_end_marks(self, mark):
        assert split_sentences(f"そうです{mark}はい{mark}") == [
            f"そうです{mark}",
            f"はい{mark}",
        ]

    def test_touten_does_not_split(self):
        assert split_sentences("はい、そうです。") == ["はい、そうです。"]

    def test_kuten_inside_quotes_does_not_split(self):
        # 引用の中の句点で切ると「彼は」と「と答えた」が分断されてしまう
        assert split_sentences("彼は「わかりました。」と答えた。") == [
            "彼は「わかりました。」と答えた。"
        ]

    def test_kuten_inside_parens_does_not_split(self):
        assert split_sentences("そうです（たぶん。）次に進みます。") == [
            "そうです（たぶん。）次に進みます。"
        ]

    def test_splits_between_quoted_sentences(self):
        assert split_sentences("彼は「了解です。」と答えた。私も頷いた。") == [
            "彼は「了解です。」と答えた。",
            "私も頷いた。",
        ]

    def test_unbalanced_closing_bracket_stays_with_previous_sentence(self):
        assert split_sentences("了解です。」次に進みます。") == [
            "了解です。」",
            "次に進みます。",
        ]

    def test_tail_without_sentence_end_is_kept(self):
        assert split_sentences("本日は晴天です。ところで") == [
            "本日は晴天です。",
            "ところで",
        ]

    def test_single_sentence_without_end_mark(self):
        assert split_sentences("句点のない文") == ["句点のない文"]

    def test_surrounding_whitespace_is_trimmed(self):
        assert split_sentences("  本日は晴天です。  明日は雨です。  ") == [
            "本日は晴天です。",
            "明日は雨です。",
        ]

    def test_consecutive_end_marks_are_one_sentence(self):
        assert split_sentences("本当ですか！？はい。") == ["本当ですか！？", "はい。"]

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_input(self, text):
        assert split_sentences(text) == []

    def test_no_empty_sentences_are_produced(self):
        assert all(s for s in split_sentences("あ。。。い。"))

    def test_concatenation_preserves_content(self):
        text = "第3四半期の売上は好調でした。特に法人向けが伸びています。以上です。"
        assert "".join(split_sentences(text)) == text


class TestMarkName:
    def test_round_trip(self):
        for i in (0, 1, 42):
            assert parse_mark_name(mark_name(i)) == i

    def test_unknown_name_returns_none(self):
        assert parse_mark_name("sentence") is None
        assert parse_mark_name("x0") is None
        assert parse_mark_name("s") is None


class TestBuildSsml:
    def test_wraps_in_speak_element(self):
        ssml = build_ssml(["本日は晴天です。"])
        assert ssml.startswith("<speak>")
        assert ssml.endswith("</speak>")

    def test_each_sentence_gets_a_mark(self):
        ssml = build_ssml(["一つ目。", "二つ目。", "三つ目。"])
        assert '<mark name="s0"/>' in ssml
        assert '<mark name="s1"/>' in ssml
        assert '<mark name="s2"/>' in ssml

    def test_mark_precedes_its_sentence(self):
        ssml = build_ssml(["一つ目。", "二つ目。"])
        assert ssml.index('<mark name="s0"/>') < ssml.index("一つ目。")
        assert ssml.index("一つ目。") < ssml.index('<mark name="s1"/>')

    def test_xml_special_characters_are_escaped(self):
        ssml = build_ssml(["A&B社は<重要>です。"])
        assert "&amp;" in ssml
        assert "&lt;重要&gt;" in ssml
        # 生の & や < が本文として残っていないこと
        assert "A&B" not in ssml
        assert "<重要>" not in ssml

    def test_escaping_does_not_break_our_own_tags(self):
        ssml = build_ssml(["A&B。"])
        assert '<mark name="s0"/>' in ssml

    def test_empty_list_produces_valid_ssml(self):
        assert build_ssml([]) == "<speak></speak>"

    def test_break_is_inserted_between_sentences(self):
        ssml = build_ssml(["一つ目。", "二つ目。", "三つ目。"], break_ms=350)
        assert ssml.count('<break time="350ms"/>') == 2

    def test_break_is_not_inserted_before_the_first_sentence(self):
        ssml = build_ssml(["一つ目。", "二つ目。"], break_ms=350)
        assert not ssml.startswith('<speak><break')

    def test_no_break_by_default(self):
        assert "<break" not in build_ssml(["一つ目。", "二つ目。"])

    def test_break_zero_inserts_nothing(self):
        assert "<break" not in build_ssml(["一つ目。", "二つ目。"], break_ms=0)

    def test_ssml_with_break_is_parseable(self):
        from xml.etree import ElementTree

        root = ElementTree.fromstring(build_ssml(["一つ目。", "二つ目。"], break_ms=350))
        assert [m.get("name") for m in root.findall("mark")] == ["s0", "s1"]
        assert [b.get("time") for b in root.findall("break")] == ["350ms"]

    def test_is_parseable_xml(self):
        from xml.etree import ElementTree

        ssml = build_ssml(split_sentences("A&B社の件です。「了解。」と伝えました。"))
        root = ElementTree.fromstring(ssml)
        assert root.tag == "speak"
        assert [m.get("name") for m in root.findall("mark")] == ["s0", "s1"]
