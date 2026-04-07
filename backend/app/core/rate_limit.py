from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    method: str
    pattern: re.Pattern[str]
    limit: int
    window_seconds: int = 60


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, key: tuple[str, str], limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, 0


def _rules() -> list[RateLimitRule]:
    return [
        RateLimitRule(
            name="auth_login",
            method="POST",
            pattern=re.compile(r"^/api/v1/auth/login$"),
            limit=settings.RATE_LIMIT_LOGIN_PER_MINUTE,
        ),
        RateLimitRule(
            name="interviews_start",
            method="POST",
            pattern=re.compile(r"^/api/v1/interviews/start$"),
            limit=settings.RATE_LIMIT_INTERVIEW_START_PER_MINUTE,
        ),
        RateLimitRule(
            name="interviews_message",
            method="POST",
            pattern=re.compile(r"^/api/v1/interviews/[0-9a-fA-F-]+/message$"),
            limit=settings.RATE_LIMIT_INTERVIEW_MESSAGE_PER_MINUTE,
        ),
        RateLimitRule(
            name="tts",
            method="POST",
            pattern=re.compile(r"^/api/v1/tts$"),
            limit=settings.RATE_LIMIT_TTS_PER_MINUTE,
        ),
        RateLimitRule(
            name="stt",
            method="POST",
            pattern=re.compile(r"^/api/v1/stt$"),
            limit=settings.RATE_LIMIT_STT_PER_MINUTE,
        ),
    ]


def match_rule(method: str, path: str) -> RateLimitRule | None:
    upper_method = method.upper()
    for rule in _rules():
        if rule.method == upper_method and rule.pattern.match(path):
            return rule
    return None


rate_limiter = InMemoryRateLimiter()
