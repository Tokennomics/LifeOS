"""Telegram surface — v0.1: echo + /vision passthrough, long-polling (no webhook, no public IP).

Run:  .venv\\Scripts\\python -m surfaces.bot.telegram
Needs TELEGRAM_BOT_TOKEN in the environment (create a bot via @BotFather).
"""

import sys
import time

import httpx

from gateway.claude import ClaudeGateway
from modules.horizon import gate, planner, retro, vision_intake
from modules.voiceos import capture as voice_capture
from substrate import load_config
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate
from surfaces.bot.scheduler import Scheduler

HELP = (
    "Life OS v0.1\n"
    "/vision <vision + goals> — backcast it into a life plan in the graph\n"
    "/plan — plan this week (3-7 if-then tasks)\n"
    "/log <n> — mark task n of this week done\n"
    "/retro — score the week + reflection\n"
    "/capture <thought> — capture into the graph (tasks/people/interests extracted)\n"
    "/parked — new-project ideas you parked (captured, not abandoned)\n"
    "/gate — v0.1 gate progress: days used, logs, retros\n"
    "/help — this message\n"
    "Anything else is echoed back (wiring check)."
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
        if text.startswith("/plan"):
            baseline = self.cfg.get("vitals", {}).get("energy_baseline", "tired")
            result = planner.plan_week(self._ensure_graph(), claude=self.claude, energy_baseline=baseline)
            return chat_id, planner.format_week(self._ensure_graph(), result["week"])
        if text.startswith("/log"):
            arg = text[len("/log"):].strip()
            if not arg.isdigit():
                return chat_id, "Usage: /log <task number from /plan>"
            try:
                title = planner.log_done(self._ensure_graph(), int(arg))
            except ValueError as exc:
                return chat_id, str(exc)
            return chat_id, f"Done: {title} ✔"
        if text.startswith("/retro"):
            return chat_id, retro.run_retro(self._ensure_graph(), claude=self.claude)["text"]
        if text.startswith("/capture"):
            payload = text[len("/capture"):].strip()
            if not payload:
                return chat_id, "Usage: /capture <the thought>"
            result = voice_capture.capture(payload, self._ensure_graph(), claude=self.claude)
            return chat_id, voice_capture.format_summary(result)
        if text.startswith("/parked"):
            items = voice_capture.list_parked(self._ensure_graph())
            if not items:
                return chat_id, "No parked ideas. Distraction-free."
            lines = ["Parked ideas — captured, not abandoned:"]
            lines += [f"• {it['text']}" for it in items]
            return chat_id, "\n".join(lines)
        if text.startswith("/gate"):
            return chat_id, gate.gate_status(self._ensure_graph())["text"]
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
        if self.cfg.get("telegram", {}).get("owner_chat_id"):
            Scheduler(self, self.cfg, self._ensure_graph(), self.claude).start()
        else:
            print("[telegram] no owner_chat_id — Monday plan / Sunday retro pushes disabled. "
                  "Message the bot once, copy the logged id into TELEGRAM_OWNER_CHAT_ID.")
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
