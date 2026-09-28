"""題材（聞き取り練習用の話し言葉のモノローグ）の生成。"""

import re

from pydantic import BaseModel, Field, ValidationError

from app.services.bedrock import BedrockClient, LLMError

# 文字数は指示どおりにならないことがある。指定の 6〜15 割に収まっていれば
# 練習の題材として支障がないため受け入れ、外れた場合のみ一度だけ作り直す。
MIN_LENGTH_RATIO = 0.6
MAX_LENGTH_RATIO = 1.5
MAX_ATTEMPTS = 2

# 話し言葉のモノローグとして不適切な形を検出する
_SPEAKER_LABEL = re.compile(r"^\s*[^\s]{0,12}[：:]")
_BULLET = re.compile(r"[・*\-—]\s*\S+\n|^\s*[0-9０-９]+[.．)）]\s", re.MULTILINE)

TOOL_NAME = "submit_script"
TOOL_DESCRIPTION = "作成した聞き取り練習用の台本を提出する"
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "話し言葉のモノローグ本文。改行・話者名・箇条書きを含まない一続きの文章。",
        }
    },
    "required": ["text"],
}

SYSTEM = """あなたは、聞き取り訓練用の音声台本を作る専門家です。
作った台本は音声合成でそのまま読み上げられ、訓練者が耳で聞いて書き取ります。

守ること:
- 一人の話者が続けて話す、自然な話し言葉にする
- 改行を含めず、一続きの文章にする
- 話者名、括弧、箇条書き、見出しを含めない
- 数は算用数字で書く（例: 15%、120億円、第2四半期、2026年10月1日）。「一五」のように数字を 1 文字ずつ漢数字に置き換えない
- アルファベットと、% 以外の記号は使わない
- 文は「。」「！」「？」で終える"""


class GeneratedScript(BaseModel):
    """モデルが提出した台本。"""

    text: str = Field(min_length=1)


def _build_prompt(theme: str, target_length: int, info: str) -> str:
    extra = f"\n\n# 追加の指示\n{info.strip()}" if info and info.strip() else ""
    return f"""次の条件で台本を1つ作り、{TOOL_NAME} で提出してください。

# 内容
{theme.strip()}

# 長さ
およそ {target_length} 文字{extra}"""


def _reject_reason(text: str, target_length: int) -> str | None:
    """題材として使えない理由を返す。問題なければ None。"""
    if "\n" in text:
        return "改行が含まれています"
    if _SPEAKER_LABEL.match(text):
        return "話者名らしき記述で始まっています"
    if _BULLET.search(text):
        return "箇条書きが含まれています"
    if not text.rstrip().endswith(("。", "！", "？")):
        return "文末が句点で終わっていません"

    ratio = len(text) / target_length
    if ratio < MIN_LENGTH_RATIO:
        return f"指定より大幅に短いです（{len(text)}文字 / 目標{target_length}文字）"
    if ratio > MAX_LENGTH_RATIO:
        return f"指定より大幅に長いです（{len(text)}文字 / 目標{target_length}文字）"
    return None


def generate_script(
    client: BedrockClient, *, theme: str, target_length: int, info: str = ""
) -> str:
    """題材を生成する。条件を満たさない出力は一度だけ作り直す。"""
    prompt = _build_prompt(theme, target_length, info)
    last_reason = ""

    for attempt in range(MAX_ATTEMPTS):
        user = prompt if attempt == 0 else f"{prompt}\n\n# 前回の問題点\n{last_reason}"
        raw = client.invoke_tool(
            system=SYSTEM,
            user=user,
            tool_name=TOOL_NAME,
            tool_description=TOOL_DESCRIPTION,
            input_schema=INPUT_SCHEMA,
            # 日本語は 1 文字あたり概ね 1 トークン。指示より長く返る場合に備えて余裕を持たせる
            max_tokens=target_length * 3 + 200,
            temperature=1.0,  # 毎回同じ題材にならないよう、生成には揺らぎを残す
        )

        try:
            text = GeneratedScript.model_validate(raw).text.strip()
        except ValidationError as error:
            last_reason = f"提出された台本の形式が不正です: {error}"
            continue

        reason = _reject_reason(text, target_length)
        if reason is None:
            return text
        last_reason = reason

    raise LLMError(f"条件を満たす題材を生成できませんでした: {last_reason}")
