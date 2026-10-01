from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from app.repositories.usage import UsageLimiter, UsageLimitExceeded, counter_ids

DAY1 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
NEXT_MONTH = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FakeDynamoDBClient:
    """TransactWriteItems の条件付き加算を模した偽物。

    本物と同じく、どれか 1 つでも条件を満たさなければ全部を取り消し、
    取り消し理由を更新の並び順で返す。
    """

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.transactions: list[list[dict]] = []

    def transact_write_items(self, TransactItems):
        self.transactions.append(TransactItems)
        reasons = []
        for item in TransactItems:
            update = item["Update"]
            counter_id = update["Key"]["counter_id"]["S"]
            limit = int(update["ExpressionAttributeValues"][":limit"]["N"])
            ok = counter_id not in self.counts or self.counts[counter_id] < limit
            reasons.append({"Code": "None" if ok else "ConditionalCheckFailed"})

        if any(r["Code"] != "None" for r in reasons):
            raise ClientError(
                {
                    "Error": {"Code": "TransactionCanceledException", "Message": "canceled"},
                    "CancellationReasons": reasons,
                },
                "TransactWriteItems",
            )

        for item in TransactItems:
            counter_id = item["Update"]["Key"]["counter_id"]["S"]
            self.counts[counter_id] = self.counts.get(counter_id, 0) + 1

    def get_item(self, TableName, Key):
        counter_id = Key["counter_id"]["S"]
        if counter_id not in self.counts:
            return {}
        return {"Item": {"counter_id": {"S": counter_id}, "count": {"N": str(self.counts[counter_id])}}}


@pytest.fixture
def client():
    return FakeDynamoDBClient()


def limiter(client, daily=3, monthly=5):
    return UsageLimiter(client=client, table_name="counters", daily_limit=daily, monthly_limit=monthly)


def test_counter_ids():
    assert counter_ids(DAY1) == ("problems#2026-09-01", "problems#2026-09")


def test_counter_ids_with_prefix():
    assert counter_ids(DAY1, "reviews") == ("reviews#2026-09-01", "reviews#2026-09")


class TestSeparateCounters:
    """作問と要約の採点は、同じテーブルの別々のカウンタで数える。"""

    def reviews(self, client, daily=3, monthly=5):
        return UsageLimiter(
            client=client, table_name="counters", daily_limit=daily, monthly_limit=monthly,
            prefix="reviews", label="要約採点", unit="回",
        )

    def test_counts_do_not_mix(self, client):
        limiter(client).consume(DAY1)
        self.reviews(client).consume(DAY1)
        self.reviews(client).consume(DAY1)
        assert limiter(client).current(DAY1) == {"daily": 1, "monthly": 1}
        assert self.reviews(client).current(DAY1) == {"daily": 2, "monthly": 2}

    def test_reaching_one_limit_does_not_block_the_other(self, client):
        for _ in range(3):
            self.reviews(client).consume(DAY1)
        with pytest.raises(UsageLimitExceeded):
            self.reviews(client).consume(DAY1)
        limiter(client).consume(DAY1)  # 作問は止まらない

    def test_message_names_what_was_limited(self, client):
        for _ in range(3):
            self.reviews(client).consume(DAY1)
        with pytest.raises(UsageLimitExceeded) as caught:
            self.reviews(client).consume(DAY1)
        assert str(caught.value) == "本日の要約採点上限（3 回）に達しました"


class TestConsume:
    def test_counts_up_to_the_daily_limit(self, client):
        lim = limiter(client, daily=3)
        for _ in range(3):
            lim.consume(DAY1)
        assert lim.current(DAY1) == {"daily": 3, "monthly": 3}

    def test_rejects_beyond_the_daily_limit(self, client):
        lim = limiter(client, daily=3)
        for _ in range(3):
            lim.consume(DAY1)
        with pytest.raises(UsageLimitExceeded) as caught:
            lim.consume(DAY1)
        assert caught.value.scope == "daily"
        assert caught.value.limit == 3
        assert "本日" in str(caught.value)

    def test_rejects_beyond_the_monthly_limit(self, client):
        lim = limiter(client, daily=3, monthly=5)
        for _ in range(3):
            lim.consume(DAY1)
        for _ in range(2):
            lim.consume(DAY2)
        with pytest.raises(UsageLimitExceeded) as caught:
            lim.consume(DAY2)
        assert caught.value.scope == "monthly"
        assert "今月" in str(caught.value)

    def test_rejection_does_not_count_either_counter(self, client):
        # 月次で弾かれたとき日次だけ増えると、翌日以降の枠を不当に削ってしまう
        lim = limiter(client, daily=3, monthly=5)
        for _ in range(3):
            lim.consume(DAY1)
        for _ in range(2):
            lim.consume(DAY2)
        with pytest.raises(UsageLimitExceeded):
            lim.consume(DAY2)
        assert lim.current(DAY2) == {"daily": 2, "monthly": 5}

    def test_new_day_starts_from_zero(self, client):
        lim = limiter(client, daily=3, monthly=100)
        for _ in range(3):
            lim.consume(DAY1)
        lim.consume(DAY2)
        assert lim.current(DAY2)["daily"] == 1

    def test_new_month_starts_from_zero(self, client):
        lim = limiter(client, daily=100, monthly=2)
        lim.consume(DAY1)
        lim.consume(DAY1)
        lim.consume(NEXT_MONTH)
        assert lim.current(NEXT_MONTH)["monthly"] == 1

    def test_other_errors_are_not_mistaken_for_the_limit(self):
        # 権限エラーなどを「上限に達した」と表示すると原因が分からなくなる
        class Broken:
            def transact_write_items(self, TransactItems):
                raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "TransactWriteItems")

        with pytest.raises(ClientError):
            limiter(Broken()).consume(DAY1)


class TestRequestShape:
    def test_both_counters_are_updated_in_one_transaction(self, client):
        limiter(client).consume(DAY1)
        assert len(client.transactions) == 1
        keys = [i["Update"]["Key"]["counter_id"]["S"] for i in client.transactions[0]]
        assert keys == ["problems#2026-09-01", "problems#2026-09"]

    def test_update_is_conditional_on_the_limit(self, client):
        limiter(client, daily=30, monthly=200).consume(DAY1)
        daily, monthly = (i["Update"] for i in client.transactions[0])
        assert daily["ConditionExpression"] == "attribute_not_exists(#count) OR #count < :limit"
        assert daily["ExpressionAttributeValues"][":limit"] == {"N": "30"}
        assert monthly["ExpressionAttributeValues"][":limit"] == {"N": "200"}

    def test_reserved_words_go_through_aliases(self, client):
        # count と ttl は DynamoDB の予約語で、式に直接書くとエラーになる
        limiter(client).consume(DAY1)
        update = client.transactions[0][0]["Update"]
        assert update["ExpressionAttributeNames"] == {"#count": "count", "#ttl": "ttl"}
        assert "count" not in update["UpdateExpression"].replace("#count", "")

    def test_missing_counter_reads_as_zero(self, client):
        assert limiter(client).current(DAY1) == {"daily": 0, "monthly": 0}
