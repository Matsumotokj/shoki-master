"""問題に関するエンドポイント（要件定義書 §9）。

エンドポイントは入力を受けて ProblemService に渡すだけにする。
処理の順番や失敗時の扱いはサービス側、例外から状態コードへの対応は main.py に置く。

boto3 は処理が終わるまで待つ（非同期ではない）ので、関数は async def ではなく
def で書く。FastAPI は def の関数を別スレッドで動かすため、待っている間も
他のリクエストを受けられる。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.dependencies import get_problem_service
from app.schemas.api import (
    PROBLEM_ID_PATTERN,
    AnswerResponse,
    CreateProblemRequest,
    ErrorResponse,
    ProblemResponse,
    SubmitAnswerRequest,
    UsageLimitErrorResponse,
)
from app.services.problem_service import ProblemService

router = APIRouter(prefix="/api/problems", tags=["problems"])

Service = Annotated[ProblemService, Depends(get_problem_service)]
ProblemId = Annotated[str, Path(pattern=PROBLEM_ID_PATTERN, description="問題 ID（16 進 32 文字）")]


@router.post(
    "",
    status_code=201,
    summary="作問",
    responses={
        429: {"model": UsageLimitErrorResponse, "description": "作問数の上限に達した"},
        502: {"model": ErrorResponse, "description": "題材の生成に失敗した"},
    },
)
def create_problem(request: CreateProblemRequest, service: Service) -> ProblemResponse:
    return service.create_problem(request)


@router.get(
    "/{problem_id}",
    summary="問題の再取得",
    responses={404: {"model": ErrorResponse, "description": "問題が無い（1 日経つと消える）"}},
)
def get_problem(problem_id: ProblemId, service: Service) -> ProblemResponse:
    return service.get_problem(problem_id)


@router.post(
    "/{problem_id}/answers",
    status_code=201,
    summary="採点",
    responses={
        404: {"model": ErrorResponse, "description": "問題が無い"},
        502: {"model": ErrorResponse, "description": "要約の採点に失敗した"},
    },
)
def submit_answer(
    problem_id: ProblemId, request: SubmitAnswerRequest, service: Service
) -> AnswerResponse:
    return service.submit_answer(problem_id, request)
