from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler

from core.config import LoggingSettings

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*)(basic|bearer)\s+[^\s]+"),
    re.compile(r"(?i)(cookie\s*:\s*)[^\s]+"),
    re.compile(r"(?i)(password(?:_hash)?\s*[=:]\s*)[^\s]+"),
]


def sanitize_log_message(message: str) -> str:
    sanitized = message
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    return sanitized


@dataclass
class LogDiagnostics:
    write_failures: int = 0
    dropped_records: int = 0


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize_log_message(record.getMessage())
        record.args = ()
        return True


class SafeRotatingFileHandler(RotatingFileHandler):
    def __init__(self, *args: object, diagnostics: LogDiagnostics, **kwargs: object) -> None:
        self.diagnostics = diagnostics
        super().__init__(*args, **kwargs)

    def handleError(self, record: logging.LogRecord) -> None:
        self.diagnostics.write_failures += 1
        super().handleError(record)


def configure_logging(settings: LoggingSettings) -> LogDiagnostics:
    settings.path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = LogDiagnostics()
    handler = SafeRotatingFileHandler(
        settings.path,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
        diagnostics=diagnostics,
    )
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter('{"level":"%(levelname)s","message":"%(message)s"}'))
    logger = logging.getLogger("repair_ai_image")
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return diagnostics
