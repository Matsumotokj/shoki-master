"""実行環境から与える設定。

テーブル名やバケット名はインフラ（SAM）が決めるため、環境変数で受け取る。
コードに直接書くと、環境を作り直したときにコードの修正が必要になる。
"""

import os

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

PROBLEMS_TABLE = os.environ.get("PROBLEMS_TABLE", "shoki-master-problems")
ATTEMPTS_TABLE = os.environ.get("ATTEMPTS_TABLE", "shoki-master-attempts")
COUNTERS_TABLE = os.environ.get("COUNTERS_TABLE", "shoki-master-counters")
AUDIO_BUCKET = os.environ.get("AUDIO_BUCKET", "")

# 保存したデータを消すまでの時間。題材・回答・音声のいずれも使い捨てとする。
TTL_SECONDS = 24 * 60 * 60

# 音声を配信する署名付き URL の有効期限
AUDIO_URL_EXPIRES_SECONDS = 60 * 60

# 作問数の上限（要件 N2-3）。日次はバースト制限、月次が月額を抑える本体。
DAILY_PROBLEM_LIMIT = int(os.environ.get("DAILY_PROBLEM_LIMIT", "30"))
MONTHLY_PROBLEM_LIMIT = int(os.environ.get("MONTHLY_PROBLEM_LIMIT", "200"))

# 要約の採点回数の上限。採点は毎回 Bedrock を呼ぶ（約 0.5 円）が、再挑戦（要件 F3-4）や
# サンプル問題では作問を伴わないため、作問数の上限では止まらない。月 600 回で約 300 円
DAILY_REVIEW_LIMIT = int(os.environ.get("DAILY_REVIEW_LIMIT", "100"))
MONTHLY_REVIEW_LIMIT = int(os.environ.get("MONTHLY_REVIEW_LIMIT", "600"))
