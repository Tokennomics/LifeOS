import datetime

from modules.horizon import planner
from modules.reconnect import decay
from modules.steward import actions, scanners
from modules.voiceos import capture


def _backdate_entity(graph, entity_id, days):
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    graph._execute("UPDATE entities SET created_at = ? WHERE id = ?", (past, entity_id))
    graph.conn.commit()


def _seed_all_three(graph):
    s = graph.session("horizon", {"tasks:write"})
    stale = s.create_entity("task", {"title": "renew the thing", "status": "open", "if_then": ""}, source="seed")
    _backdate_entity(graph, stale, 20)
    capture.capture("must renew car insurance before rego", graph)
    person = decay.add_person(graph, "Ghosted Gary")
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)).isoformat()
    graph.session("reconnect", decay.SCOPES).update_entity(person, {"last_contact": past}, source="seed")
    return stale


def test_scan_finds_all_three_signals_and_dedupes(graph):
    _seed_all_three(graph)
    seen = []
    graph.bus.subscribe("admin.detected", lambda t, p: seen.append(p))
    first = scanners.scan(graph)
    assert first["created"] == 3
    assert {p["type"] for p in seen} == {"stale_task", "admin_capture", "reconnect"}
    again = scanners.scan(graph)
    assert again["created"] == 0  # open items are not re-surfaced
    assert len(actions.open_items(graph)) == 3


def test_approve_stale_task_schedules_it(graph):
    stale = _seed_all_three(graph)
    scanners.scan(graph)
    item = next(i for i in actions.open_items(graph) if i["type"] == "stale_task")
    result = actions.approve(graph, item["id"])
    assert "scheduled" in result["outcome"]
    task = graph.session("horizon", {"tasks:read"}).get_entity(stale)
    assert task["attrs"]["week"] == planner.week_id()
    assert all(i["id"] != item["id"] for i in actions.open_items(graph))


def test_approve_reconnect_creates_task_and_dismiss_closes(graph):
    _seed_all_three(graph)
    scanners.scan(graph)
    items = actions.open_items(graph)
    reconnect_item = next(i for i in items if i["type"] == "reconnect")
    capture_item = next(i for i in items if i["type"] == "admin_capture")

    actions.approve(graph, reconnect_item["id"])
    week_titles = [t["attrs"]["title"] for t in planner.week_tasks(graph)]
    assert any("Ghosted Gary" in t for t in week_titles)

    actions.dismiss(graph, capture_item["id"])
    remaining = actions.open_items(graph)  # only the untouched stale_task stays open
    assert [i["type"] for i in remaining] == ["stale_task"]
