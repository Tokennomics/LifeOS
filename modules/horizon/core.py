"""Horizon — the anti-hindrance core (T3).

Pure, deterministic, side-effect-free logic shared by BOTH the server (Python)
and Travel Mode (surfaces/app/www/horizon-core.js). Every function here has a
line-for-line twin in that JS file; the golden-file suite (tests/test_golden.py +
tests/golden/run_js.mjs against tests/golden/cases.json) runs both against the
same fixtures so any drift fails CI instead of surfacing as odd behaviour on a
phone with no laptop.

Keep it boring and portable: no graph, no I/O, no datetime beyond week_id, and
no idiom that can't be mirrored in plain JS.

The three named obstacles, encoded:
  1. Distraction  -> is_project_idea() feeds the capture "distraction sink".
  2. Boredom      -> offline_plan() finishes stuck work before starting new work,
                     and surfaces >2-cycle tasks as their smallest remaining piece.
  3. Doubt        -> gate_from_counts() reports honest v0.1-gate progress.
Plus energy shaping: deep work goes to the evening (never mornings), admin to the
daytime trough, and the week is hard-capped while the owner's baseline is tired.
"""

import datetime

# ---- shared constants (mirror horizon-core.js exactly) ----------------------

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
EVENING_TIME = "20:00"   # deep work -> evening/night, never morning (night-owl owner)
TROUGH_TIME = "14:00"    # admin -> the daytime energy trough
WEEKLY_CAP_TIRED = 3     # hard cap on the week while energy_baseline == tired
WEEKLY_CAP_RESTED = 7
NEW_WORK_FLOOR = 3       # start at most this many *new* items when nothing is stuck
STALE_CYCLES = 2         # a task carried more than this many cycles = "smallest piece"

GATE_TARGET_DAYS = 28    # v0.1 gate: daily self-use for 4 weeks
GATE_TARGET_RETROS = 4

PARK_MESSAGE = "Captured, not abandoned — current gate first."

# Substring markers (matched case-insensitively). Curated to catch "I'm about to
# start a shiny new thing" without tripping on ordinary tasks/notes.
PROJECT_IDEA_MARKERS = (
    "idea:", "new idea", "new project", "side project", "startup", "start a company",
    "i should build", "i want to build", "we could build", "i could build",
    "what if i built", "what if we built", "build an app", "build a platform",
    "launch a ", "new app", "new venture",
)
ADMIN_MARKERS = (
    "email", "invoice", "pay the", "pay my", "bill", "tax", "form", "renew",
    "book a", "book the", "schedule", "admin", "call the", "reply to", "submit",
    "file the", "paperwork", "appointment",
)


def week_id(dt: datetime.datetime | datetime.date | None = None) -> str:
    """ISO-8601 week id, e.g. '2026-W30'. Twin of planner.week_id / JS weekId."""
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _has_marker(text: str, markers) -> bool:
    low = (text or "").lower()
    return any(m in low for m in markers)


def is_project_idea(text: str) -> bool:
    """Distraction sink: does this capture read as a brand-new project to start?"""
    return _has_marker(text, PROJECT_IDEA_MARKERS)


def is_admin(name: str) -> bool:
    return _has_marker(name, ADMIN_MARKERS)


def weekly_cap(baseline: str) -> int:
    return WEEKLY_CAP_TIRED if (baseline or "tired") == "tired" else WEEKLY_CAP_RESTED


def shape_if_then(ref: str, cycles: int, day_index: int) -> str:
    """Energy-shaped implementation intention for one task.

    Admin -> daytime trough. Deep work -> evening, always. A task carried past
    STALE_CYCLES is reframed as its smallest remaining physical piece (boredom rule).
    """
    day = DAYS[day_index % len(DAYS)]
    if is_admin(ref):
        return f"If it's {day} {TROUGH_TIME}, then I clear '{ref}' (admin — batch it in the daytime dip)"
    if cycles > STALE_CYCLES:
        return (f"If it's {day} {EVENING_TIME}, then I do the smallest remaining piece of "
                f"'{ref}': one concrete physical step, 15 minutes")
    return f"If it's {day} {EVENING_TIME}, then I spend 45 min on '{ref}'"


