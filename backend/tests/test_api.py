"""API 全体を通したテスト。

エンドポイント → ProblemService → 各部品、という本物の流れを通し、
外部サービスにあたる部品（Bedrock・Polly・S3・DynamoDB）だけを偽物に差し替える。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_problem_service
from app.main import app
from app.repositories.usage import UsageLimitExceeded
from app.schemas.problem import Sentence
from app.services.bedrock import LLMError
from app.services.problem_service import ProblemService
from app.services.script_segmentation import split_sentences
from app.services.speech import Synthesis

SCRIPT = "本日はお集まりいただきありがとうございます。" * 5  # 110 文字・5 文
REVIEW = {
    "faithfulness": 42,
    "coverage": 28,
    "clarity": 13,
    "hallucination": False,
    "notes": "忠実性42/50、網羅性28/35、明瞭13/15。",
    "best_summary": "集まりへの謝意を述べた。",
}


# ---------------------------------------------------------------------------
# 偽物の部品
# ---------------------------------------------------------------------------


class FakeLLM:
    def __init__(self):
        self.calls: list[str] = []
        self.error: Exception | None = None

    def invoke_tool(self, **kwargs) -> dict[str, Any]:
        self.calls.append(kwargs["tool_name"])
        if self.error:
            raise self.error
        return {"text": SCRIPT} if kwargs["tool_name"] == "submit_script" else REVIEW


class FakeSpeech:
    def synthesize(self, text: str) -> Synthesis:
        sentences = [
            Sentence(index=i, text=s, start_ms=i * 1000) for i, s in enumerate(split_sentences(text))
        ]
        return Synthesis(audio=b"mp3", sentences=sentences)


class FakeAudio:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.presigned = 0

    def put(self, problem_id: str, audio: bytes) -> str:
        key = f"audio/{problem_id}.mp3"
        self.objects[key] = audio
        return key

    def presigned_url(self, key: str, expires_in: int) -> str:
        self.presigned += 1
        return f"https://audio.example/{key}?n={self.presigned}"


class FakeRepo:
    def __init__(self):
        self.problems: dict[str, dict] = {}
        self.attempts: list[dict] = []

    def save_problem(self, **item) -> None:
        item["sentences"] = [s.model_dump() for s in item["sentences"]]
        self.problems[item["problem_id"]] = item

    def get_problem(self, problem_id: str) -> dict | None:
        return self.problems.get(problem_id)

    def save_attempt(self, **item) -> str:
        attempt_id = f"attempt-{len(self.attempts) + 1}"
        self.attempts.append({**item, "attempt_id": attempt_id})
        return attempt_id


class FakeUsage:
    def __init__(self, limit: int = 100):
        self.count = 0
        self.limit = limit

    def consume(self) -> None:
        if self.count >= self.limit:
            raise UsageLimitExceeded("daily", self.limit)
        self.count += 1


# ---------------------------------------------------------------------------


class Fakes:
    def __init__(self):
        self.llm = FakeLLM()
        self.audio = FakeAudio()
        self.repo = FakeRepo()
        self.usage = FakeUsage()
        self.service = ProblemService(
            llm=self.llm, speech=FakeSpeech(), audio=self.audio, repo=self.repo, usage=self.usage
        )


@pytest.fixture
def fakes():
    return Fakes()


@pytest.fixture
def client(fakes):
    app.dependency_overrides[get_problem_service] = lambda: fakes.service
    yield TestClient(app)
    app.dependency_overrides.clear()


def create(client, **overrides):
    body = {"theme": "株主総会の挨拶", "target_length": 100, "mode": "transcription"}
    body.update(overrides)
    return client.post("/api/problems", json=body)


# ---------------------------------------------------------------------------
# 作問
# ---------------------------------------------------------------------------


class TestCreateProblem:
    def test_returns_the_problem(self, client):
        response = create(client)
        assert response.status_code == 201
        body = response.json()
        assert len(body["problem_id"]) == 32
        assert body["text"] == SCRIPT
        assert len(body["sentences"]) == 5
        assert body["sentences"][1]["start_ms"] == 1000
        assert body["audio_url"].startswith("https://audio.example/audio/")
        assert "audio_url_expires_at" in body

    def test_saves_audio_and_problem(self, client, fakes):
        problem_id = create(client).json()["problem_id"]
        assert f"audio/{problem_id}.mp3" in fakes.audio.objects
        assert fakes.repo.problems[problem_id]["mode"] == "transcription"

    def test_trims_the_theme(self, client, fakes):
        problem_id = create(client, theme="  株主総会  ").json()["problem_id"]
        assert fakes.repo.problems[problem_id]["theme"] == "株主総会"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"theme": ""},
            {"theme": "   "},  # 空白だけは除去すると空になる
            {"theme": "あ" * 201},
            {"target_length": 49},
            {"target_length": 501},
            {"info": "あ" * 201},
            {"mode": "dictation"},
        ],
    )
    def test_rejects_invalid_requests_before_spending_anything(self, client, fakes, overrides):
        # 入力が不正なら、上限も Bedrock も消費しない
        assert create(client, **overrides).status_code == 422
        assert fakes.usage.count == 0
        assert fakes.llm.calls == []

    def test_usage_limit_returns_429_without_calling_bedrock(self, client, fakes):
        fakes.usage.limit = 0
        response = create(client)
        assert response.status_code == 429
        assert response.json() == {
            "detail": "本日の作問上限（0 問）に達しました",
            "scope": "daily",
            "limit": 0,
        }
        assert fakes.llm.calls == []

    def test_generation_failure_returns_502(self, client, fakes):
        fakes.llm.error = LLMError("model output was broken")
        response = create(client)
        assert response.status_code == 502
        # モデル側のエラー内容は利用者に見せない
        assert "model output" not in response.json()["detail"]

    def test_failed_generation_still_counts_against_the_limit(self, client, fakes):
        # 失敗しても Bedrock の料金は発生しているので、上限の歯止めから外さない
        fakes.llm.error = LLMError("boom")
        create(client)
        assert fakes.usage.count == 1


# ---------------------------------------------------------------------------
# 再取得
# ---------------------------------------------------------------------------


class TestGetProblem:
    def test_returns_the_saved_problem(self, client):
        created = create(client).json()
        response = client.get(f"/api/problems/{created['problem_id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["text"] == created["text"]
        assert body["sentences"] == created["sentences"]

    def test_issues_a_fresh_audio_url(self, client):
        # 署名付き URL は 1 時間で切れるので、再取得のたびに発行し直す
        created = create(client).json()
        again = client.get(f"/api/problems/{created['problem_id']}").json()
        assert again["audio_url"] != created["audio_url"]

    def test_unknown_problem_returns_404(self, client):
        response = client.get(f"/api/problems/{'0' * 32}")
        assert response.status_code == 404
        assert "1 日" in response.json()["detail"]

    @pytest.mark.parametrize("bad_id", ["abc", "0" * 31, "0" * 33, "G" * 32])
    def test_malformed_id_is_rejected_as_invalid_input(self, client, bad_id):
        # 形式の違う ID はデータベースに問い合わせる前に 422 で弾く
        assert client.get(f"/api/problems/{bad_id}").status_code == 422


# ---------------------------------------------------------------------------
# 採点
# ---------------------------------------------------------------------------


class TestSubmitAnswer:
    def test_transcription_is_scored_by_edit_distance(self, client, fakes):
        problem_id = create(client, mode="transcription").json()["problem_id"]
        response = client.post(f"/api/problems/{problem_id}/answers", json={"user_input": SCRIPT})
        assert response.status_code == 201
        body = response.json()
        assert body["mode"] == "transcription"
        assert body["transcription"]["accuracy"] == 100
        assert body["summary"] is None
        assert body["source_text"] == SCRIPT
        # 文字起こしの採点では Bedrock を呼ばない
        assert fakes.llm.calls == ["submit_script"]

    def test_summary_is_scored_by_the_llm(self, client, fakes):
        problem_id = create(client, mode="summary").json()["problem_id"]
        summary = "集まりへの謝意を述べた。" * 3
        response = client.post(f"/api/problems/{problem_id}/answers", json={"user_input": summary})
        assert response.status_code == 201
        body = response.json()
        assert body["mode"] == "summary"
        assert body["summary"]["score_raw"] == 42 + 28 + 13
        assert body["transcription"] is None
        assert fakes.llm.calls == ["submit_script", "submit_review"]

    def test_mode_comes_from_the_problem(self, client):
        # 要約の問題に回答すれば、要約として採点される（回答者はモードを選べない）
        problem_id = create(client, mode="summary").json()["problem_id"]
        body = client.post(
            f"/api/problems/{problem_id}/answers", json={"user_input": "まとめ" * 10}
        ).json()
        assert body["mode"] == "summary"

    def test_each_answer_is_saved_separately(self, client, fakes):
        # 同じ問題への再挑戦（要件 F3-4）
        problem_id = create(client).json()["problem_id"]
        for text in ("一回目", "二回目"):
            client.post(f"/api/problems/{problem_id}/answers", json={"user_input": text})
        assert [a["user_input"] for a in fakes.repo.attempts] == ["一回目", "二回目"]

    def test_answer_to_unknown_problem_returns_404(self, client):
        response = client.post(f"/api/problems/{'0' * 32}/answers", json={"user_input": "あ"})
        assert response.status_code == 404

    @pytest.mark.parametrize("user_input", ["", "   ", "あ" * 2001])
    def test_rejects_invalid_answers(self, client, user_input):
        problem_id = create(client).json()["problem_id"]
        response = client.post(
            f"/api/problems/{problem_id}/answers", json={"user_input": user_input}
        )
        assert response.status_code == 422

    def test_broken_characters_return_422_not_500(self, client):
        # UTF-8 として表せない文字（対になっていないサロゲート）が届いた場合。
        # 標準の 422 応答は入力をそのまま返そうとして 500 になっていた
        problem_id = create(client).json()["problem_id"]
        response = client.post(
            f"/api/problems/{problem_id}/answers",
            content=b'{"user_input": "\\udc86abc"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_validation_errors_do_not_echo_the_input(self, client):
        # 利用者の入力を応答に書き戻さない
        problem_id = create(client).json()["problem_id"]
        secret = "あ" * 2001
        response = client.post(f"/api/problems/{problem_id}/answers", json={"user_input": secret})
        assert response.status_code == 422
        assert secret not in response.text
        assert response.json()["detail"][0]["loc"] == ["body", "user_input"]

    def test_summary_scoring_failure_returns_502(self, client, fakes):
        problem_id = create(client, mode="summary").json()["problem_id"]
        fakes.llm.error = LLMError("boom")
        response = client.post(f"/api/problems/{problem_id}/answers", json={"user_input": "まとめ"})
        assert response.status_code == 502
        assert fakes.repo.attempts == []


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_openapi_lists_the_three_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) >= {
        "/api/problems",
        "/api/problems/{problem_id}",
        "/api/problems/{problem_id}/answers",
    }
