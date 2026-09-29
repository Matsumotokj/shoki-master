"""FastAPI アプリ本体と、Lambda から呼ばれる入口。

ローカル:  uvicorn app.main:app      （scripts/dev.py が接続先を設定して起動する）
Lambda  :  app.main.handler           （Mangum が API Gateway のイベントを変換する）
"""

import logging

from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.logging_config import configure_logging
from app.repositories.usage import UsageLimitExceeded
from app.routers import problems, samples, usage
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
app.include_router(samples.router)
app.include_router(usage.router)


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


_ACCESS_DENIED_CODES = {"AccessDeniedException", "AccessDenied"}


@app.exception_handler(ClientError)
def aws_client_error(request: Request, error: ClientError) -> JSONResponse:
    """AWS から「権限がない」と返されたときは、停止中として 503 を返す。

    月の予算を使い切ると、Budgets が実行ロールに Bedrock と Polly を拒否する
    ポリシーを付ける（要件 N2-3）。その間、作問と要約の採点はここに来る。
    文字起こしの採点は AWS を呼ばない計算だけなので、止まらずに使える。
    それ以外の AWS のエラーは想定外なので 500 とし、ログに残す。
    """
    code = error.response.get("Error", {}).get("Code", "")
    if code in _ACCESS_DENIED_CODES:
        logger.warning("aws access denied", extra={"path": request.url.path, "code": code})
        return JSONResponse(
            status_code=503,
            content={
                "detail": "作問と要約の採点を一時停止しています（今月の利用上限に達したため）。"
                "作成済みの問題での文字起こしの練習は引き続き使えます"
            },
        )
    logger.error("aws client error", extra={"path": request.url.path, "code": code}, exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "内部エラーが発生しました"})


# Lambda の入口。lifespan は使っていないので無効にする。
handler = Mangum(app, lifespan="off")
