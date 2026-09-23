"""テスト全体の前提。

自動テストは課金の発生する外部サービスを呼ばない（要件 N4-4）。
うっかり実サービスを叩くコードが混ざったときに黙って課金されないよう、
boto3 のクライアント生成自体をテスト中は失敗させる。
"""

import boto3
import pytest


@pytest.fixture(autouse=True)
def forbid_aws_clients(monkeypatch):
    def _blocked(*args, **kwargs):
        service = args[0] if args else kwargs.get("service_name", "?")
        raise AssertionError(
            f"テスト中に AWS クライアント({service})を生成しようとしました。"
            "偽のクライアントを渡してください。"
        )

    monkeypatch.setattr(boto3, "client", _blocked)
