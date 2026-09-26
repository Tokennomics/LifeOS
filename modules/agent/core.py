"""The agent — goals in, plans out, and nothing done without your say-so.

Meta's Muse (Connect, September 2026) set what people now expect a personal agent to do:
you hand it a goal, it breaks the goal into a plan, it remembers what you told it across
conversations, it checks back when something changes, and before anything consequential —
sending a message, spending money — it stops and asks. "Propose, authorise, execute."

LifeOS already had every part and no whole. Goals and milestones lived in Horizon, an
approval queue lived in Steward, grounded wording lived in `modules/ai/assist`, and none of
them talked. The weekly auto-drafter wrote the same two boilerplate tasks for every goal
("Draft execution milestones for '…'"), which is a plan in the sense that a form letter is a
letter. This module is the loop that joins them:

- **Goals → plans.** A goal in plain words becomes a `goal` row (the same kind the planner
  reads, so it flows into the week) with its steps as Horizon milestones. With a model the
  steps are drafted for this goal; without one you get three starter steps that are true of
  any goal and say they are starters. Nothing is presented as tailored that was not.
- **Memory you can read and delete.** Facts are stored because you said "remember", listed
  in full on request, and deleted outright by "forget". The model sees exactly this list and
  nothing inferred behind your back.
- **Check-ins.** What needs you, counted from rows: proposals waiting, deadlines close or
  passed, goals with no progress in a week, and each goal's next step.
- **Propose, authorise, execute.** Anything the agent wants to *do* becomes a pending
  proposal. Only an explicit approve runs it, only actions on a short whitelist can run at
  all, and an action this app cannot perform is never reported as performed: a drafted
  message comes back as a `mailto:`/`sms:` link for you to send, with `sent: False`.

Works with no API key. A key adds drafted plans and open-ended answers; without one the
agent says which of those it cannot do rather than filling the gap with prose.
"""

import datetime
import json
import re
from urllib.parse import quote

from modules.horizon import milestones
from modules.horizon.planner import week_id
from substrate.graph import Graph

MODULE = "agent"
SCOPES = {"goals:write", "tasks:write", "memories:write", "content:write", "events:read"}

MAX_STEPS = 7
MAX_FACTS = 200
MAX_TEXT = 500
STALL_DAYS = 7
DEADLINE_SOON_DAYS = 7

# True of any goal, and labelled as such. The no-key path must still leave you with a plan
# you can act on today, and inventing goal-specific steps without a model is the prop this
# module exists not to be.
STARTER_STEPS = (
    "Write one sentence saying what done looks like",
    "Pick the smallest first step — something under 15 minutes",
    "Put that first step on your calendar",
)

ACTIONS = {
    "add_task": "Add a task to this week's plan",
    "add_step": "Add a step to one of your goals",
    "remember": "Remember a fact about you",
    "draft_message": "Draft a message for you to send",
    "set_focus": "Make a goal this week's focus",
}

NEEDS_KEY = {
    "available": False,
    "capability": "open-ended answers",
    "why": "ANTHROPIC_API_KEY is not set, so there is no model to answer free-form questions",
    "needs": ["ANTHROPIC_API_KEY"],
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def _parse_date(text) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(text or "").strip()[:10])
    except ValueError:
        return None