def offline_plan(inp: dict) -> list[dict]:
    """Deterministic weekly plan (the no-Claude path).

    Input:  {"baseline": "tired"|"rested",
             "goals": [{"title": str}, ...],
             "open_tasks": [{"id": any, "title": str, "if_then": str, "cycles": int}, ...]}
    Output: an ordered list of task descriptors to write for the week:
             {"origin": "reuse"|"new", "id": <passthrough|None>, "title": str,
              "if_then": str, "status": "open", "cycles": int,
              "smallest_piece": bool, "goal_title": str}

    Boredom rule: carry-overs come first, most-stuck first; if any carry-over is
    stale we do NOT start new goal work this cycle (finish before you start).
    Gate-first: goals flagged focus lead the week, so the goal the current gate
    depends on is always in the top few rather than losing to input order.
    Energy/cap: total items capped by baseline; new starts capped at the floor.
    """
    cap = weekly_cap(inp.get("baseline", "tired"))
    # Focus goals first (stable), so the gate/keystone goal is never crowded out.
    goals = sorted(inp.get("goals", []), key=lambda g: 0 if g.get("focus") else 1)
    open_tasks = inp.get("open_tasks", [])

    # Most-stuck carry-overs first (stable sort keeps input order among equals).
    carry = sorted(open_tasks, key=lambda t: -int(t.get("cycles", 0) or 0))

    proposals: list[dict] = []
    stale_present = False
    day = 0
    for t in carry:
        if len(proposals) >= cap:
            break
        cycles = int(t.get("cycles", 0) or 0) + 1
        smallest = cycles > STALE_CYCLES
        ref = t.get("title", "")
        proposals.append({
            "origin": "reuse",
            "id": t.get("id"),
            "title": ref,
            "if_then": shape_if_then(ref, cycles, day),
            "status": "open",
            "cycles": cycles,
            "smallest_piece": smallest,
            "goal_title": "",
        })
        stale_present = stale_present or smallest
        day += 1

    # Only start NEW work when nothing is stuck (boredom rule) and there's room.
    if not stale_present:
        new_limit = min(NEW_WORK_FLOOR, cap)
        for g in goals:
            if len(proposals) >= new_limit:
                break
            title = g.get("title", "")
            proposals.append({
                "origin": "new",
                "id": None,
                "title": f"Advance: {title}",
                "if_then": shape_if_then(title, 1, day),
                "status": "open",
                "cycles": 1,
                "smallest_piece": False,
                "goal_title": title,
            })
            day += 1

    return proposals


def retro(week: str, tasks: list[dict]) -> dict:
    """Score the week and compose the reflection (the no-Claude retro path).

    tasks: [{"title": str, "status": "open"|"done"}, ...]
    """
    done = [t for t in tasks if t.get("status") == "done"]
    planned = len(tasks)
    rate = round(len(done) / planned, 2) if planned else 0.0
    lines = [f"Retro {week}: {len(done)}/{planned} tasks done ({int(rate * 100)}%)."]
    for t in tasks:
        mark = "x" if t.get("status") == "done" else " "
        lines.append(f"[{mark}] {t.get('title', '')}")
    if planned == 0:
        lines.append("Nothing was planned this week — plan it now.")
    return {"week": week, "planned": planned, "done": len(done), "rate": rate,
            "text": "\n".join(lines)}


def gate_from_counts(days_used: int, logs_recorded: int, retros_completed: int) -> dict:
    """Doubt rule: honest v0.1-gate progress from real counts (never estimates)."""
    cleared = days_used >= GATE_TARGET_DAYS and retros_completed >= GATE_TARGET_RETROS
    lines = [
        "v0.1 gate — use it daily for 4 weeks before any new surface.",
        f"Days used: {days_used}/{GATE_TARGET_DAYS}",
        f"Logs recorded: {logs_recorded}",
        f"Retros completed: {retros_completed}/{GATE_TARGET_RETROS}",
    ]
    if cleared:
        lines.append("Gate cleared. You earned the next surface.")
    else:
        remaining = max(0, GATE_TARGET_DAYS - days_used)
        lines.append(f"{remaining} day(s) to go. Check the metric, don't re-decide — keep logging.")
    return {
        "target_days": GATE_TARGET_DAYS,
        "target_retros": GATE_TARGET_RETROS,
        "days_used": days_used,
        "logs_recorded": logs_recorded,
        "retros_completed": retros_completed,
        "cleared": cleared,
        "text": "\n".join(lines),
    }
