import pytest

from app.services.bedrock import LLMError
from app.services.script_generation import generate_script

VALID = "本日はお忙しい中お集まりいただきありがとうございます。" * 3  # 81 文字


class FakeLLM:
    """invoke_tool の呼び出しを記録し、決めた台本を順に返す。"""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def invoke_tool(self, **kwargs):
        self.calls.append(kwargs)
        return self._payloads.pop(0) if self._payloads else {}


def generate(*payloads, target_length=80, **kwargs):
    llm = FakeLLM(*payloads)
    text = generate_script(llm, theme="株主総会の挨拶", target_length=target_length, **kwargs)
    return text, llm


class TestPrompt:
    def test_theme_and_length_are_in_the_prompt(self):
        _, llm = generate({"text": VALID}, target_length=80)
        user = llm.calls[0]["user"]
        assert "株主総会の挨拶" in user
        assert "80" in user

    def test_additional_instructions_are_included(self):
        _, llm = generate({"text": VALID}, info="専門用語を少し含める")
        assert "専門用語を少し含める" in llm.calls[0]["user"]

    def test_blank_instructions_are_omitted(self):
        _, llm = generate({"text": VALID}, info="   ")
        assert "追加の指示" not in llm.calls[0]["user"]

    def test_generation_uses_a_nonzero_temperature(self):
        # 同じテーマで毎回同じ題材が出ると練習にならない
        _, llm = generate({"text": VALID})
        assert llm.calls[0]["temperature"] > 0


class TestAcceptedOutput:
    def test_returns_the_generated_text(self):
        text, llm = generate({"text": VALID})
        assert text == VALID
        assert len(llm.calls) == 1

    def test_strips_surrounding_whitespace(self):
        text, _ = generate({"text": f"  {VALID}  "})
        assert text == VALID

    @pytest.mark.parametrize("ratio", [0.7, 1.0, 1.4])
    def test_length_within_tolerance_is_accepted(self, ratio):
        text = "あ" * (int(80 * ratio) - 1) + "。"
        result, llm = generate({"text": text}, target_length=80)
        assert result == text
        assert len(llm.calls) == 1


class TestRejectedOutput:
    def _expect_retry(self, bad_payload, **kwargs):
        text, llm = generate(bad_payload, {"text": VALID}, **kwargs)
        assert text == VALID
        assert len(llm.calls) == 2
        return llm

    def test_newline_triggers_a_retry(self):
        # 改行はモノローグとして不自然で、音声にも表示にも影響する
        self._expect_retry({"text": "本日は晴天です。\n明日は雨です。" + "あ" * 60 + "。"})

    def test_speaker_label_triggers_a_retry(self):
        self._expect_retry({"text": "話者1：" + "あ" * 76 + "。"})

    def test_missing_sentence_end_triggers_a_retry(self):
        self._expect_retry({"text": "あ" * 80})

    def test_too_short_triggers_a_retry(self):
        self._expect_retry({"text": "短い。"})

    def test_too_long_triggers_a_retry(self):
        self._expect_retry({"text": "あ" * 200 + "。"})

    def test_empty_text_triggers_a_retry(self):
        self._expect_retry({"text": ""})

    def test_missing_field_triggers_a_retry(self):
        self._expect_retry({})

    def test_retry_prompt_explains_the_problem(self):
        llm = self._expect_retry({"text": "短い。"})
        assert "前回の問題点" in llm.calls[1]["user"]
        assert "短い" in llm.calls[1]["user"]

    def test_gives_up_after_one_retry(self):
        # 作り直しを繰り返すと待ち時間も課金も増えるため、上限を設ける
        llm = FakeLLM({"text": "短い。"}, {"text": "まだ短い。"}, {"text": VALID})
        with pytest.raises(LLMError, match="生成できませんでした"):
            generate_script(llm, theme="テーマ", target_length=80)
        assert len(llm.calls) == 2