def _clean(text, limit: int = MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _assisted(claude) -> bool:
    return bool(claude is not None and getattr(claude, "available", False))


# ---- memory --------------------------------------------------------------------

def remember(graph: Graph, text: str, *, source: str = MODULE) -> dict:
    fact = _clean(text)
    if not fact:
        raise ValueError("nothing to remember")
    session = _session(graph)
    for row in session.find_entities("memory", {"type": "agent_fact"}, limit=MAX_FACTS):
        if row["attrs"].get("text", "").lower() == fact.lower():
            return {"id": row["id"], "text": fact, "stored": False, "reason": "already remembered"}
    fact_id = session.create_entity("memory", {"type": "agent_fact", "text": fact}, source=source)
    return {"id": fact_id, "text": fact, "stored": True}


def facts(graph: Graph) -> list[dict]:
    rows = _session(graph).find_entities("memory", {"type": "agent_fact"}, limit=MAX_FACTS)
    rows.sort(key=lambda r: r.get("created_at", ""))
    return [{"id": r["id"], "text": r["attrs"].get("text", ""), "since": r.get("created_at", "")}
            for r in rows]


def forget(graph: Graph, fact_id: str, *, source: str = MODULE) -> dict:
    session = _session(graph)
    row = session.get_entity(fact_id)
    if row is None or row["kind"] != "memory" or row["attrs"].get("type") != "agent_fact":
        raise ValueError("unknown memory")
    session.delete_entity(fact_id, source=source)
    return {"id": fact_id, "forgotten": True}


def forget_matching(graph: Graph, phrase: str, *, source: str = MODULE) -> list[str]:
    needle = _clean(phrase).lower()
    if not needle:
        return []
    gone = []
    for fact in facts(graph):
        if needle in fact["text"].lower():
            forget(graph, fact["id"], source=source)
            gone.append(fact["text"])
    return gone


# ---- goals and plans -----------------------------------------------------------

_PLAN_SYSTEM = (
    "You break one personal goal into a short, concrete plan. You are given the goal, an "
    "optional deadline, and facts the person asked you to remember. Write 3 to 7 steps, in "
    "order, each doable by one person and each starting with a verb. The first step must "
    "take under 30 minutes. Never invent a person, a place, a price, a date or a detail that "
    "is not in the input; where the plan needs one, the step is to find it out. Plain words, "
    "no emoji."
)

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["steps", "note"],
    "additionalProperties": False,
}


def _draft_steps(title: str, deadline: str, remembered: list[str],
                 claude) -> tuple[list[str], str, bool]:
    if _assisted(claude):
        try:
            data = claude.complete_json(
                _PLAN_SYSTEM,
                json.dumps({"goal": title, "deadline": deadline,
                            "remembered": remembered}),
                schema=_PLAN_SCHEMA, max_tokens=1200)
            steps = [_clean(s, 200) for s in data.get("steps", []) if _clean(s, 200)]
            if steps:
                return steps[:MAX_STEPS], _clean(data.get("note", ""), 300), True
        except Exception:
            pass
    return list(STARTER_STEPS), (
        "Starter steps — true of any goal. Add your own, or set ANTHROPIC_API_KEY for a "
        "plan drafted for this goal."), False



def create_goal(graph: Graph, title: str, *, why: str = "", deadline: str = "",
                steps: list[str] | None = None, claude=None, source: str = MODULE) -> dict:
    """A goal with a plan attached. Your steps win; then a model's; then the starters."""
    title = _clean(title, 200)
    if not title:
        raise ValueError("a goal needs a title")
    if deadline and _parse_date(deadline) is None:
        raise ValueError("deadline must be a date, YYYY-MM-DD")
    session = _session(graph)
    given = [_clean(s, 200) for s in (steps or []) if _clean(s, 200)][:MAX_STEPS]
    if given:
        plan, note, assisted, planned_by = given, "", False, "you"
    else:
        remembered = [f["text"] for f in facts(graph)] if _assisted(claude) else []
        plan, note, assisted = _draft_steps(title, deadline, remembered, claude)
        planned_by = "model" if assisted else "starter"
    goal_id = session.create_entity("goal", {
        "title": title, "level": "goal", "why": _clean(why, 300), "deadline": deadline,
        "agent": True, "planned_by": planned_by, "focus": False,
    }, source=source)
    for step in plan:
        milestones.add_milestone(graph, goal_id, step, source=source)
    return {**goal(graph, goal_id), "assisted": assisted, "note": note}


