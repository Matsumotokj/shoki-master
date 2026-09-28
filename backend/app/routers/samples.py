"""サンプル問題の一覧（要件 F4-1）。

フロントの「すぐに試す」はここで ID を得て、通常の問題と同じく
GET /api/problems/{problem_id} で本体を取る。
"""

from fastapi import APIRouter

from app.samples import load_samples
from app.schemas.api import SampleSummary

router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.get("", summary="サンプル問題の一覧")
def list_samples() -> list[SampleSummary]:
    return [
        SampleSummary(problem_id=s.problem_id, mode=s.mode, theme=s.theme) for s in load_samples()
    ]
