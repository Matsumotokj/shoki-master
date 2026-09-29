"""API の仕様書（OpenAPI）を docs/openapi.json に書き出す。

フロントエンドはこのファイルから TypeScript の型を生成する（frontend で npm run gen:api）。
バックエンドの型を変えたら、これを実行し直してから型を生成し直すと、
フロントのずれがコンパイルエラーとして見える。

使い方（backend ディレクトリで）:
    ..\\.venv\\Scripts\\python.exe scripts\\export_openapi.py
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

OUTPUT = BACKEND_DIR.parent / "docs" / "openapi.json"


def main() -> None:
    OUTPUT.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(BACKEND_DIR.parent)}")


if __name__ == "__main__":
    main()