def _steps(graph: Graph, goal_id: str) -> list[dict]:
    session = _session(graph)
    rows = [m for m in session.find_entities("content", {"type": "milestone"}, limit=500)
            if m["attrs"].get("goal_id") == goal_id]
    rows.sort(key=lambda r: r.get("created_at", ""))
    return [{"id": r["id"], "title": r["attrs"].get("title", ""),
             "done": r["attrs"].get("status") == "completed",
             "updated_at": r.get("updated_at", "")} for r in rows]


def goal(graph: Graph, goal_id: str) -> dict:
    row = _session(graph).get_entity(goal_id)
    if row is None or row["kind"] != "goal":
        raise ValueError("unknown goal")
    a = row["attrs"]
    steps = _steps(graph, goal_id)
    done = sum(1 for s in steps if s["done"])
    nxt = next((s for s in steps if not s["done"]), None)
    return {
        "id": goal_id, "title": a.get("title", ""), "why": a.get("why", ""),
        "deadline": a.get("deadline", ""), "focus": bool(a.get("focus")),
        "planned_by": a.get("planned_by", "you"), "status": a.get("status", "active"),
        "steps": steps, "done": done, "of": len(steps),
        "next_step": nxt, "created_at": row.get("created_at", ""),
    }


def goals(graph: Graph, *, include_done: bool = False) -> list[dict]:
    rows = _session(graph).find_entities("goal", {"level": "goal"}, limit=100)
    rows.sort(key=lambda r: r.get("created_at", ""))
    out = [goal(graph, r["id"]) for r in rows]
    return out if include_done else [g for g in out if g["status"] != "done"]


def complete_step(graph: Graph, step_id: str, *, source: str = MODULE) -> dict:
    row = _session(graph).get_entity(step_id)
    if row is None or row["attrs"].get("type") != "milestone":
        raise ValueError("unknown step")
    milestones.complete_milestone(graph, step_id, source=source)
    g = goal(graph, row["attrs"].get("goal_id", ""))
    if g["of"] and g["done"] == g["of"]:
        _session(graph).update_entity(g["id"], {"status": "done"}, source=source)
        g["status"] = "done"
    return g


def add_step(graph: Graph, goal_id: str, title: str, *, source: str = MODULE) -> dict:
    title = _clean(title, 200)
    if not title:
        raise ValueError("a step needs a title")
    goal(graph, goal_id)
    milestones.add_milestone(graph, goal_id, title, source=source)
    return goal(graph, goal_id)


# ---- check-in ------------------------------------------------------------------

def checkin(graph: Graph) -> dict:
    """What needs you, from rows. Every item says why it is here."""
    today = _now().date()
    items = []
    pending = proposals(graph)
    if pending:
        items.append({"kind": "approval", "why": f"{len(pending)} action"
                      f"{'' if len(pending) == 1 else 's'} waiting for your approval",
                      "proposal_ids": [p["id"] for p in pending]})
    active = goals(graph)
    for g in active:
        due = _parse_date(g["deadline"])
        if due and g["next_step"]:
            left = (due - today).days
            if left < 0:
                items.append({"kind": "overdue", "goal_id": g["id"],
                              "why": f"'{g['title']}' was due {g['deadline']} with "
                                     f"{g['of'] - g['done']} step(s) open"})
            elif left <= DEADLINE_SOON_DAYS:
                items.append({"kind": "deadline", "goal_id": g["id"],
                              "why": f"'{g['title']}' is due in {left} day"
                                     f"{'' if left == 1 else 's'} with "
                                     f"{g['of'] - g['done']} step(s) open"})
        # Progress is the last step ticked; a goal with none ticked dates from its creation.
        ticked = [t for t in (_parse(s["updated_at"]) for s in g["steps"] if s["done"]) if t]
        last = max(ticked) if ticked else _parse(g["created_at"])
        if g["next_step"] and last and (_now() - last).days >= STALL_DAYS:
            items.append({"kind": "stalled", "goal_id": g["id"],
                          "why": f"No step on '{g['title']}' in {(_now() - last).days} days"})
    week = week_id()
    open_tasks = [t for t in _session(graph).find_entities("task", {"week": week}, limit=100)
                  if t["attrs"].get("status") != "done"]
    next_steps = [{"goal_id": g["id"], "goal": g["title"], "step_id": g["next_step"]["id"],
                   "step": g["next_step"]["title"]} for g in active if g["next_step"]]
    return {
        "needs_you": items,
        "next_steps": next_steps,
        "open_tasks_this_week": len(open_tasks),
        "quiet": not items,
        "note": "Counted from your goals, steps, tasks and pending approvals.",
    }


