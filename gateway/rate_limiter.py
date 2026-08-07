"""Gateway rate limiter and brute-force defence.

In-memory sliding window, per (client, endpoint).

**This file existed for a while and was imported by nothing.** The docstring claimed
protection against "DDoS, brute-force authentication, and API abuse" while `/v1/auth/login`
took unlimited guesses — 60 wrong passwords in a row, 60 × HTTP 401, no back-off. Same
shape as the published signing key: a security control that was real on paper and absent in
the request path. `enforce()` below is the missing half, and it is wired into login,
registration and the outbound-fetch endpoints in `gateway/main.py`.

**Known limits, stated so nobody over-trusts it again.** It is per-process and in-memory, so
it resets on restart and does not coordinate across replicas — fine for one container, not a
substitute for a WAF or for fail2ban at the edge. It keys on the client address, so a NAT'd
office shares a bucket and an attacker with many addresses gets many buckets. It raises the
cost of guessing; it does not make guessing impossible.
"""

import os
import time
from collections import defaultdict

from fastapi import HTTPException, Request

DISABLE_VAR = "LIFEOS_DISABLE_RATE_LIMIT"      # for tests and single-user local runs


class RateLimiter:
    """Sliding window rate limiter tracking request timestamps per key."""

    def __init__(self):
        # key -> list of float timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(self, client_ip: str, endpoint: str, max_requests: int = 100,
                         window_seconds: int = 60) -> dict:
        """Checks if a request from client_ip to endpoint exceeds rate limits."""
        key = f"{client_ip}:{endpoint}"
        now = time.time()
        window_start = now - window_seconds

        # Prune old timestamps
        timestamps = [t for t in self._requests[key] if t > window_start]
        self._requests[key] = timestamps

        if len(timestamps) >= max_requests:
            oldest = timestamps[0] if timestamps else now
            reset_seconds = max(1, int(window_seconds - (now - oldest)))
            return {
                "allowed": False,
                "remaining": 0,
                "reset_seconds": reset_seconds,
                "limit": max_requests,
            }

        timestamps.append(now)
        self._requests[key] = timestamps
        remaining = max(0, max_requests - len(timestamps))

        return {
            "allowed": True,
            "remaining": remaining,
            "reset_seconds": window_seconds,
            "limit": max_requests,
        }

    def reset_rate_limit(self, client_ip: str | None = None) -> None:
        """Resets rate limit counters for a client IP or completely."""
        if client_ip:
            keys_to_del = [k for k in self._requests if k.startswith(f"{client_ip}:")]
            for k in keys_to_del:
                del self._requests[k]
        else:
            self._requests.clear()


# Global rate limiter instance
limiter = RateLimiter()


def client_key(request: Request) -> str:
    """Who to count against.

    `X-Forwarded-For` is honoured because the deployment puts Caddy in front and the socket
    address would otherwise be the proxy for every caller — one bucket for the whole
    internet, which is worse than no limit at all. It is only ever the LAST hop that can be
    trusted, and a header a client sets directly is a lie; behind a known proxy the leftmost
    entry is the real client, so that is what is used. If this is ever exposed without a
    proxy in front, drop the header.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def for_app(request: Request) -> RateLimiter:
    """The limiter belonging to THIS app instance.

    A module-level singleton was the first version and it was wrong in a way that showed up
    immediately: counters outlived the app that created them, so a second gateway in the same
    process inherited the first one's buckets. Harmless in production (one app per process)
    and quietly wrong everywhere else — it made six unrelated tests fail by exhausting a
    shared quota, which is exactly what it would do to a batch job or an embedded instance.
    """
    state = getattr(request.app, "state", None)
    existing = getattr(state, "rate_limiter", None)
    if existing is None:
        existing = RateLimiter()
        if state is not None:
            state.rate_limiter = existing
    return existing


def enforce(request: Request, endpoint: str, max_requests: int, window_seconds: int) -> None:
    """Count this request, and raise 429 when the window is full."""
    if str(os.environ.get(DISABLE_VAR, "")).strip().lower() in {"1", "true", "yes", "on"}:
        return
    verdict = for_app(request).check_rate_limit(client_key(request), endpoint,
                                                max_requests=max_requests,
                                                window_seconds=window_seconds)
    if not verdict["allowed"]:
        raise HTTPException(
            status_code=429, detail=f"too many requests — try again in {verdict['reset_seconds']}s",
            headers={"Retry-After": str(verdict["reset_seconds"])})
