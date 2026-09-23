"""要約の評価のうち、LLM に任せる部分。

LLM には「観点ごとの点数」と「元文にない付け足しの有無」だけを答えさせる。
合計点の計算や長さによる減点はアプリ側で行う（summary_scoring）。
モデルが申告した合計を信用せず、観点別の点数から自分で足し合わせることで、
内訳と合計が食い違った結果を返さずに済む。
"""

from pydantic import BaseModel, Field, ValidationError

from app.schemas.scoring import SummarySubscores
from app.services.bedrock import BedrockClient, LLMError

MAX_SOURCE_CHARS = 2000
MAX_SUMMARY_CHARS = 800
MAX_NOTES_CHARS = 200
MAX_BEST_SUMMARY_CHARS = 120

TOOL_NAME = "submit_review"
TOOL_DESCRIPTION = "要約の評価結果を提出する"
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {
            "type": "integer",
            "minimum": 0,
            "maximum": 50,
            "description": "忠実性。元文にない主張・数値・固有名詞を付け足していないか。",
        },
        "coverage": {
            "type": "integer",
            "minimum": 0,
            "maximum": 35,
            "description": "網羅性。元文の重要点をどれだけ押さえているか。",
        },
        "clarity": {
            "type": "integer",
            "minimum": 0,
            "maximum": 15,
            "description": "明瞭・簡潔さ。冗長さや曖昧さが少ないか。",
        },
        "hallucination": {
            "type": "boolean",
            "description": "元文に根拠のない内容の付け足しがあるか。",
        },
        "notes": {
            "type": "string",
            "description": f"観点ごとの点数とその理由。{MAX_NOTES_CHARS}文字以内。",
        },
        "best_summary": {
            "type": "string",
            "description": f"元文の事実だけに基づく模範要約。{MAX_BEST_SUMMARY_CHARS}文字以内。",
        },
    },
    "required": ["faithfulness", "coverage", "clarity", "hallucination", "notes", "best_summary"],
}

SYSTEM = f"""あなたは日本語の要約を厳格に評価する採点者です。

観点と配点:
- 忠実性(0〜50): 元文にない主張・数値・固有名詞を付け足していないこと。明確な付け足しが1つでもあれば大きく減点する。
- 網羅性(0〜35): 元文の重要点のカバー率。主要な論点の取りこぼしは大きく減点する。
- 明瞭・簡潔(0〜15): 冗長表現や曖昧さが少なく、簡潔にまとまっているか。

採点の目安:
- 平均は80点前後。満点は稀。
- そこそこ書けていても、忠実性か網羅性に欠けるなら合計70点未満とする。

notes には観点ごとの点数と理由を簡潔に書く（{MAX_NOTES_CHARS}文字以内）。
best_summary は元文の事実に厳密に従って書く（{MAX_BEST_SUMMARY_CHARS}文字以内、捏造禁止）。"""


class Review(BaseModel):
    """モデルが提出した評価。範囲は tool のスキーマでも縛るが、ここでも検証する。"""

    faithfulness: int = Field(ge=0, le=50)
    coverage: int = Field(ge=0, le=35)
    clarity: int = Field(ge=0, le=15)
    hallucination: bool
    notes: str = ""
    best_summary: str = ""

    @property
    def subscores(self) -> SummarySubscores:
        return SummarySubscores(
            faithfulness=self.faithfulness, coverage=self.coverage, clarity=self.clarity
        )

    @property
    def score_raw(self) -> int:
        """観点別の点数の合計。モデルの申告ではなくアプリ側で計算する。"""
        return self.faithfulness + self.coverage + self.clarity


def review_summary(client: BedrockClient, *, source_text: str, summary: str) -> Review:
    """要約を評価する。返る値は必ず定義した範囲に収まっている。"""
    source = source_text.strip()[:MAX_SOURCE_CHARS]
    answer = summary.strip()[:MAX_SUMMARY_CHARS]
    if not source or not answer:
        raise ValueError("元文と要約の両方が必要です")

    raw = client.invoke_tool(
        system=SYSTEM,
        user=f"# 元文\n{source}\n\n# 要約\n{answer}",
        tool_name=TOOL_NAME,
        tool_description=TOOL_DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        max_tokens=1000,
        temperature=0.0,  # 同じ要約には同じ点数がつくようにする
    )

    try:
        review = Review.model_validate(raw)
    except ValidationError as error:
        raise LLMError(f"評価結果が想定した形式ではありません: {error}") from error

    # 文字数の上限はモデルへの指示でしかないため、超過分はここで確実に切る
    return review.model_copy(
        update={
            "notes": review.notes.strip()[:MAX_NOTES_CHARS],
            "best_summary": review.best_summary.strip()[:MAX_BEST_SUMMARY_CHARS],
        }
    )