def _checkin_text(c: dict) -> str:
    lines = [i["why"] for i in c["needs_you"]]
    for n in c["next_steps"][:3]:
        lines.append(f"Next on '{n['goal']}': {n['step']}")
    if not lines:
        return ("Nothing needs you right now. Tell me a goal and I will draft a plan, or say "
                "\"remember …\" and I will keep it.")
    return "\n".join(lines)


# ---- propose, authorise, execute -----------------------------------------------

def _validate(action: str, args: dict) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; the agent can only {sorted(ACTIONS)}")
    args = dict(args or {})
    if action in ("add_task", "add_step") and not _clean(args.get("title")):
        raise ValueError(f"{action} needs a title")
    if action in ("add_step", "set_focus") and not args.get("goal_id"):
        raise ValueError(f"{action} needs a goal_id")
    if action == "remember" and not _clean(args.get("text")):
        raise ValueError("remember needs text")
    if action == "draft_message":
        if not _clean(args.get("body")):
            raise ValueError("draft_message needs a body")
        if args.get("channel", "email") not in ("email", "sms"):
            raise ValueError("draft_message channel is email or sms")
    return args


def propose(graph: Graph, action: str, args: dict, summary: str = "", *,
            source: str = MODULE) -> dict:
    args = _validate(action, args)
    summary = _clean(summary, 200) or ACTIONS[action]
    pid = _session(graph).create_entity("content", {
        "type": "agent_proposal", "action": action, "args": args, "summary": summary,
        "status": "pending",
    }, source=source)
    return {"id": pid, "action": action, "args": args, "summary": summary, "status": "pending"}


def proposals(graph: Graph, status: str = "pending") -> list[dict]:
    rows = _session(graph).find_entities("content", {"type": "agent_proposal",
                                                      "status": status}, limit=100)
    rows.sort(key=lambda r: r.get("created_at", ""))
    return [{"id": r["id"], "action": r["attrs"].get("action"), "args": r["attrs"].get("args", {}),
             "summary": r["attrs"].get("summary", ""), "status": r["attrs"].get("status"),
             "result": r["attrs"].get("result")} for r in rows]


def _proposal(graph: Graph, proposal_id: str) -> dict:
    row = _session(graph).get_entity(proposal_id)
    if row is None or row["attrs"].get("type") != "agent_proposal":
        raise ValueError("unknown proposal")
    if row["attrs"].get("status") != "pending":
        raise ValueError(f"proposal is already {row['attrs'].get('status')}")
    return row


def _execute(graph: Graph, action: str, args: dict, source: str) -> dict:
    if action == "add_task":
        attrs = {"title": _clean(args["title"], 200), "status": "open", "week": week_id()}
        if args.get("goal_id"):
            goal(graph, args["goal_id"])
            attrs["goal_id"] = args["goal_id"]
        task_id = _session(graph).create_entity("task", attrs, source=source)
        return {"done": True, "task_id": task_id, "what": f"added '{attrs['title']}' to this week"}
    if action == "add_step":
        g = add_step(graph, args["goal_id"], args["title"], source=source)
        return {"done": True, "goal_id": g["id"], "what": f"added a step to '{g['title']}'"}
    if action == "remember":
        r = remember(graph, args["text"], source=source)
        return {"done": True, "memory_id": r["id"], "what": f"remembered: {r['text']}"}
    if action == "set_focus":
        g = goal(graph, args["goal_id"])
        _session(graph).update_entity(g["id"], {"focus": True}, source=source)
        return {"done": True, "goal_id": g["id"], "what": f"'{g['title']}' is this week's focus"}
    if action == "draft_message":
        # LifeOS has no outbound mail or SMS of its own. The approval hands you a link that
        # opens your own app with the draft filled in; you press send, or you do not.
        to = _clean(args.get("to"), 200)
        body = _clean(args.get("body"), 2000)
        if args.get("channel", "email") == "sms":
            link = f"sms:{quote(to)}?body={quote(body)}"
        else:
            subject = _clean(args.get("subject"), 200)
            link = f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body)}"
        return {"done": True, "sent": False, "open": link,
                "what": "draft ready — open it in your own app to send"}
    raise ValueError(f"unknown action {action!r}")


