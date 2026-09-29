"""問題と回答の保存（Amazon DynamoDB）。

DynamoDB には結合が無いため、一緒に読むものは 1 つの項目にまとめて持つ。
問題を取り出すときは必ず文の一覧も要るので、sentences は別テーブルにせず
問題の項目の中に配列として置く。

保存した項目には ttl（消える時刻の Unix 秒）を入れておく。DynamoDB が
自動で削除するため、削除処理も定期実行も書かなくてよい。
"""

import time
import uuid
from decimal import Decimal
from typing import Any

import boto3

from app import config
from app.schemas.problem import Sentence


def new_problem_id() -> str:
    return uuid.uuid4().hex


def new_attempt_id() -> str:
    """時刻を先頭に置き、辞書順が時系列順になるようにする。

    DynamoDB はソートキーの順に並ぶので、これで「最新の挑戦から取る」が
    並べ替えなしでできる。
    """
    return f"{int(time.time() * 1000):013d}-{uuid.uuid4().hex[:8]}"


def _expires_at(now: int | None = None) -> int:
    return (now or int(time.time())) + config.TTL_SECONDS


def _to_plain(value: Any) -> Any:
    """DynamoDB が返す Decimal を、扱いやすい int / float に戻す。

    数値はすべて Decimal で返るため、そのままだと Pydantic や json が扱いにくい。
    """
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    return value


class ProblemRepository:
    """問題と、その問題への回答の読み書き。"""

    def __init__(self, problems_table=None, attempts_table=None, region_name: str = config.REGION):
        if problems_table is None or attempts_table is None:
            resource = boto3.resource("dynamodb", region_name=region_name)
            problems_table = problems_table or resource.Table(config.PROBLEMS_TABLE)
            attempts_table = attempts_table or resource.Table(config.ATTEMPTS_TABLE)
        self._problems = problems_table
        self._attempts = attempts_table

    def save_problem(
        self,
        *,
        problem_id: str,
        mode: str,
        theme: str,
        target_length: int,
        info: str,
        text: str,
        sentences: list[Sentence],
        audio_key: str,
        duration_ms: int | None = None,
        expires: bool = True,
    ) -> None:
        """問題を保存する。

        expires=False にすると ttl を書かない。DynamoDB は ttl 属性の無い項目を
        消さないので、サンプル問題のように残しておきたいものに使う。
        """
        item = {
            "problem_id": problem_id,
            "mode": mode,
            "theme": theme,
            "target_length": target_length,
            "info": info,
            "text": text,
            "sentences": [s.model_dump() for s in sentences],
            "audio_key": audio_key,
            "created_at": int(time.time()),
        }
        if duration_ms is not None:
            item["duration_ms"] = duration_ms
        if expires:
            item["ttl"] = _expires_at()
        self._problems.put_item(Item=item)

    def get_problem(self, problem_id: str) -> dict[str, Any] | None:
        """問題を 1 件取り出す。見つからなければ None。

        TTL で消えた後や、存在しない ID を指定された場合に None が返る。
        """
        response = self._problems.get_item(Key={"problem_id": problem_id})
        item = response.get("Item")
        return _to_plain(item) if item else None

    def save_attempt(
        self, *, problem_id: str, mode: str, user_input: str, result: dict[str, Any]
    ) -> str:
        attempt_id = new_attempt_id()
        self._attempts.put_item(
            Item={
                "problem_id": problem_id,
                "attempt_id": attempt_id,
                "mode": mode,
                "user_input": user_input,
                "result": result,
                "created_at": int(time.time()),
                "ttl": _expires_at(),
            }
        )
        return attempt_id
