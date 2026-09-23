"""採点結果のスキーマ。"""

from typing import Literal

from pydantic import BaseModel, Field

DiffOp = Literal["equal", "replace", "delete", "insert"]


class DiffSegment(BaseModel):
    """正解文と入力文の差分 1 区間。

    文字単位ではなく区間単位で返すことで、レスポンスを小さく保つ。
    - equal   : 一致（gold == typed）
    - replace : 書き換え（gold → typed）
    - delete  : 入力側で欠落（typed が空）
    - insert  : 入力側の余分（gold が空）
    """

    op: DiffOp
    gold: str = ""
    typed: str = ""


class TranscriptionResult(BaseModel):
    """文字起こしモードの採点結果。"""

    accuracy: int = Field(ge=0, le=100, description="正答率 (%)")
    distance: int = Field(ge=0, description="編集距離（誤り文字数）")
    length: int = Field(ge=0, description="正規化後の正解文の文字数")
    diff: list[DiffSegment]


class SummarySubscores(BaseModel):
    """要約モードの観点別スコア。"""

    faithfulness: int = Field(ge=0, le=50, description="忠実性")
    coverage: int = Field(ge=0, le=35, description="網羅性")
    clarity: int = Field(ge=0, le=15, description="明瞭・簡潔")


class SummaryResult(BaseModel):
    """要約モードの採点結果。"""

    score: int = Field(ge=0, le=100, description="最終スコア")
    score_raw: int = Field(ge=0, le=100, description="LLM の素点")
    penalty: int = Field(le=0, description="長さによる自動減点")
    hallucination: bool = Field(description="元文にない内容の付け足しがあるか")
    subscores: SummarySubscores
    penalty_reasons: list[str]
    notes: str = Field(description="採点理由の総評")
    best_summary: str = Field(description="模範要約")
