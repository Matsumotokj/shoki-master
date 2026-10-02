"""Basic 認証の ID とパスワードから、KeyValueStore に登録するキーを作る。

ブラウザは ID とパスワードを「Basic <base64(ID:パスワード)>」の形にして、
Authorization ヘッダで送る。CloudFront の関数（template.yaml の SiteRequestFunction）は
そのヘッダ全体の SHA-256 を計算し、KeyValueStore のキーにあるかで照合する。
ここで同じ計算をして、登録するキーを作る。パスワードそのものはどこにも保存しない。

使い方（標準ライブラリだけで動く）:
    python scripts/basic_auth_key.py
"""

import base64
import getpass
import hashlib


def authorization_header(user_id: str, password: str) -> str:
    """ブラウザが送る Authorization ヘッダの値。文字は UTF-8 で数える（関数の charset と同じ）。"""
    token = base64.b64encode(f"{user_id}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def credential_key(user_id: str, password: str) -> str:
    return hashlib.sha256(authorization_header(user_id, password).encode("ascii")).hexdigest()


def main() -> None:
    user_id = input("ID: ").strip()
    password = getpass.getpass("パスワード（入力は表示されません）: ")
    if not user_id or not password:
        raise SystemExit("ID とパスワードの両方を入力してください")
    if ":" in user_id:
        # Basic 認証は最初の : で ID とパスワードを分けるため、ID には使えない
        raise SystemExit("ID に : は使えません")
    print(credential_key(user_id, password))


if __name__ == "__main__":
    main()
