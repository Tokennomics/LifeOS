"""Horizon — Boredom Rule Micro-Break Planner (Procrastination Solver).

Takes tasks carried >2 cycles, breaks them into 15-minute physical steps using Claude
or a smart heuristic, and splits/creates concrete actionable subtasks.
"""

import json
from substrate.graph import Graph

SCOPES = {"tasks:read", "tasks:write", "*"}
MODULE = "horizon"

BREAKDOWN_SYSTEM = (
    "You are an expert procrastination coach in LifeOS. The user has procrastinated on "
    "a task for multiple weeks. Break down the task into exactly 3 ultra-simple, 15-minute "
    "physical next steps. They must be concrete and actionable (e.g. 'open the document and "
    "type the title' instead of 'research information'). Do not include abstract steps. "
    "Output a JSON object matching the required schema."
)

BREAKDOWN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["steps"],
    "additionalProperties": False
}


def suggest_micro_breaks(graph: Graph, claude = None) -> list[dict]:
    """Finds open stuck tasks (>2 carries) and proposes 15-minute concrete steps."""
    session = graph.session(MODULE, SCOPES)
    all_tasks = session.find_entities("task", limit=500)
    
    stuck_tasks = []
    for t in all_tasks:
        attrs = t.get("attrs", {})
        if attrs.get("status", "open") == "open" and attrs.get("carries", 0) > 2:
            stuck_tasks.append(t)
            
    if not stuck_tasks:
        return []
        
    proposals = []
    for t in stuck_tasks:
        title = t["attrs"].get("title", "")
        steps = []
        
        if claude is not None and getattr(claude, "available", False):
            try:
                res = claude.complete_json(BREAKDOWN_SYSTEM, f"Task to break down: '{title}'", schema=BREAKDOWN_SCHEMA)
                steps = res.get("steps", [])
            except Exception:
                pass
                
        if not steps:
            # Smart heuristic split: e.g. "Draft the report and submit email"
            steps = [
                f"Open workspace and review '{title}' requirements (5 mins)",
                f"Draft first rough 3 bullet points / outline of '{title}' (10 mins)",
                f"Write the first minor section or send quick inquiry (15 mins)"
            ]
            
        proposals.append({
            "task_id": t["id"],
            "original_title": title,
            "carries": t["attrs"].get("carries", 0),
            "steps": steps
        })
        
    return proposals


def execute_micro_break_plan(graph: Graph, task_id: str, steps: list[str], source: str = MODULE) -> dict:
    """Closes the stuck parent task and spawns concrete child tasks linked via feeds."""
    session = graph.session(MODULE, SCOPES)
    
    parent = session.get_entity(task_id)
    if not parent or parent.get("kind") != "task":
        raise ValueError("stuck task not found")
        
    # Mark parent task as archived or completed
    session.update_entity(task_id, {"status": "split"}, source=source)
    
    # Spawn child tasks
    child_ids = []
    for step in steps:
        cid = session.create_entity("task", {
            "title": step,
            "status": "open",
            "week": parent["attrs"].get("week"),
            "if_then": parent["attrs"].get("if_then", "")
        }, source=source)
        session.create_edge(task_id, cid, "feeds", source=source)
        child_ids.append(cid)
        
    return {
        "parent_task_id": task_id,
        "status": "split_successful",
        "child_tasks": child_ids
    }
