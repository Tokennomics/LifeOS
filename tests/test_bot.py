from surfaces.bot.telegram import TelegramBot


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


def test_non_message_updates_ignored(cfg, graph):
    bot = TelegramBot(cfg, graph=graph)
    assert bot.handle_update({"update_id": 1}) is None
    assert bot.handle_update(_update("")) is None
