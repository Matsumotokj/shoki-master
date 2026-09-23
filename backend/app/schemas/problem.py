"""問題（題材と音声）のスキーマ。"""

from pydantic import BaseModel, Field


class Sentence(BaseModel):
    """題材を構成する 1 文と、その音声上の位置。"""

    index: int = Field(ge=0, description="先頭からの通し番号")
    text: str
    start_ms: int = Field(ge=0, description="音声のどのミリ秒から読み始めるか")
