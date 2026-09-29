"""サンプル問題を作る（または作り直す）。

app/samples.json の文章から音声を作り、S3 の samples/ の下に置き、
DynamoDB に TTL なしで保存する。何度実行しても同じ ID で上書きされる。

使い方（backend ディレクトリで）:
    ..\\.venv\\Scripts\\python.exe scripts\\create_samples.py [スタック名]

Polly を 1 問あたり 2 回呼ぶ（2 問で 1 円未満）。Bedrock は使わない。
先に template.yaml のライフサイクル変更（audio/ だけを 1 日で消す）を
デプロイしておくこと。でないと samples/ の音声も 1 日で消える。
"""

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from dev import OUTPUT_TO_ENV, REGION, load_stack_outputs  # noqa: E402


def main() -> None:
    stack_name = sys.argv[1] if len(sys.argv) > 1 else "shoki-master"
    outputs = load_stack_outputs(stack_name)
    for key, env in OUTPUT_TO_ENV.items():
        os.environ[env] = outputs[key]

    # 環境変数を入れてから読み込む（config.py は読み込み時に環境変数を見る）
    from app import config
    from app.repositories.audio import AudioStorage
    from app.repositories.problems import ProblemRepository
    from app.samples import load_samples, sample_audio_key
    from app.services.speech import SpeechSynthesizer

    speech = SpeechSynthesizer(region_name=REGION)
    storage = AudioStorage(config.AUDIO_BUCKET, region_name=REGION)
    repo = ProblemRepository(region_name=REGION)

    durations: dict[str, int] = {}
    for sample in load_samples():
        synthesis = speech.synthesize(sample.text)
        durations[sample.problem_id] = synthesis.duration_ms
        key = storage.put(sample.problem_id, synthesis.audio, key=sample_audio_key(sample.problem_id))
        repo.save_problem(
            problem_id=sample.problem_id,
            mode=sample.mode,
            theme=sample.theme,
            target_length=len(sample.text),
            info="",
            text=sample.text,
            sentences=synthesis.sentences,
            audio_key=key,
            duration_ms=synthesis.duration_ms,
            expires=False,
        )
        print(
            f"{sample.problem_id}  {sample.mode:<13} {len(sample.text):>3} 字 / "
            f"{len(synthesis.sentences)} 文 / {synthesis.duration_ms / 1000:.1f} 秒  -> s3://{config.AUDIO_BUCKET}/{key}"
        )

    # 一覧 API がデータベースを読まずに長さを返せるよう、定義ファイルに書き戻す
    samples_file = BACKEND_DIR / "app" / "samples.json"
    definitions = json.loads(samples_file.read_text(encoding="utf-8"))
    for definition in definitions:
        definition["duration_ms"] = durations[definition["problem_id"]]
    text = json.dumps(definitions, ensure_ascii=False, indent=2) + "\n"
    samples_file.write_text(text, encoding="utf-8")
    print(f"音声の長さを {samples_file.name} に書き戻しました")


if __name__ == "__main__":
    main()
