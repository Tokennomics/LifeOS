"""Telegram surface — v0.1: echo + /vision passthrough, long-polling (no webhook, no public IP).

Run:  .venv\\Scripts\\python -m surfaces.bot.telegram
Needs TELEGRAM_BOT_TOKEN in the environment (create a bot via @BotFather).
"""

import sys
import time

import httpx

from gateway.claude import ClaudeGateway
from modules.horizon import vision_intake
from substrate import load_config
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate

HELP = (
    "Life OS v0.1\n"
    "/vision <your vision + goals> — turn it into a life plan in the graph\n"
    "/help — this message\n"
    "Anything else is echoed back (gateway wiring check)."
)


class TelegramBot:
    def __init__(self, cfg: dict, graph: Graph | None = None, claude: ClaudeGateway | None = None):
        tg = cfg.get("telegram", {})
        self.token = tg.get("token", "")
        self.allowed = {int(x) for x in tg.get("allowed_user_ids") or []}
        self.cfg = cfg
        self.graph = graph
        self.claude = claude or ClaudeGateway(cfg)

    def _ensure_graph(self) -> Graph:
        if self.graph is None:
            conn = migrate(self.cfg)
            self.graph = Graph(conn, Bus(), default_owner=self.cfg.get("owner", {}).get("id"))
        return self.graph

    def handle_update(self, update: dict) -> tuple[int, str] | None:
        """Returns (chat_id, reply_text) or None if the update should be ignored."""
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        user_id = (message.get("from") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return None
        if self.allowed and user_id not in self.allowed:
            print(f"[telegram] ignored message from unauthorized user {user_id}")
            return None
        if not self.allowed:
            print(f"[telegram] accepted user {user_id} — pin allowed_user_ids: [{user_id}] in config.yaml")

        if text in ("/start", "/help"):
            return chat_id, HELP
        if text.startswith("/vision"):
            payload = text[len("/vision"):].strip()
            if not payload:
                return chat_id, "Usage: /vision <where you want to be, and the goals that get you there>"
            result = vision_intake.intake(payload, self._ensure_graph(), claude=self.claude)
            return chat_id, vision_intake.format_summary(result)
        return chat_id, f"echo: {text}"

    # ---- transport -------------------------------------------------------

    def _api(self, method: str, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        resp = httpx.post(url, json=params, timeout=70)
        resp.raise_for_status()
        return resp.json()

    def run(self):
        if not self.token:
            sys.exit("Set TELEGRAM_BOT_TOKEN (create a bot via @BotFather) and retry.")
        print("[telegram] long-polling started")
        offset = 0
        while True:
            try:
                data = self._api("getUpdates", offset=offset, timeout=50)
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    try:
                        handled = self.handle_update(update)
                    except Exception as exc:  # keep the loop alive; surface the error in chat
                        chat_id = ((update.get("message") or {}).get("chat") or {}).get("id")
                        handled = (chat_id, f"error: {exc}") if chat_id else None
                    if handled:
                        chat_id, reply = handled
                        self._api("sendMessage", chat_id=chat_id, text=reply)
            except KeyboardInterrupt:
                print("[telegram] stopped")
                return
            except Exception as exc:
                print(f"[telegram] transport error, retrying in 3s: {exc}")
                time.sleep(3)


def main():
    cfg = load_config()
    TelegramBot(cfg).run()


if __name__ == "__main__":
    main()
