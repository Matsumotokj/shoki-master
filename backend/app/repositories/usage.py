"""作問数の上限（Amazon DynamoDB）。

要件 N2-3 の費用上限を仕組みで担保する。日次はバースト制限、月次が月額を抑える本体。

「読んで、上限未満なら 1 増やす」を別々に行うと、同時に処理が走ったときに
どちらも上限未満と判断して両方通ってしまう。DynamoDB の更新は
条件式を付けられ、条件を満たさなければ書き込み自体が起きないため、
読み取りと加算を 1 回の操作にまとめられる。

さらに日次と月次は「両方とも上限未満のときだけ、両方を 1 増やす」必要がある。
別々に更新すると、日次だけ増えて月次で弾かれたときに日次を戻す処理が要る。
TransactWriteItems は複数の更新をまとめて成功・失敗させるため、これを避けられる。
"""

import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from app import config


class UsageLimitExceeded(RuntimeError):
    """作問数が上限に達した。"""

    def __init__(self, scope: str, limit: int):
        self.scope = scope
        self.limit = limit
        period = "本日" if scope == "daily" else "今月"
        super().__init__(f"{period}の作問上限（{limit} 問）に達しました")


def counter_ids(now: datetime | None = None) -> tuple[str, str]:
    """日次・月次それぞれのカウンタの ID を作る。

    日付が変われば ID が変わり、新しいカウンタが 0 から始まる。
    リセット処理を書かなくてよい。
    """
    now = now or datetime.now(UTC)
    return f"problems#{now:%Y-%m-%d}", f"problems#{now:%Y-%m}"


class UsageLimiter:
    """作問の回数を数え、上限を超える要求を拒む。"""

    def __init__(
        self,
        client=None,
        table_name: str = config.COUNTERS_TABLE,
        region_name: str = config.REGION,
        daily_limit: int = config.DAILY_PROBLEM_LIMIT,
        monthly_limit: int = config.MONTHLY_PROBLEM_LIMIT,
    ):
        self._client = client or boto3.client("dynamodb", region_name=region_name)
        self._table = table_name
        self._daily_limit = daily_limit
        self._monthly_limit = monthly_limit

    def consume(self, now: datetime | None = None) -> None:
        """作問 1 回分を計上する。上限を超える場合は UsageLimitExceeded。

        カウンタ自体にも有効期限を付けておき、古い日付のカウンタが
        際限なく溜まらないようにする。
        """
        daily_id, monthly_id = counter_ids(now)
        # 月次カウンタは月をまたいでも残るよう、日次より長く保つ
        expires = int(time.time()) + 70 * 24 * 60 * 60

        try:
            self._client.transact_write_items(
                TransactItems=[
                    self._increment(daily_id, self._daily_limit, expires),
                    self._increment(monthly_id, self._monthly_limit, expires),
                ]
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            # どちらの条件で弾かれたかは、取り消し理由の並び順で分かる
            reasons = error.response.get("CancellationReasons", [])
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                raise UsageLimitExceeded("daily", self._daily_limit) from error
            raise UsageLimitExceeded("monthly", self._monthly_limit) from error

    def _increment(self, counter_id: str, limit: int, expires: int) -> dict:
        """カウンタを 1 増やす更新。ただし上限未満のときだけ成立する。"""
        return {
            "Update": {
                "TableName": self._table,
                "Key": {"counter_id": {"S": counter_id}},
                # ADD は「無ければ 0 から始めて加算」する書き方
                "UpdateExpression": "ADD #count :one SET #ttl = :ttl",
                # count も ttl も DynamoDB の予約語なので、別名を経由して指定する
                "ExpressionAttributeNames": {"#count": "count", "#ttl": "ttl"},
                "ExpressionAttributeValues": {
                    ":one": {"N": "1"},
                    ":ttl": {"N": str(expires)},
                    ":limit": {"N": str(limit)},
                },
                # 条件を満たさなければ加算も起きない
                "ConditionExpression": "attribute_not_exists(#count) OR #count < :limit",
            }
        }

    def status(self, now: datetime | None = None) -> dict[str, dict[str, int]]:
        """日次・月次それぞれの使用数・上限・残りを返す（画面に「あと何問」を出すため）。"""
        used = self.current(now)
        limits = {"daily": self._daily_limit, "monthly": self._monthly_limit}
        return {
            scope: {"used": used[scope], "limit": limits[scope], "remaining": max(0, limits[scope] - used[scope])}
            for scope in ("daily", "monthly")
        }

    def current(self, now: datetime | None = None) -> dict[str, int]:
        """現在の使用数を返す（表示・確認用）。"""
        daily_id, monthly_id = counter_ids(now)
        return {
            "daily": self._read(daily_id),
            "monthly": self._read(monthly_id),
        }

    def _read(self, counter_id: str) -> int:
        response = self._client.get_item(
            TableName=self._table, Key={"counter_id": {"S": counter_id}}
        )
        item = response.get("Item")
        return int(item["count"]["N"]) if item and "count" in item else 0
