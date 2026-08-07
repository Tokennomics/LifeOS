"""Outbound HTTP that cannot be pointed at the machine it is running on.

Three features now fetch a URL a *user* chose: venue feeds, feed discovery, and ICS
calendar sync. On a laptop that is harmless. On a hosted box it is server-side request
forgery — the attacker does not need to reach the internal network, they just ask the
server to reach it for them, and the server has credentials and a private IP that they
do not.

The specific thing this stops, because it is not hypothetical: every major cloud exposes an
unauthenticated metadata service on `169.254.169.254` that hands out instance credentials to
anything on the box that asks. Render, Fly, AWS, GCP, DigitalOcean — all of them. A feed URL
of `http://169.254.169.254/latest/meta-data/iam/security-credentials/` is a complete
credential theft with no exploit code involved.

So:

- **Only http and https.** `file://`, `gopher://` and friends are not feeds.
- **The resolved ADDRESS is checked, not the hostname.** Blocking "localhost" by name is
  theatre: `127.0.0.1` has a thousand spellings (`127.1`, `2130706433`, `0x7f.1`,
  `localtest.me`, any attacker-controlled DNS record). Resolving first and judging the IP is
  the only check that holds.
- **Every redirect hop is re-checked.** A URL that passes on `example.com` and then 302s to
  the metadata service would otherwise sail straight through — which is why
  `follow_redirects=True` was the dangerous part of the original one-liner.
- **Responses are capped.** A "feed" that streams forever is a memory exhaustion bug, and
  nobody's event calendar is 50 MB.

`LIFEOS_ALLOW_PRIVATE_FETCH=1` disables the address check, for the NucBox case where the
calendar genuinely is on the LAN. It is off by default because the person who needs it knows
they need it, and the person who gets exploited by it does not.
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOW_PRIVATE_VAR = "LIFEOS_ALLOW_PRIVATE_FETCH"
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 30


class UnsafeURL(ValueError):
    """A URL that points somewhere the server must not be aimed."""


def _allow_private() -> bool:
    return str(os.environ.get(ALLOW_PRIVATE_VAR, "")).strip().lower() in {"1", "true", "yes", "on"}


def _addresses(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except (socket.gaierror, UnicodeError, ValueError):
        raise UnsafeURL(f"cannot resolve {host!r}")


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # `is_global` is False for loopback, private, link-local (169.254.0.0/16 — the metadata
    # service), reserved, multicast and unspecified, which is exactly the set to refuse.
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> str:
    """Raise `UnsafeURL` unless this is a public http(s) address. Returns the url."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL(f"only http(s) urls are fetched, not {parsed.scheme or 'that'!r}")
    if not parsed.hostname:
        raise UnsafeURL("no host in url")
    if _allow_private():
        return url
    for address in _addresses(parsed.hostname):
        if not _is_public(address):
            raise UnsafeURL(
                f"{parsed.hostname} resolves to {address}, which is not a public address "
                f"(set {ALLOW_PRIVATE_VAR}=1 if this is deliberate)")
    return url


def fetch_text(url: str, *, timeout: int = TIMEOUT, max_bytes: int = MAX_BYTES,
               max_redirects: int = MAX_REDIRECTS) -> str:
    """GET a public URL as text, re-checking the destination at every redirect."""
    import httpx

    seen = url
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            check_url(seen)
            response = client.get(seen)
            if response.is_redirect and response.headers.get("location"):
                seen = str(response.next_request.url) if response.next_request else ""
                if not seen:
                    raise UnsafeURL("redirect without a destination")
                continue
            response.raise_for_status()
            content = response.content[:max_bytes]
            return content.decode(response.encoding or "utf-8", errors="replace")
    raise UnsafeURL(f"too many redirects (> {max_redirects})")


def fetch_json(url: str, params: dict | None = None, *, timeout: int = TIMEOUT) -> dict:
    """Same guarantees, for the Tier 2 provider APIs."""
    import httpx

    check_url(url)
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        response = client.get(url, params=params or {})
        response.raise_for_status()
        return response.json()