def approve(graph: Graph, proposal_id: str, *, source: str = MODULE) -> dict:
    row = _proposal(graph, proposal_id)
    a = row["attrs"]
    result = _execute(graph, a["action"], a.get("args", {}), source)
    _session(graph).update_entity(proposal_id, {"status": "approved", "result": result},
                                  source=source)
    return {"id": proposal_id, "status": "approved", "result": result}


def reject(graph: Graph, proposal_id: str, *, source: str = MODULE) -> dict:
    _proposal(graph, proposal_id)
    _session(graph).update_entity(proposal_id, {"status": "rejected"}, source=source)
    return {"id": proposal_id, "status": "rejected"}


# ---- conversation --------------------------------------------------------------

_REMEMBER = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?[:,]?\s+(.+)$", re.I | re.S)
_FORGET = re.compile(r"^\s*(?:please\s+)?forget(?:\s+that)?[:,]?\s+(.+)$", re.I | re.S)
_GOAL = re.compile(
    r"^\s*(?:new\s+goal|goal|my\s+goal\s+is(?:\s+to)?|i\s+want\s+to|i'd\s+like\s+to|"
    r"i\s+would\s+like\s+to|help\s+me(?:\s+to)?|plan)[:,]?\s+(.+)$", re.I | re.S)
_CHECKIN = re.compile(
    r"^\s*(?:check[\s-]?in|status|what'?s\s+next|what\s+is\s+next|what\s+needs\s+me|"
    r"what\s+should\s+i\s+do(?:\s+next|\s+now|\s+today)?)\s*\??\s*$", re.I)
_RECALL = re.compile(r"^\s*what\s+do\s+you\s+(?:know|remember)(?:\s+about\s+me)?\s*\??\s*$", re.I)
_BY = re.compile(r"\s+by\s+(\d{4}-\d{2}-\d{2})\s*\.?\s*$", re.I)

_ASK_SYSTEM = (
    "You are the user's personal agent inside LifeOS. You answer from the facts you are "
    "given — their goals and steps, this week's tasks, their calendar, and what they asked "
    "you to remember — and say plainly when those facts do not contain the answer. Never "
    "invent a person, place, time, price or event. You cannot send messages, book, buy or "
    "browse; when doing something would help, propose it using only these actions: "
    "add_task {title, goal_id?}, add_step {goal_id, title}, remember {text}, set_focus "
    "{goal_id}, draft_message {channel: email|sms, to, subject?, body}. Proposals wait for "
    "the user's approval; never say an action has happened. Reply in at most five short "
    "sentences, plain words, no emoji."
)

_ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "proposals": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(ACTIONS)},
                "summary": {"type": "string"},
                "args_json": {"type": "string"},
            },
            "required": ["action", "summary", "args_json"],
            "additionalProperties": False,
        }},
    },
    "required": ["reply", "proposals"],
    "additionalProperties": False,
}


