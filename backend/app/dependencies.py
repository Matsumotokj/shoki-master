"""本物の部品を組み立てて ProblemService を作る。

テストでは FastAPI の dependency_overrides でこの関数ごと差し替え、偽物の部品を使う。
"""

from functools import lru_cache

from app import config
from app.repositories.audio import AudioStorage
from app.repositories.problems import ProblemRepository
from app.repositories.usage import UsageLimiter
from app.services.bedrock import BedrockClient
from app.services.problem_service import ProblemService
from app.services.speech import SpeechSynthesizer


@lru_cache
def get_problem_service() -> ProblemService:
    """初回の呼び出しで 1 度だけ組み立て、以後は同じものを使い回す。

    Lambda は 1 つの実行環境を複数のリクエストで再利用するので、AWS の
    クライアントを毎回作り直さずに済む（接続の確立や認証情報の取得が省ける）。
    """
    if not config.AUDIO_BUCKET:
        raise RuntimeError("環境変数 AUDIO_BUCKET が設定されていません")
    return ProblemService(
        llm=BedrockClient(region_name=config.REGION),
        speech=SpeechSynthesizer(region_name=config.REGION),
        audio=AudioStorage(config.AUDIO_BUCKET, region_name=config.REGION),
        repo=ProblemRepository(region_name=config.REGION),
        usage=UsageLimiter(region_name=config.REGION),
    )
