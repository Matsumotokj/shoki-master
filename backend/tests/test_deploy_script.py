"""デプロイ用スクリプト（リポジトリ直下の scripts/deploy.py）のうち、アップロードの順番とキャッシュの設定。

ここを間違えると、画面を更新した直後に古い JS が使われ続けたり、
新しい index.html がまだ無い JS を指したりする。AWS は呼ばない。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from deploy import ASSET_CACHE, NO_CACHE, stale_assets, upload_plan  # noqa: E402


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    for name in ["index.html", "assets/index-abc123.js", "assets/index-def456.css", "favicon.ico"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    return tmp_path


def test_index_html_is_uploaded_last_and_assets_first(dist):
    keys = [u.key for u in upload_plan(dist)]
    assert keys[-1] == "index.html"
    assert keys[:2] == ["assets/index-abc123.js", "assets/index-def456.css"]


def test_hashed_assets_are_cached_and_the_rest_is_revalidated(dist):
    cache = {u.key: u.cache_control for u in upload_plan(dist)}
    assert cache["assets/index-abc123.js"] == ASSET_CACHE
    # 名前が変わらないファイルを長くキャッシュさせると、更新が届かなくなる
    assert cache["index.html"] == NO_CACHE
    assert cache["favicon.ico"] == NO_CACHE


def test_content_types(dist):
    types = {u.key: u.content_type for u in upload_plan(dist)}
    assert types["index.html"] == "text/html; charset=utf-8"
    assert types["assets/index-abc123.js"] == "text/javascript; charset=utf-8"
    assert types["assets/index-def456.css"] == "text/css; charset=utf-8"


def test_only_old_assets_are_removed(dist):
    existing = ["assets/index-OLD.js", "assets/index-abc123.js", "index.html"]
    assert stale_assets(existing, upload_plan(dist)) == ["assets/index-OLD.js"]
