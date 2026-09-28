"""SAM で作ったリソースに対して、repositories のコードを実際に動かす。

課金は 1 円未満（DynamoDB の読み書き数十回と、S3 への 1 回の書き込み）。
書き込んだ題材・回答・音声は TTL とライフサイクルで 1 日後に消える。
リソースの名前は環境変数で差し替えられる（既定は shoki-master スタックの名前）。

使い方:
    python scripts/try_storage.py
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# テーブル名は config.py の既定値が shoki-master スタックの名前と一致している。
# バケット名はアカウント ID を含むので、ここで補う（sam deploy の Outputs を参照）。
os.environ.setdefault("AUDIO_BUCKET", "shoki-master-audio-843232832210-ap-northeast-1-an")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402

from app import config  # noqa: E402
from app.repositories.audio import AudioStorage  # noqa: E402
from app.repositories.problems import ProblemRepository, new_problem_id  # noqa: E402
from app.repositories.usage import UsageLimiter, UsageLimitExceeded, counter_ids  # noqa: E402
from app.schemas.problem import Sentence  # noqa: E402

SAMPLE_AUDIO = Path.home() / "Desktop" / "polly-samples" / "Takumi_break350.mp3"

TEXT = (
    "本日はお忙しい中お集まりいただき、誠にありがとうございます。"
    "第三四半期の業績についてご報告いたします。"
)
SENTENCES = [
    Sentence(index=0, text="本日はお忙しい中お集まりいただき、誠にありがとうございます。", start_ms=12),
    Sentence(index=1, text="第三四半期の業績についてご報告いたします。", start_ms=4712),
]


def heading(title: str) -> None:
    print(f"\n=== {title} ===")


def try_audio(problem_id: str) -> str:
    heading("1. S3: 音声を置いて、署名付き URL を発行する")
    storage = AudioStorage(config.AUDIO_BUCKET)
    key = storage.put(problem_id, SAMPLE_AUDIO.read_bytes())
    url = storage.presigned_url(key, expires_in=300)
    print(f"キー        : {key}")
    print(f"URL（5分）  : {url[:90]}...")
    print("→ URL 全体をブラウザで開くと再生できる")
    return key


def try_problem(repo: ProblemRepository, problem_id: str, audio_key: str) -> None:
    heading("2. DynamoDB: 日本語の題材を保存して取り出す")
    repo.save_problem(
        problem_id=problem_id,
        mode="transcription",
        theme="株主総会の挨拶",
        target_length=60,
        info="",
        text=TEXT,
        sentences=SENTENCES,
        audio_key=audio_key,
    )

    # boto3 がそのまま返す値（数値は Decimal）
    table = boto3.resource("dynamodb", region_name=config.REGION).Table(config.PROBLEMS_TABLE)
    raw = table.get_item(Key={"problem_id": problem_id})["Item"]
    print(f"生の target_length : {raw['target_length']!r}  ← Decimal で返る")

    # repositories を通すと int に戻っている
    item = repo.get_problem(problem_id)
    print(f"変換後             : {item['target_length']!r}  ← int")
    print(f"題材               : {item['text']}")
    print(f"文の数・開始位置   : {[(s['index'], s['start_ms']) for s in item['sentences']]}")
    print(f"TTL（Unix 秒）     : {item['ttl']}")
    print(f"存在しない ID      : {repo.get_problem('no-such-problem')!r}  ← エラーではなく None")


def try_attempts(repo: ProblemRepository, problem_id: str) -> None:
    heading("3. DynamoDB: 同じ問題に 2 回回答する → ソートキー順に並ぶ")
    for accuracy in (72, 88):
        attempt_id = repo.save_attempt(
            problem_id=problem_id,
            mode="transcription",
            user_input="本日はお忙しい中…",
            result={"accuracy": accuracy},
        )
        print(f"保存: attempt_id={attempt_id}  正答率={accuracy}")

    table = boto3.resource("dynamodb", region_name=config.REGION).Table(config.ATTEMPTS_TABLE)
    latest = table.query(
        KeyConditionExpression=Key("problem_id").eq(problem_id),
        ScanIndexForward=False,  # 新しい順
        Limit=1,
    )
    print(
        f"最新の 1 件        : 正答率={latest['Items'][0]['result']['accuracy']}"
        f"  （ScannedCount={latest['ScannedCount']}）"
    )


def try_usage_limits() -> None:
    heading("4. DynamoDB: 日次 3 回・月次 5 回の上限をトランザクションで守る")

    # 実際の日付と混ざらないよう、2000 年の日付で試す。前回の実行分は消してから始める。
    day1 = datetime(2000, 1, 1, tzinfo=timezone.utc)
    day2 = datetime(2000, 1, 2, tzinfo=timezone.utc)
    client = boto3.client("dynamodb", region_name=config.REGION)
    for counter_id in {*counter_ids(day1), *counter_ids(day2)}:
        client.delete_item(TableName=config.COUNTERS_TABLE, Key={"counter_id": {"S": counter_id}})

    limiter = UsageLimiter(daily_limit=3, monthly_limit=5)

    def attempt(label: str, now: datetime) -> None:
        try:
            limiter.consume(now)
            result = "OK"
        except UsageLimitExceeded as error:
            result = f"拒否（{error}）"
        counts = limiter.current(now)
        print(f"{label}: {result:<30} 日次={counts['daily']}  月次={counts['monthly']}")

    print("-- 1 日目: 日次の上限 3 に当たる")
    for i in range(1, 5):
        attempt(f"  {i} 回目", day1)

    print("-- 2 日目: 日次はまだ余裕があるが、月次の上限 5 に当たる")
    for i in range(1, 4):
        attempt(f"  {i} 回目", day2)

    print("→ 月次で拒否されたとき、日次のカウンタも増えていない（2 つの更新がまとめて取り消される）")


def main() -> None:
    print("接続先:")
    print(f"  問題     : {config.PROBLEMS_TABLE}")
    print(f"  回答     : {config.ATTEMPTS_TABLE}")
    print(f"  カウンタ : {config.COUNTERS_TABLE}")
    print(f"  音声     : {config.AUDIO_BUCKET}")

    repo = ProblemRepository()
    problem_id = new_problem_id()

    audio_key = try_audio(problem_id)
    try_problem(repo, problem_id, audio_key)
    try_attempts(repo, problem_id)
    try_usage_limits()


if __name__ == "__main__":
    main()
