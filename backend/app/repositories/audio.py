"""生成した音声の保管と配信（Amazon S3）。

バケットは非公開にしておき、再生には有効期限付きの署名付き URL を発行する。
バケットを公開すれば URL の発行は不要になるが、置いたものが恒久的に誰でも
取得できる状態になるため採用しない。

古い音声の削除はバケットのライフサイクルルール（1 日）に任せる。
アプリ側で削除処理を書くと、消し忘れと余計な API 呼び出しが生まれる。
"""

import boto3
from botocore.config import Config

from app import config


def audio_key(problem_id: str) -> str:
    """音声を置く場所の名前。S3 に実際のフォルダは存在せず、これ全体が 1 つの名前。"""
    return f"audio/{problem_id}.mp3"


def s3_client(region_name: str = config.REGION, session=boto3):
    """署名付き URL が正しく作られるよう設定した S3 クライアント。

    boto3 の既定のままだと、署名付き URL が旧式の署名（SigV2）で、接続先も
    リージョンを含まない s3.amazonaws.com になる。東京リージョンのバケットでは
    S3 が 307 で東京の接続先へリダイレクトさせるため、再生位置を動かすたびに
    往復が 1 回増える。SigV4 に固定し、接続先もリージョン付きで指定する。
    SigV4 は接続先のホスト名も署名に含めるので、両方をそろえる必要がある。
    """
    return session.client(
        "s3",
        region_name=region_name,
        endpoint_url=f"https://s3.{region_name}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


class AudioStorage:
    """音声の保存と、再生用 URL の発行。"""

    def __init__(self, bucket: str, client=None, region_name: str = config.REGION):
        self._bucket = bucket
        self._client = client or s3_client(region_name)

    def put(self, problem_id: str, audio: bytes, key: str | None = None) -> str:
        """音声を保存し、そのキーを返す。

        既定は audio/ の下（1 日で消える）。サンプル問題は key で samples/ の下を指定する。
        """
        key = key or audio_key(problem_id)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=audio,
            ContentType="audio/mpeg",
        )
        return key

    def presigned_url(
        self, key: str, expires_in: int = config.AUDIO_URL_EXPIRES_SECONDS
    ) -> str:
        """期限付きの再生用 URL を発行する。

        この呼び出しは AWS と通信しない。手元の認証情報で署名を計算するだけなので、
        即座に返り、料金もかからない。URL を知っていれば期限内は誰でも取得できるため、
        期限は短く保つ。
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
