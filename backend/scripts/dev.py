"""ローカル開発用の起動スクリプト。

SAM で作ったスタック（既定は shoki-master）の Outputs からテーブル名とバケット名を
読み取り、環境変数に入れてから uvicorn を起動する。Lambda 上では SAM が同じ環境変数を
設定するので、ローカルと本番で同じ設定の受け取り方になる。

使い方（backend ディレクトリで）:
    ..\\.venv\\Scripts\\python.exe scripts\\dev.py [スタック名]

起動後、ブラウザで http://127.0.0.1:8000/docs を開くと API を試せる。
Bedrock と Polly を実際に呼ぶので、作問 1 回あたり約 2 円かかる。
"""

import os
import sys
from pathlib import Path

import boto3
import uvicorn

REGION = "ap-northeast-1"
BACKEND_DIR = Path(__file__).resolve().parents[1]

# スタックの Outputs のキー → アプリが読む環境変数の名前
OUTPUT_TO_ENV = {
    "ProblemsTableName": "PROBLEMS_TABLE",
    "AttemptsTableName": "ATTEMPTS_TABLE",
    "CountersTableName": "COUNTERS_TABLE",
    "AudioBucketName": "AUDIO_BUCKET",
}


def load_stack_outputs(stack_name: str) -> dict[str, str]:
    cloudformation = boto3.client("cloudformation", region_name=REGION)
    stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def main() -> None:
    stack_name = sys.argv[1] if len(sys.argv) > 1 else "shoki-master"
    outputs = load_stack_outputs(stack_name)

    missing = [key for key in OUTPUT_TO_ENV if key not in outputs]
    if missing:
        sys.exit(f"スタック {stack_name} の Outputs に {missing} がありません")

    print(f"接続先（スタック {stack_name}）:")
    for key, env in OUTPUT_TO_ENV.items():
        os.environ[env] = outputs[key]
        print(f"  {env:<15} = {outputs[key]}")
    os.environ.setdefault("AWS_REGION", REGION)
    print("\nAPI の試用画面: http://127.0.0.1:8000/docs\n")

    # reload=True だとコードを保存するたびに自動で再起動する。
    # 環境変数は再起動後のプロセスにも引き継がれる。
    uvicorn.run(
        "app.main:app",
        app_dir=str(BACKEND_DIR),
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(BACKEND_DIR / "app")],
    )


if __name__ == "__main__":
    main()