def context(graph: Graph) -> dict:
    """Everything the model is shown, and nothing else. Public so it can be checked."""
    session = _session(graph)
    now = _now()
    events = []
    for ev in session.find_entities("event", limit=200):
        start = _parse(ev["attrs"].get("start", ""))
        if start and now <= start <= now + datetime.timedelta(days=7):
            events.append({"title": ev["attrs"].get("title", ""), "start": ev["attrs"]["start"]})
    events.sort(key=lambda e: e["start"])
    tasks = [{"title": t["attrs"].get("title", ""), "status": t["attrs"].get("status", "open")}
             for t in session.find_entities("task", {"week": week_id()}, limit=50)]
    return {
        "today": now.date().isoformat(),
        "remembered": [f["text"] for f in facts(graph)],
        "goals": [{"id": g["id"], "title": g["title"], "deadline": g["deadline"],
                   "steps": [{"title": s["title"], "done": s["done"]} for s in g["steps"]]}
                  for g in goals(graph)],
        "this_week": tasks,
        "next_7_days": events[:20],
        "pending_approvals": [p["summary"] for p in proposals(graph)],
    }


def ask(graph: Graph, message: str, *, claude=None) -> dict:
    """One turn. Plain commands work without a key; open questions need one, and say so."""
    text = _clean(message, 2000)
    if not text:
        raise ValueError("say something")

    m = _REMEMBER.match(text)
    if m:
        r = remember(graph, m.group(1))
        return {"intent": "remember", "reply": (f"I'll remember: {r['text']}" if r["stored"]
                                                else f"I already had that: {r['text']}"),
                "memory": r, "assisted": False}
    m = _FORGET.match(text)
    if m:
        gone = forget_matching(graph, m.group(1))
        reply = ("Forgotten: " + "; ".join(gone)) if gone else "I had nothing matching that."
        return {"intent": "forget", "reply": reply, "forgotten": gone, "assisted": False}
    if _RECALL.match(text):
        known = facts(graph)
        reply = ("Here is everything you asked me to remember:\n" +
                 "\n".join(f"- {f['text']}" for f in known)) if known else \
            "Nothing yet. Say \"remember …\" and I will keep it here, where you can delete it."
        return {"intent": "recall", "reply": reply, "memory": known, "assisted": False}
    if _CHECKIN.match(text):
        c = checkin(graph)
        return {"intent": "checkin", "reply": _checkin_text(c), "checkin": c, "assisted": False}
    m = _GOAL.match(text)
    if m:
        body, deadline = m.group(1), ""
        by = _BY.search(body)
        if by:
            deadline, body = by.group(1), body[:by.start()]
        g = create_goal(graph, body.rstrip(" ."), deadline=deadline, claude=claude)
        lines = [f"New goal: {g['title']}"] + [f"{i}. {s['title']}"
                                               for i, s in enumerate(g["steps"], 1)]
        if g["note"]:
            lines.append(g["note"])
        return {"intent": "goal", "reply": "\n".join(lines), "goal": g,
                "assisted": g["assisted"]}

    if not _assisted(claude):
        return {"intent": "question", "reply": (
            "I can't answer open questions without a model on this server. Without one I "
            "can still: plan a goal (\"I want to …\"), remember things (\"remember …\"), "
            "and check in (\"what's next?\")."), "assisted": False, **NEEDS_KEY}

    try:
        data = claude.complete_json(_ASK_SYSTEM,
                                    json.dumps({"facts": context(graph), "message": text}),
                                    schema=_ASK_SCHEMA, max_tokens=1200)
    except Exception as exc:
        return {"intent": "question", "reply": "The model did not answer this time. Try again.",
                "assisted": False, "available": False, "capability": "open-ended answers",
                "why": f"the model call failed: {type(exc).__name__}", "needs": []}
    made, dropped = [], 0
    for p in data.get("proposals", [])[:5]:
        try:
            args = json.loads(p.get("args_json") or "{}")
            made.append(propose(graph, p.get("action", ""), args if isinstance(args, dict) else {},
                                p.get("summary", "")))
        except (ValueError, json.JSONDecodeError):
            dropped += 1
    out = {"intent": "question", "reply": _clean(data.get("reply", ""), 2000),
           "proposals": made, "assisted": True}
    if dropped:
        out["note"] = f"{dropped} suggested action(s) were malformed and not queued"
    return out
