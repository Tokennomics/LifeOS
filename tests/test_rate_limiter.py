import pytest
from gateway.rate_limiter import RateLimiter


def test_rate_limiter_enforcement():
    limiter = RateLimiter()
    ip = "192.168.1.100"
    endpoint = "/v1/auth/sso/login"

    # Allow first 3 requests (max_requests = 3)
    r1 = limiter.check_rate_limit(ip, endpoint, max_requests=3, window_seconds=60)
    assert r1["allowed"] is True
    assert r1["remaining"] == 2

    r2 = limiter.check_rate_limit(ip, endpoint, max_requests=3, window_seconds=60)
    assert r2["allowed"] is True

    r3 = limiter.check_rate_limit(ip, endpoint, max_requests=3, window_seconds=60)
    assert r3["allowed"] is True

    # 4th request blocked
    r4 = limiter.check_rate_limit(ip, endpoint, max_requests=3, window_seconds=60)
    assert r4["allowed"] is False
    assert r4["remaining"] == 0

    # Reset limiter
    limiter.reset_rate_limit(ip)
    r5 = limiter.check_rate_limit(ip, endpoint, max_requests=3, window_seconds=60)
    assert r5["allowed"] is True
