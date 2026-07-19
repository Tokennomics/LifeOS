"""Server-side Claude calls — the single choke point for models, caching, and budgets.

Routing per master doc §3.2: heavy model (claude-opus-4-8) for planning/intake,
light model (claude-haiku-4-5) for classification. System prompts are cached with
cache_control (prefix caching); keep them byte-stable — put volatile content in the
user turn, never in the system prompt.
"""

import json
import os

DEFAULT_HEAVY = "claude-opus-4-8"
DEFAULT_LIGHT = "claude-haiku-4-5"


class ClaudeGateway:
    def __init__(self, cfg: dict | None = None):
        a = (cfg or {}).get("anthropic", {})
        self.api_key = a.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model_heavy = a.get("model_heavy") or DEFAULT_HEAVY
        self.model_light = a.get("model_light") or DEFAULT_LIGHT
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def client(self):
        if self._client is None:
            import anthropic

            # Zero-arg resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login` profile.
            self._client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str, *, model: str | None = None,
                 max_tokens: int = 16000) -> str:
        response = self.client().messages.create(
            model=model or self.model_heavy,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request (stop_reason=refusal)")
        return "".join(b.text for b in response.content if b.type == "text")

    def complete_json(self, system: str, user: str, *, schema: dict, model: str | None = None,
                      max_tokens: int = 16000) -> dict:
        """Structured output constrained to a JSON schema (guaranteed parseable)."""
        response = self.client().messages.create(
            model=model or self.model_heavy,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request (stop_reason=refusal)")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    def classify(self, system: str, user: str, *, schema: dict) -> dict:
        """Light-model structured classification (COGS: small-model routing)."""
        return self.complete_json(system, user, schema=schema, model=self.model_light, max_tokens=256)
