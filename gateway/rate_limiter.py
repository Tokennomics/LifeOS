"""Gateway Rate Limiter & Brute-Force Defense Core.

In-memory sliding window rate limiter protecting endpoints against DDoS,
brute-force authentication, and API abuse.
"""

from collections import defaultdict
import time


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
