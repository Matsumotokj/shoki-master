"""バックエンドと画面をまとめてデプロイする。

  1. sam build
  2. sam deploy（samconfig.toml の設定どおり、変更内容を見てから y で実行する）
  3. 画面のビルド（npm run build。型チェックを含む）
  4. 画面のファイルを S3 にアップロードする
       assets/ を先に、index.html を最後に置く。逆だと、新しい index.html が
       まだ置かれていない JS を指す瞬間ができる。最後に、使われなくなった古い
       assets/ のファイルを消す

使い方（リポジトリのルートで。boto3 の入った backend の venv を使う）:
    .venv\\Scripts\\python scripts\\deploy.py                  # 全部
    .venv\\Scripts\\python scripts\\deploy.py --frontend-only  # 画面だけ（1・2 を飛ばす）

AWS の認証は aws login のセッションを使う。
"""

import argparse
import mimetypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
STACK_NAME = "shoki-master"
REGION = "ap-northeast-1"

ASSETS_PREFIX = "assets/"
ENTRY = "index.html"

# assets/ のファイルは名前に中身のハッシュが入る（中身が変われば名前も変わる）ので 1 年キャッシュさせる。
# それ以外（index.html など）は名前が変わらないので、毎回確かめさせる
ASSET_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# Windows ではファイルの種類の推定がレジストリに左右されるので、使うものは固定する
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".json": "application/json",
}


@dataclass(frozen=True)
class Upload:
    path: Path
    key: str
    cache_control: str
    content_type: str


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_plan(dist: Path) -> list[Upload]:
    """アップロードする順番の一覧。assets/ → その他 → index.html の順。"""
    uploads = []
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        key = path.relative_to(dist).as_posix()
        cache = ASSET_CACHE if key.startswith(ASSETS_PREFIX) else NO_CACHE
        uploads.append(Upload(path, key, cache, content_type(path)))

    def order(upload: Upload) -> int:
        if upload.key == ENTRY:
            return 2
        return 0 if upload.key.startswith(ASSETS_PREFIX) else 1

    return sorted(uploads, key=order)


def stale_assets(existing_keys: list[str], plan: list[Upload]) -> list[str]:
    """バケットにあるが、今回のビルドに無い assets/ のファイル（前のビルドの残り）。"""
    current = {u.key for u in plan}
    return [k for k in existing_keys if k.startswith(ASSETS_PREFIX) and k not in current]


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    # sam・npm は Windows では .cmd なので、実体のパスを探してから実行する
    executable = shutil.which(command[0])
    if executable is None:
        sys.exit(f"{command[0]} が見つかりません")
    print(f"\n$ {' '.join(command)}", flush=True)
    result = subprocess.run([executable, *command[1:]], cwd=cwd, env=env)
    if result.returncode != 0:
        sys.exit(f"\n「{' '.join(command)}」が失敗しました（終了コード {result.returncode}）。上のメッセージを確認してください")


def check_credentials(session) -> None:
    """最初に AWS の認証を確かめる。時間のかかる sam build の後で切れていると分かるのを避ける。"""
    try:
        session.client("sts").get_caller_identity()
    except (BotoCoreError, ClientError) as error:
        sys.exit(f"AWS の認証を確かめられませんでした（{error}）。aws login を実行してから、もう一度実行してください")


def deploy_backend() -> None:
    # パスに日本語を含む Windows では、これが無いと sam build が文字コードの違いで失敗する
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    run(["sam", "build"], cwd=ROOT, env=env)
    # 変更が無いときも失敗扱いにしない（画面だけを変えた場合など）
    run(["sam", "deploy", "--no-fail-on-empty-changeset"], cwd=ROOT, env=env)


def build_frontend() -> None:
    if not (FRONTEND / "node_modules").exists():
        run(["npm", "ci"], cwd=FRONTEND)
    run(["npm", "run", "build"], cwd=FRONTEND)


def stack_outputs(session) -> dict[str, str]:
    stack = session.client("cloudformation").describe_stacks(StackName=STACK_NAME)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def upload_frontend(s3, bucket: str) -> None:
    plan = upload_plan(DIST)
    if not any(u.key == ENTRY for u in plan):
        sys.exit(f"{DIST / ENTRY} がありません。画面のビルドに失敗しています")

    print(f"\ns3://{bucket}/ にアップロード", flush=True)
    for upload in plan:
        s3.upload_file(
            str(upload.path),
            bucket,
            upload.key,
            ExtraArgs={"CacheControl": upload.cache_control, "ContentType": upload.content_type},
        )
        print(f"  {upload.key}  ({upload.cache_control})")

    existing = [
        obj["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=ASSETS_PREFIX)
        for obj in page.get("Contents", [])
    ]
    for key in stale_assets(existing, plan):
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"  {key}  を削除（前のビルドの残り）")


def main() -> None:
    parser = argparse.ArgumentParser(description="バックエンドと画面をデプロイする")
    parser.add_argument("--frontend-only", action="store_true", help="sam build / deploy を飛ばし、画面だけ更新する")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    check_credentials(session)

    if not args.frontend_only:
        deploy_backend()
    build_frontend()

    outputs = stack_outputs(session)
    upload_frontend(session.client("s3"), outputs["FrontendBucketName"])
    print(f"\n完了: {outputs['SiteUrl']}")


if __name__ == "__main__":
    main()
