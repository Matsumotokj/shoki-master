from urllib.parse import parse_qs, urlparse

import boto3
import pytest

from app.repositories.audio import AudioStorage, audio_key, s3_client

BUCKET = "example-audio-123456789012-ap-northeast-1-an"


class FakeS3Client:
    def __init__(self):
        self.put_calls: list[dict] = []

    def put_object(self, **params):
        self.put_calls.append(params)
        return {}


@pytest.fixture
def offline_session():
    """AWS と通信しないセッション。

    署名付き URL の生成は手元で署名を計算するだけなので、ダミーの認証情報で
    実物の boto3 の挙動を確かめられる。conftest が禁止しているのは
    boto3.client（既定の認証情報で実サービスへつながる経路）だけ。
    """
    return boto3.session.Session(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        region_name="ap-northeast-1",
    )


def test_audio_key():
    assert audio_key("abc123") == "audio/abc123.mp3"


class TestPut:
    def test_puts_with_audio_content_type(self):
        # ContentType が無いとブラウザが再生せずダウンロードしてしまう
        fake = FakeS3Client()
        key = AudioStorage(BUCKET, client=fake).put("abc123", b"mp3")
        assert key == "audio/abc123.mp3"
        assert fake.put_calls == [
            {"Bucket": BUCKET, "Key": "audio/abc123.mp3", "Body": b"mp3", "ContentType": "audio/mpeg"}
        ]


class TestPresignedUrl:
    def _url(self, session, expires_in=3600):
        storage = AudioStorage(BUCKET, client=s3_client("ap-northeast-1", session=session))
        return urlparse(storage.presigned_url("audio/abc123.mp3", expires_in=expires_in))

    def test_uses_the_regional_endpoint(self, offline_session):
        # s3.amazonaws.com だと 307 リダイレクトが挟まり、シークのたびに往復が増える
        url = self._url(offline_session)
        assert url.netloc == f"{BUCKET}.s3.ap-northeast-1.amazonaws.com"

    def test_uses_signature_version_4(self, offline_session):
        query = parse_qs(self._url(offline_session).query)
        assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
        assert "Signature" not in query  # 旧式（SigV2）の形式ではない

    def test_expiry_is_embedded(self, offline_session):
        query = parse_qs(self._url(offline_session, expires_in=300).query)
        assert query["X-Amz-Expires"] == ["300"]

    def test_points_at_the_object(self, offline_session):
        assert self._url(offline_session).path == "/audio/abc123.mp3"
