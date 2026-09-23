"""題材生成と要約採点を実際に呼び、品質と所要時間を確かめる。

課金が発生するため手動で実行する。既定では題材生成を 1 回だけ行う。

使い方:
    python scripts/try_generation.py [目標文字数] [--review]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.bedrock import BedrockClient  # noqa: E402
from app.services.script_generation import generate_script  # noqa: E402
from app.services.summary_review import review_summary  # noqa: E402

THEME = "IT企業の株主総会で、社長が四半期の業績を報告するスピーチ"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target_length = int(args[0]) if args else 300
    with_review = "--review" in sys.argv

    client = BedrockClient()

    started = time.perf_counter()
    text = generate_script(client, theme=THEME, target_length=target_length)
    elapsed = time.perf_counter() - started

    print(f"--- 題材生成 ---")
    print(f"所要時間: {elapsed:.1f} 秒 / 目標 {target_length} 文字 → 実際 {len(text)} 文字")
    print(text)
    print()

    if not with_review:
        return

    summary = text[: max(40, len(text) // 3)]
    started = time.perf_counter()
    review = review_summary(client, source_text=text, summary=summary)
    elapsed = time.perf_counter() - started

    print(f"--- 要約採点（元文の冒頭を要約として渡した場合）---")
    print(f"所要時間: {elapsed:.1f} 秒")
    print(f"素点: {review.score_raw} (忠実性{review.faithfulness}/網羅性{review.coverage}/明瞭{review.clarity})")
    print(f"ハルシネーション: {review.hallucination}")
    print(f"総評: {review.notes}")
    print(f"模範要約: {review.best_summary}")


if __name__ == "__main__":
    main()
