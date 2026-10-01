"""部品をつないで、作問・再取得・採点の一連の処理にする。

個々の部品（題材生成・音声合成・保存・採点）は外部サービスとのやりとりや
計算だけを受け持ち、「どの順で呼ぶか」「失敗したらどうするか」はここに集める。
部品は外から渡す（依存性の注入）ので、テストでは偽物に差し替えられる。
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app import config
from app.repositories.audio import AudioStorage
from app.repositories.problems import ProblemRepository, new_problem_id
from app.repositories.usage import UsageLimiter
from app.schemas.api import (
    AnswerResponse,
    CreateProblemRequest,
    ProblemResponse,
    SubmitAnswerRequest,
    UsageCount,
    UsageStatus,
)
from app.schemas.problem import Sentence
from app.services.bedrock import BedrockClient
from app.services.script_generation import generate_script
from app.services.speech import SpeechSynthesizer
from app.services.summary_review import review_summary
from app.services.summary_scoring import finalize_summary_score
from app.services.transcription_scoring import grade_transcription

logger = logging.getLogger(__name__)


class ProblemNotFound(LookupError):
    """問題が存在しない（ID の誤り、または 1 日経って消えた）。"""


class _Stopwatch:
    """処理ごとの所要時間を記録する。作問が API Gateway の 29 秒に収まるかを見るため。"""

    def __init__(self):
        self._last = time.perf_counter()
        self.laps: dict[str, int] = {}

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self._last) * 1000)
        self._last = now

    @property
    def total_ms(self) -> int:
        return sum(self.laps.values())


@dataclass
class ProblemService:
    llm: BedrockClient
    speech: SpeechSynthesizer
    audio: AudioStorage
    repo: ProblemRepository
    usage: UsageLimiter
    review_usage: UsageLimiter

    # -----------------------------------------------------------------------
    # 作問
    # -----------------------------------------------------------------------

    def create_problem(self, request: CreateProblemRequest) -> ProblemResponse:
        """題材を生成し、音声にして保存する。

        上限は題材生成の「前」に消費する。生成や音声合成が途中で失敗しても
        Bedrock・Polly の料金は発生しているので、失敗した作問も数えないと
        費用の歯止めにならない（要件 N2-3）。上限を超えていれば
        UsageLimitExceeded がそのまま呼び出し元へ伝わる。
        """
        watch = _Stopwatch()

        self.usage.consume()
        watch.lap("usage")

        text = generate_script(
            self.llm, theme=request.theme, target_length=request.target_length, info=request.info
        )
        watch.lap("generate")

        synthesis = self.speech.synthesize(text)
        watch.lap("synthesize")

        problem_id = new_problem_id()
        audio_key = self.audio.put(problem_id, synthesis.audio)
        watch.lap("put_audio")

        self.repo.save_problem(
            problem_id=problem_id,
            mode=request.mode,
            theme=request.theme,
            target_length=request.target_length,
            info=request.info,
            text=text,
            sentences=synthesis.sentences,
            audio_key=audio_key,
            duration_ms=synthesis.duration_ms,
        )
        watch.lap("save")

        logger.info(
            "problem created",
            extra={"problem_id": problem_id, "chars": len(text), "total_ms": watch.total_ms, **watch.laps},
        )
        return self._to_response(
            problem_id=problem_id,
            mode=request.mode,
            theme=request.theme,
            text=text,
            sentences=synthesis.sentences,
            audio_key=audio_key,
            duration_ms=synthesis.duration_ms,
        )

    # -----------------------------------------------------------------------
    # 再取得
    # -----------------------------------------------------------------------

    def get_problem(self, problem_id: str) -> ProblemResponse:
        """保存済みの問題を返す。音声の署名付き URL はその場で発行し直す。"""
        item = self._load(problem_id)
        return self._to_response(
            problem_id=problem_id,
            mode=item["mode"],
            theme=item["theme"],
            text=item["text"],
            sentences=[Sentence.model_validate(s) for s in item["sentences"]],
            audio_key=item["audio_key"],
            duration_ms=item.get("duration_ms"),
        )

    # -----------------------------------------------------------------------
    # 作問数の残り
    # -----------------------------------------------------------------------

    def usage_status(self) -> UsageStatus:
        status = self.usage.status()
        return UsageStatus(
            daily=UsageCount(**status["daily"]), monthly=UsageCount(**status["monthly"])
        )

    # -----------------------------------------------------------------------
    # 採点
    # -----------------------------------------------------------------------

    def submit_answer(self, problem_id: str, request: SubmitAnswerRequest) -> AnswerResponse:
        """モードに応じて採点し、回答を保存する。

        モードは問題の側に保存されているものを使う。回答者に選ばせると、
        要約の問題を文字起こしとして採点させるといった食い違いが起きる。

        要約の採点は Bedrock を呼ぶ前に回数の上限を消費する（作問と同じく、
        失敗しても料金は発生しているため）。文字起こしの採点は計算だけなので数えない。
        """
        item = self._load(problem_id)
        source_text: str = item["text"]
        mode = item["mode"]
        user_input = request.user_input

        watch = _Stopwatch()
        transcription = summary = None
        if mode == "transcription":
            transcription = grade_transcription(source_text, user_input)
            result = transcription.model_dump()
        else:
            self.review_usage.consume()
            review = review_summary(self.llm, source_text=source_text, summary=user_input)
            summary = finalize_summary_score(
                source_text=source_text,
                summary=user_input,
                score_raw=review.score_raw,
                subscores=review.subscores,
                hallucination=review.hallucination,
                notes=review.notes,
                best_summary=review.best_summary,
            )
            result = summary.model_dump()
        watch.lap("score")

        attempt_id = self.repo.save_attempt(
            problem_id=problem_id, mode=mode, user_input=user_input, result=result
        )
        watch.lap("save")

        logger.info(
            "answer scored",
            extra={"problem_id": problem_id, "mode": mode, "total_ms": watch.total_ms, **watch.laps},
        )
        return AnswerResponse(
            attempt_id=attempt_id,
            problem_id=problem_id,
            mode=mode,
            source_text=source_text,
            user_input=user_input,
            transcription=transcription,
            summary=summary,
        )

    # -----------------------------------------------------------------------

    def _load(self, problem_id: str) -> dict[str, Any]:
        item = self.repo.get_problem(problem_id)
        if item is None:
            raise ProblemNotFound(problem_id)
        return item

    def _to_response(
        self,
        *,
        problem_id: str,
        mode: str,
        theme: str,
        text: str,
        sentences: list[Sentence],
        audio_key: str,
        duration_ms: int | None,
    ) -> ProblemResponse:
        expires_in = config.AUDIO_URL_EXPIRES_SECONDS
        return ProblemResponse(
            problem_id=problem_id,
            mode=mode,
            theme=theme,
            text=text,
            sentences=sentences,
            duration_ms=duration_ms,
            audio_url=self.audio.presigned_url(audio_key, expires_in=expires_in),
            audio_url_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        )
