import pytest
from botocore.exceptions import ClientError

from app.services.bedrock import BedrockClient, LLMError


def tool_use_response(tool_name: str, payload: dict, stop_reason: str = "tool_use") -> dict:
    return {
        "stopReason": stop_reason,
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "t1", "name": tool_name, "input": payload}}],
            }
        },
    }


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Converse")


class FakeBedrockClient:
    """converse の呼び出しを記録し、決めた応答か例外を返す。"""

    def __init__(self, responses=None, errors=None):
        self._responses = list(responses or [])
        self._errors = list(errors or [])
        self.calls: list[dict] = []

    def converse(self, **request):
        self.calls.append(request)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        return self._responses.pop(0) if self._responses else {}


def invoke(client, **overrides):
    params = dict(
        system="システム指示",
        user="お願い",
        tool_name="submit",
        tool_description="提出する",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        max_tokens=100,
        temperature=0.0,
    )
    params.update(overrides)
    return BedrockClient(client=client).invoke_tool(**params)


class TestRequestShape:
    def test_forces_the_tool_to_be_called(self):
        # ツールを「使ってもよい」ではなく「必ず使う」設定でないと自由文が返りうる
        fake = FakeBedrockClient([tool_use_response("submit", {"text": "本文"})])
        invoke(fake)
        assert fake.calls[0]["toolConfig"]["toolChoice"] == {"tool": {"name": "submit"}}

    def test_passes_schema_system_and_user(self):
        fake = FakeBedrockClient([tool_use_response("submit", {"text": "本文"})])
        invoke(fake)
        request = fake.calls[0]
        tool_spec = request["toolConfig"]["tools"][0]["toolSpec"]
        assert tool_spec["name"] == "submit"
        assert tool_spec["inputSchema"]["json"]["type"] == "object"
        assert request["system"] == [{"text": "システム指示"}]
        assert request["messages"][0]["content"][0]["text"] == "お願い"

    def test_passes_inference_config(self):
        fake = FakeBedrockClient([tool_use_response("submit", {"text": "本文"})])
        invoke(fake, max_tokens=512, temperature=1.0)
        assert fake.calls[0]["inferenceConfig"] == {"maxTokens": 512, "temperature": 1.0}

    def test_uses_the_japan_resident_inference_profile(self):
        # 機密性の高い業務を想定した題材のため、国内完結のプロファイルを使う
        fake = FakeBedrockClient([tool_use_response("submit", {"text": "本文"})])
        invoke(fake)
        assert fake.calls[0]["modelId"].startswith("jp.")


class TestResponseHandling:
    def test_returns_the_tool_input(self):
        fake = FakeBedrockClient([tool_use_response("submit", {"text": "本文です。"})])
        assert invoke(fake) == {"text": "本文です。"}

    def test_picks_the_expected_tool_from_several_blocks(self):
        response = tool_use_response("submit", {"text": "本文"})
        response["output"]["message"]["content"].insert(0, {"text": "考えています"})
        assert invoke(FakeBedrockClient([response])) == {"text": "本文"}

    def test_missing_tool_use_is_an_error(self):
        response = {"stopReason": "end_turn", "output": {"message": {"content": [{"text": "はい"}]}}}
        with pytest.raises(LLMError, match="含まれていません"):
            invoke(FakeBedrockClient([response]))

    def test_truncated_output_is_an_error(self):
        # 途中で切れた引数は形式が整っていても内容を信用できない
        response = tool_use_response("submit", {"text": "途中まで"}, stop_reason="max_tokens")
        with pytest.raises(LLMError, match="途中で切れ"):
            invoke(FakeBedrockClient([response]))

    def test_non_dict_input_is_an_error(self):
        response = tool_use_response("submit", "文字列")
        with pytest.raises(LLMError, match="辞書ではありません"):
            invoke(FakeBedrockClient([response]))

    def test_other_tool_name_is_ignored(self):
        response = tool_use_response("something_else", {"text": "本文"})
        with pytest.raises(LLMError):
            invoke(FakeBedrockClient([response]))


class TestRetry:
    def test_retries_once_on_throttling(self):
        fake = FakeBedrockClient(
            responses=[tool_use_response("submit", {"text": "本文"})],
            errors=[client_error("ThrottlingException"), None],
        )
        assert invoke(fake) == {"text": "本文"}
        assert len(fake.calls) == 2

    def test_gives_up_after_the_retry(self):
        fake = FakeBedrockClient(
            errors=[client_error("ThrottlingException"), client_error("ThrottlingException")]
        )
        with pytest.raises(LLMError, match="繰り返し失敗"):
            invoke(fake)
        assert len(fake.calls) == 2

    def test_does_not_retry_other_errors(self):
        # 権限エラーや不正リクエストを再試行しても課金が増えるだけで解決しない
        fake = FakeBedrockClient(errors=[client_error("AccessDeniedException")])
        with pytest.raises(ClientError):
            invoke(fake)
        assert len(fake.calls) == 1

    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr("app.services.bedrock.time.sleep", lambda _: None)
