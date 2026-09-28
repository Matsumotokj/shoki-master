"""FastAPI アプリ本体と、Lambda から呼ばれる入口。

ローカル:  uvicorn app.main:app      （scripts/dev.py が接続先を設定して起動する）
Lambda  :  app.main.handler           （Mangum が API Gateway のイベントを変換する）
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.logging_config import configure_logging
from app.repositories.usage import UsageLimitExceeded
from app.routers import problems
from app.services.bedrock import LLMError
from app.services.problem_service import ProblemNotFound

configure_logging()
logger = logging.getLogger("app")

app = FastAPI(
    title="書記マスター API",
    description="聞き取り・要約の訓練のための作問と採点",
    version="0.1.0",
)
app.include_router(problems.router)


@app.get("/api/health", tags=["health"], summary="死活確認")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 例外 → HTTP の状態コード
# サービス層は HTTP を知らない例外を投げ、ここで利用者向けの応答に変換する。
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    """入力の検証に失敗したときの 422。

    FastAPI の標準の応答は、受け取った値（input）をそのまま返す。
    利用者の入力を応答やログに書き戻すのは避けたいうえ、壊れた文字
    （UTF-8 として表せない文字）が含まれていると応答を作れずに 500 になる。
    どの項目がなぜ不正かだけを返す。
    """
    details = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


@app.exception_handler(UsageLimitExceeded)
def usage_limit_exceeded(request: Request, error: UsageLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": str(error), "scope": error.scope, "limit": error.limit},
    )


@app.exception_handler(ProblemNotFound)
def problem_not_found(request: Request, error: ProblemNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": "問題が見つかりません。作成から 1 日経つと削除されます"},
    )


@app.exception_handler(LLMError)
def llm_error(request: Request, error: LLMError) -> JSONResponse:
    # 詳細はログにだけ残し、利用者には再試行を促す。モデルの応答内容を画面に出さない。
    logger.warning("llm error", extra={"path": request.url.path, "error": str(error)})
    return JSONResponse(
        status_code=502,
        content={"detail": "文章の生成または採点に失敗しました。時間をおいて再度お試しください"},
    )


# Lambda の入口。lifespan は使っていないので無効にする。
handler = Mangum(app, lifespan="off")
