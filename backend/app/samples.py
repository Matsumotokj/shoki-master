"""サンプル問題の定義（要件 F4）。

評価者が待たずに試せるよう、題材と音声を事前に用意しておく問題。
題材の文章は samples.json に置き、人が確認したものを Git で管理する。
音声と DynamoDB の項目は scripts/create_samples.py が作る（TTL なし、消えない）。

API は一覧を返すときに DynamoDB を読まない。サンプルの ID は決まっているので、
このファイルを読むだけで済み、LLM も音声合成も作問数の上限も使わない。
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.api import PROBLEM_ID_PATTERN, Mode

_SAMPLES_FILE = Path(__file__).with_name("samples.json")


class SampleProblem(BaseModel):
    problem_id: str = Field(pattern=PROBLEM_ID_PATTERN)
    mode: Mode
    theme: str
    text: str


def sample_audio_key(problem_id: str) -> str:
    """サンプルの音声の置き場所。audio/ と分けて、1 日で消すルールの対象外にする。"""
    return f"samples/{problem_id}.mp3"


@lru_cache
def load_samples() -> tuple[SampleProblem, ...]:
    raw = json.loads(_SAMPLES_FILE.read_text(encoding="utf-8"))
    return tuple(SampleProblem.model_validate(item) for item in raw)
