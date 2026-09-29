"""API のリクエストとレスポンスの型。

フロントエンドとの約束事（API 契約）になる。FastAPI はこの型から入力の検証と
OpenAPI の仕様書（/docs）を自動で作るので、ここに書いた制約がそのまま
「API が受け付ける値」として公開される。
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.problem import Sentence
from app.schemas.scoring import SummaryResult, TranscriptionResult

Mode = Literal["transcription", "summary"]

# 問題 ID は uuid4 の 16 進 32 文字。形式の違う値はデータベースに問い合わせる前に弾く。
PROBLEM_ID_PATTERN = r"^[0-9a-f]{32}$"


# ---------------------------------------------------------------------------
# 作問
# ---------------------------------------------------------------------------


class CreateProblemRequest(BaseModel):
    """作問の依頼（要件 F1-1）。"""

    theme: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="何について話すか", examples=["IT 企業の株主総会で、社長が四半期の業績を報告する"]
    )
    target_length: int = Field(default=300, ge=50, le=500, description="目標文字数")
    info: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = Field(
        default="", description="追加の指示（任意）", examples=["専門用語を少し含める"]
    )
    mode: Mode = Field(default="transcription", description="採点モード")


class ProblemResponse(BaseModel):
    """問題。作問直後と再取得のどちらもこの形で返す。

    題材の全文も含める。音声を聞けば分かる情報であり、隠しても訓練上の意味がないため。
    """

    problem_id: str
    mode: Mode
    theme: str
    text: str = Field(description="題材の全文")
    sentences: list[Sentence] = Field(description="文ごとのテキストと、音声上の開始位置")
    duration_ms: int | None = Field(
        default=None, description="音声全体の長さ（ミリ秒）。音声を読み込む前に進行バーを描くため"
    )
    audio_url: str = Field(description="音声の署名付き URL。期限が切れたら問題を再取得すると新しい URL が得られる")
    audio_url_expires_at: datetime


# ---------------------------------------------------------------------------
# 採点
# ---------------------------------------------------------------------------


class SubmitAnswerRequest(BaseModel):
    """回答。どの問題への回答かは URL のパスで示す。"""

    user_input: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] = Field(
        description="書き取った文章、または要約"
    )


class AnswerResponse(BaseModel):
    """採点結果。モードに応じて transcription か summary の一方だけが入る。"""

    attempt_id: str
    problem_id: str
    mode: Mode
    source_text: str = Field(description="題材の全文（自分の入力と並べて確認するため。要件 F3-3）")
    user_input: str
    transcription: TranscriptionResult | None = None
    summary: SummaryResult | None = None


# ---------------------------------------------------------------------------
# サンプル問題
# ---------------------------------------------------------------------------


class SampleSummary(BaseModel):
    """サンプル問題の一覧に出す項目。本体は GET /api/problems/{problem_id} で取る。"""

    problem_id: str
    mode: Mode
    theme: str
    char_count: int = Field(description="題材の文字数")
    sentence_count: int
    duration_ms: int | None = Field(default=None, description="音声全体の長さ（ミリ秒）")


# ---------------------------------------------------------------------------
# 作問数の残り
# ---------------------------------------------------------------------------


class UsageCount(BaseModel):
    used: int
    limit: int
    remaining: int


class UsageStatus(BaseModel):
    """作問数の上限と使用数（要件 N2-3）。上限に達してから知るのではなく、先に見せる。"""

    daily: UsageCount
    monthly: UsageCount


# ---------------------------------------------------------------------------
# エラー
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str


class UsageLimitErrorResponse(ErrorResponse):
    scope: Literal["daily", "monthly"]
    limit: int
