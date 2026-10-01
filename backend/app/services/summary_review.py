"""要約の評価のうち、LLM に任せる部分。

LLM には「観点ごとの点数」と「元文にない付け足しの有無」だけを答えさせる。
合計点の計算や長さによる減点はアプリ側で行う（summary_scoring）。
モデルが申告した合計を信用せず、観点別の点数から自分で足し合わせることで、
内訳と合計が食い違った結果を返さずに済む。
"""

import math

from pydantic import BaseModel, Field, ValidationError

from app.schemas.scoring import SummarySubscores
from app.services.bedrock import BedrockClient, LLMError

MAX_SOURCE_CHARS = 2000
# 元文は最大 750 字（目標 500 字の 1.5 倍）なので、800 字を超える要約は元文より長く、
# 長さの減点（−10）が確定している。それ以上を読ませても採点は変わらず、費用だけが増える。
# 長さの減点は切る前の全文で計算する（summary_scoring）
MAX_SUMMARY_CHARS = 800
MAX_NOTES_CHARS = 200

# 模範要約の長さ。利用者に求める長さ（元文の 25〜60%。summary_scoring）の中ほどにする。
# 上限は「求める長さ」の上端。文の途中で切れないよう、目安より余裕を持たせる
BEST_SUMMARY_RATIO = 0.4
BEST_SUMMARY_MAX_RATIO = 0.6

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
            "description": "元文の事実だけに基づく模範要約。長さは依頼文の指定に従う。",
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
best_summary は元文の事実に厳密に従って書く（長さは依頼文の指定に従う。捏造禁止）。"""


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


def best_summary_length(source_length: int) -> tuple[int, int]:
    """模範要約の (目安の字数, 上限の字数)。"""
    return round(source_length * BEST_SUMMARY_RATIO), math.floor(source_length * BEST_SUMMARY_MAX_RATIO)


def review_summary(client: BedrockClient, *, source_text: str, summary: str) -> Review:
    """要約を評価する。返る値は必ず定義した範囲に収まっている。"""
    source = source_text.strip()[:MAX_SOURCE_CHARS]
    answer = summary.strip()[:MAX_SUMMARY_CHARS]
    if not source or not answer:
        raise ValueError("元文と要約の両方が必要です")
    target, max_best = best_summary_length(len(source))

    raw = client.invoke_tool(
        system=SYSTEM,
        user=(
            f"# 元文\n{source}\n\n# 要約\n{answer}\n\n"
            f"# 模範要約の長さ\n{target}文字前後（{max_best}文字以内）"
        ),
        tool_name=TOOL_NAME,
        tool_description=TOOL_DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        # 日本語は 1 字あたり概ね 1 トークン。点数・講評の分に、模範要約の上限を足す
        max_tokens=1000 + max_best,
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
            "best_summary": review.best_summary.strip()[:max_best],
        }
    )
