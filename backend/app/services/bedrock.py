"""Amazon Bedrock の呼び出し。

LLM の出力は形式が揺れる。自由文で JSON を書かせて後から解析するのではなく、
Converse API の tool use で JSON Schema を渡し、モデルにその形の引数を組み立て
させる。受け取った引数は必ず Pydantic で検証してからアプリに渡す。
"""

import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

# 日本国内で完結する推論プロファイル。機密性の高い業務を想定した題材であるため、
# アジア太平洋全域にまたがる apac.* ではなく jp.* を使う。
MODEL_ID = "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "ap-northeast-1"

# 一時的な過負荷で失敗したときだけ再試行する
_RETRYABLE_ERRORS = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}
_MAX_ATTEMPTS = 2
_RETRY_WAIT_SECONDS = 2.0


class LLMError(RuntimeError):
    """LLM から期待した形の応答を得られなかった。"""


class BedrockClient:
    """tool use による構造化出力に用途を絞った、Bedrock の薄いアダプタ。"""

    def __init__(self, client=None, model_id: str = MODEL_ID, region_name: str = REGION):
        self._client = client or boto3.client("bedrock-runtime", region_name=region_name)
        self._model_id = model_id

    def invoke_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """モデルに指定のツールを必ず呼ばせ、その引数を辞書で返す。"""
        request = {
            "modelId": self._model_id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool_name,
                            "description": tool_description,
                            "inputSchema": {"json": input_schema},
                        }
                    }
                ],
                # 「使っても使わなくてもよい」ではなく、このツールの呼び出しを強制する
                "toolChoice": {"tool": {"name": tool_name}},
            },
        }

        response = self._converse_with_retry(request)
        return self._extract_tool_input(response, tool_name)

    def _converse_with_retry(self, request: dict[str, Any]) -> dict[str, Any]:
        last_error: ClientError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._client.converse(**request)
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code", "")
                if code not in _RETRYABLE_ERRORS:
                    raise
                last_error = error
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_WAIT_SECONDS)
        raise LLMError(f"Bedrock の呼び出しに繰り返し失敗しました: {last_error}")

    @staticmethod
    def _extract_tool_input(response: dict[str, Any], tool_name: str) -> dict[str, Any]:
        """応答からツールの引数を取り出す。想定外の形なら例外にする。"""
        stop_reason = response.get("stopReason")
        if stop_reason == "max_tokens":
            # 引数が途中で切れており、形式が整っていても内容は信用できない
            raise LLMError("出力が長さの上限に達したため、応答が途中で切れました")

        content = response.get("output", {}).get("message", {}).get("content", [])
        for block in content:
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == tool_name:
                tool_input = tool_use.get("input")
                if not isinstance(tool_input, dict):
                    raise LLMError(f"ツール {tool_name} の引数が辞書ではありません")
                return tool_input

        raise LLMError(
            f"応答にツール {tool_name} の呼び出しが含まれていません (stopReason={stop_reason})"
        )
