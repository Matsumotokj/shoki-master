"""サンプル問題の定義と、一覧の API。"""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.samples import load_samples, sample_audio_key
from app.schemas.api import PROBLEM_ID_PATTERN
from app.services.script_segmentation import split_sentences
from app.services.transcription_scoring import normalize


@pytest.fixture
def samples():
    return load_samples()


class TestDefinitions:
    def test_one_sample_per_mode(self, samples):
        # 評価者が両方のモードを体験できるように（要件 F4-2）
        assert sorted(s.mode for s in samples) == ["summary", "transcription"]

    def test_ids_are_unique_and_well_formed(self, samples):
        ids = [s.problem_id for s in samples]
        assert len(set(ids)) == len(ids)
        assert all(re.match(PROBLEM_ID_PATTERN, i) for i in ids)

    def test_texts_follow_the_generation_rules(self, samples):
        # 生成した題材と同じ規則を守る: 改行なし・句点で終わる・数は算用数字
        for s in samples:
            assert "\n" not in s.text
            assert s.text.endswith("。")
            assert not re.search(r"[一二三四五六七八九十百千]+(時|日|週|名|分|円|%)", s.text), s.text

    def test_texts_split_into_several_sentences(self, samples):
        for s in samples:
            assert len(split_sentences(s.text)) >= 3

    def test_short_enough_to_try_quickly(self, samples):
        # 評価者が数十秒で試せる長さ
        for s in samples:
            assert len(normalize(s.text)) <= 200

    def test_audio_is_kept_out_of_the_expiring_prefix(self, samples):
        # audio/ の下は 1 日で消えるので、サンプルは別の場所に置く
        for s in samples:
            key = sample_audio_key(s.problem_id)
            assert key.startswith("samples/")
            assert not key.startswith("audio/")


class TestListSamples:
    def test_lists_samples_without_touching_aws(self, samples):
        # 一覧は定義ファイルを読むだけ。conftest が AWS への接続を禁止しているので、
        # 接続しようとすればこのテストは失敗する
        response = TestClient(app).get("/api/samples")
        assert response.status_code == 200
        body = response.json()
        assert [b["problem_id"] for b in body] == [s.problem_id for s in samples]
        assert set(body[0]) == {"problem_id", "mode", "theme"}
