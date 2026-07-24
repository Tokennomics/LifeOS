import pytest

from modules.horizon import gate
from surfaces.bot.telegram import TelegramBot


@pytest.fixture(autouse=True)
def _gate_passed(monkeypatch):
    # Isolate the bot's plan/log/retro loop from the gate floor.
    monkeypatch.setattr(gate, "gate_status", lambda g: {"cleared": True})


def _update(text, user_id=42, chat_id=42):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": text}}


def test_echo(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    chat_id, reply = bot.handle_update(_update("hello lifeos"))
    assert chat_id == 42
    assert reply == "echo: hello lifeos"


def test_help(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    _, reply = bot.handle_update(_update("/start"))
    assert "/vision" in reply


def test_vision_command_offline(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    _, reply = bot.handle_update(_update("/vision Freedom\n- ship v0.1"))
    assert "Plan created" in reply
    s = graph.session("horizon", {"goals:read"})
    assert len(s.find_entities("goal")) == 2  # vision + 1 goal


def test_unauthorized_user_ignored(cfg, graph):
    cfg["telegram"]["allowed_user_ids"] = [7]
    bot = TelegramBot(cfg, graph=graph)
    assert bot.handle_update(_update("hi", user_id=42)) is None
    assert bot.handle_update(_update("hi", user_id=7)) is not None


def test_week_loop_commands(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    s = graph.session("horizon", {"tasks:write"})
    s.create_entity("task", {"title": "Ship it", "status": "open", "if_then": ""}, source="seed")

    _, plan = bot.handle_update(_update("/plan"))
    assert "1. [ ] Ship it" in plan
    _, logged = bot.handle_update(_update("/log 1"))
    assert "Done: Ship it" in logged
    _, retro_text = bot.handle_update(_update("/retro"))
    assert "1/1 tasks done (100%)" in retro_text
    _, captured = bot.handle_update(_update("/capture remember the milk"))
    assert captured == "Captured."
    _, bad = bot.handle_update(_update("/log x"))
    assert bad.startswith("Usage:")


def test_focus_command_lists_and_toggles(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    bot.handle_update(_update("/vision Freedom\n- Alpha\n- Bravo"))
    _, listing = bot.handle_update(_update("/focus"))
    assert "Alpha" in listing and "Bravo" in listing
    _, toggled = bot.handle_update(_update("/focus 2"))
    assert "★ Bravo" in toggled


def test_non_message_updates_ignored(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    assert bot.handle_update({"update_id": 1}) is None
    assert bot.handle_update(_update("")) is None
