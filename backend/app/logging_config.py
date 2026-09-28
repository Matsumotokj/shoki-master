"""ログを 1 行 1 JSON で出力する。

標準の書式では logger.info(..., extra={...}) の extra が表示されない。
JSON にしておくと、ローカルでは目で読め、Lambda 上では CloudWatch Logs の
検索（Logs Insights）で total_ms などの項目を条件や集計に使える。
"""

import json
import logging
import sys

# LogRecord が最初から持っている属性。これ以外が extra で渡された項目。
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """アプリのロガー（app.*）に JSON の出力先を付ける。何度呼んでも重複しない。"""
    logger = logging.getLogger("app")
    if any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    # Lambda のランタイムがルートロガーに付ける出力先と、二重に出さないため
    logger.propagate = False
