from decimal import Decimal

import pytest

from app import config
from app.repositories import problems as problems_module
from app.repositories.problems import ProblemRepository, _to_plain, new_attempt_id
from app.schemas.problem import Sentence

NOW = 1_790_000_000


class FakeTable:
    """DynamoDB のテーブルを模した偽物。

    本物と同じく、書いた数値は読み出し時に Decimal で返す。
    """

    def __init__(self, key_names: tuple[str, ...]):
        self._key_names = key_names
        self.items: dict[tuple, dict] = {}

    def put_item(self, Item):
        key = tuple(Item[name] for name in self._key_names)
        self.items[key] = Item

    def get_item(self, Key):
        item = self.items.get(tuple(Key[name] for name in self._key_names))
        return {"Item": _as_dynamodb(item)} if item else {}


def _as_dynamodb(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_as_dynamodb(v) for v in value]
    if isinstance(value, dict):
        return {k: _as_dynamodb(v) for k, v in value.items()}
    return value


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(problems_module.time, "time", lambda: NOW + 0.123)


@pytest.fixture
def tables():
    return FakeTable(("problem_id",)), FakeTable(("problem_id", "attempt_id"))


@pytest.fixture
def repo(tables):
    return ProblemRepository(problems_table=tables[0], attempts_table=tables[1])


def save_sample(repo, problem_id="p1"):
    repo.save_problem(
        problem_id=problem_id,
        mode="transcription",
        theme="株主総会の挨拶",
        target_length=300,
        info="",
        text="本日は晴天です。明日は雨です。",
        sentences=[
            Sentence(index=0, text="本日は晴天です。", start_ms=0),
            Sentence(index=1, text="明日は雨です。", start_ms=2500),
        ],
        audio_key="audio/p1.mp3",
    )


class TestSaveProblem:
    def test_stores_sentences_inside_the_problem_item(self, repo, tables):
        # 結合が無いので、一緒に読む文の一覧は同じ項目に持つ
        save_sample(repo)
        item = tables[0].items[("p1",)]
        assert item["sentences"] == [
            {"index": 0, "text": "本日は晴天です。", "start_ms": 0},
            {"index": 1, "text": "明日は雨です。", "start_ms": 2500},
        ]

    def test_sets_ttl_one_day_ahead(self, repo, tables):
        save_sample(repo)
        item = tables[0].items[("p1",)]
        assert item["created_at"] == NOW
        assert item["ttl"] == NOW + config.TTL_SECONDS

    def test_problem_without_expiry_has_no_ttl(self, repo, tables):
        # ttl 属性の無い項目は DynamoDB が消さない（サンプル問題用）
        repo.save_problem(
            problem_id="sample", mode="summary", theme="t", target_length=10, info="",
            text="本日は晴天です。", sentences=[], audio_key="samples/sample.mp3", expires=False,
        )
        assert "ttl" not in tables[0].items[("sample",)]

    def test_ttl_is_in_seconds_not_milliseconds(self, repo, tables):
        # ミリ秒で書くと DynamoDB は数万年後の期限と解釈し、消えなくなる
        save_sample(repo)
        assert len(str(tables[0].items[("p1",)]["ttl"])) == 10


class TestGetProblem:
    def test_numbers_come_back_as_plain_ints(self, repo):
        save_sample(repo)
        problem = repo.get_problem("p1")
        assert problem["target_length"] == 300
        assert type(problem["target_length"]) is int
        assert type(problem["sentences"][1]["start_ms"]) is int

    def test_round_trips_japanese_text(self, repo):
        save_sample(repo)
        assert repo.get_problem("p1")["text"] == "本日は晴天です。明日は雨です。"

    def test_missing_problem_returns_none(self, repo):
        assert repo.get_problem("no-such-id") is None

    def test_expired_problem_returns_none_before_dynamodb_deletes_it(self, repo, monkeypatch):
        # TTL の削除は遅れることがあり、期限後もしばらく項目が読めてしまう
        save_sample(repo)
        monkeypatch.setattr(problems_module.time, "time", lambda: NOW + config.TTL_SECONDS)
        assert repo.get_problem("p1") is None

    def test_problem_is_readable_just_before_expiry(self, repo, monkeypatch):
        save_sample(repo)
        monkeypatch.setattr(problems_module.time, "time", lambda: NOW + config.TTL_SECONDS - 1)
        assert repo.get_problem("p1") is not None

    def test_problem_without_ttl_never_expires(self, repo, monkeypatch):
        repo.save_problem(
            problem_id="sample", mode="summary", theme="t", target_length=10, info="",
            text="本日は晴天です。", sentences=[], audio_key="samples/sample.mp3", expires=False,
        )
        monkeypatch.setattr(problems_module.time, "time", lambda: NOW + 10 * config.TTL_SECONDS)
        assert repo.get_problem("sample") is not None


class TestSaveAttempt:
    def test_stores_under_the_problem_id(self, repo, tables):
        attempt_id = repo.save_attempt(
            problem_id="p1", mode="summary", user_input="まとめ", result={"score": 80}
        )
        item = tables[1].items[("p1", attempt_id)]
        assert item["user_input"] == "まとめ"
        assert item["result"] == {"score": 80}
        assert item["ttl"] == NOW + config.TTL_SECONDS

    def test_two_attempts_do_not_overwrite_each_other(self, repo, tables):
        # 同じ問題への再挑戦（要件 F3-4）。ソートキーが違うので別の項目になる
        repo.save_attempt(problem_id="p1", mode="summary", user_input="1", result={})
        repo.save_attempt(problem_id="p1", mode="summary", user_input="2", result={})
        assert len(tables[1].items) == 2


class TestAttemptId:
    def test_later_ids_sort_after_earlier_ones(self, monkeypatch):
        # ソートキーは文字列の辞書順で並ぶので、辞書順と時系列順を一致させる
        times = iter([NOW + 0.001, NOW + 0.020, NOW + 10.0])
        monkeypatch.setattr(problems_module.time, "time", lambda: next(times))
        ids = [new_attempt_id() for _ in range(3)]
        assert ids == sorted(ids)

    def test_millisecond_part_is_zero_padded(self):
        assert new_attempt_id().split("-")[0] == f"{int((NOW + 0.123) * 1000):013d}"


class TestToPlain:
    def test_converts_nested_decimals(self):
        value = {"a": Decimal("1"), "b": [Decimal("2.5"), {"c": Decimal("3")}], "d": "x"}
        assert _to_plain(value) == {"a": 1, "b": [2.5, {"c": 3}], "d": "x"}

    def test_leaves_booleans_alone(self):
        assert _to_plain({"flag": True}) == {"flag": True}
