"""Official LifeOS Developer Python SDK.

Zero-dependency SDK for developers to connect Python scripts, AI agents,
and home automation to LifeOS.
"""

import json
import urllib.request


class LifeOSClient:
    """Official LifeOS API Client."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, endpoint: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_today(self) -> dict:
        """Retrieves today's tasks, goals, and diurnal intent."""
        return self._request("GET", "/v1/today")

    def capture_voice(self, text: str) -> dict:
        """Transcribes thoughts into graph entities."""
        return self._request("POST", "/v1/voiceos/capture", {"text": text})

    def get_crews(self) -> dict:
        """Retrieves active crews and members."""
        return self._request("GET", "/v1/crews")

    def get_treasury(self) -> dict:
        """Retrieves 20% Community Impact Treasury status."""
        return self._request("GET", "/v1/treasury/status")
