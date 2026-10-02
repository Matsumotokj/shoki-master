"""CloudFront を通らない直接アクセスの拒否（API Gateway の URL を直接呼ばれた場合）。"""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.dependencies import get_problem_service
from app.main import app

SECRET = "0123abcd" * 8


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def behind_cloudfront(monkeypatch):
    """Lambda 上と同じく、合言葉が設定されている状態。"""
    monkeypatch.setattr(config, "ORIGIN_VERIFY_SECRET", SECRET)


def test_request_through_cloudfront_is_accepted(client, behind_cloudfront):
    response = client.get("/api/health", headers={"X-Origin-Verify": SECRET})
    assert response.status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-Origin-Verify": ""}, {"X-Origin-Verify": "wrong"}])
def test_direct_request_is_rejected(client, behind_cloudfront, headers):
    response = client.get("/api/health", headers=headers)
    assert response.status_code == 403


def test_rejected_before_spending_anything(client, behind_cloudfront):
    # 作問の処理（上限の消費・Bedrock）に入る前に止める
    def must_not_be_called():
        raise AssertionError("サービスが呼ばれた")

    app.dependency_overrides[get_problem_service] = must_not_be_called
    response = client.post("/api/problems", json={"theme": "株主総会", "target_length": 100})
    assert response.status_code == 403


def test_nothing_is_checked_without_a_secret(client, monkeypatch):
    # ローカル開発（Vite → uvicorn）は CloudFront を通らないので、確かめない
    monkeypatch.setattr(config, "ORIGIN_VERIFY_SECRET", "")
    assert client.get("/api/health").status_code == 200
