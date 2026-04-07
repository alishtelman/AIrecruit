from app.core.rate_limit import InMemoryRateLimiter, match_rule


def test_match_rule_covers_critical_endpoints():
    assert match_rule("POST", "/api/v1/auth/login") is not None
    assert match_rule("POST", "/api/v1/interviews/start") is not None
    assert match_rule("POST", "/api/v1/interviews/123e4567-e89b-12d3-a456-426614174000/message") is not None
    assert match_rule("POST", "/api/v1/tts") is not None
    assert match_rule("POST", "/api/v1/stt") is not None
    assert match_rule("GET", "/api/v1/auth/login") is None


def test_in_memory_limiter_blocks_after_limit():
    limiter = InMemoryRateLimiter()
    key = ("auth_login", "127.0.0.1")

    for _ in range(3):
        allowed, retry_after = limiter.allow(key=key, limit=3, window_seconds=60)
        assert allowed is True
        assert retry_after == 0

    allowed, retry_after = limiter.allow(key=key, limit=3, window_seconds=60)
    assert allowed is False
    assert retry_after >= 1
