"""Goal Dependency Graph & Blocker Solver.

Tracks goal dependencies using the 'blocks' edge relation and generates
actionable unblocking recommendations for stuck goals.
"""

from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write"}
MODULE = "horizon"


def link_goal_dependency(graph: Graph, goal_id: str, depends_on_goal_id: str,
                         source: str = MODULE) -> dict:
    """Links a dependency between two goals (goal_id is blocked by depends_on_goal_id)."""
    if not goal_id.strip() or not depends_on_goal_id.strip():
        raise ValueError("goal_id and depends_on_goal_id required")

    session = graph.session(MODULE, SCOPES)
    edge_id = session.create_edge(goal_id, depends_on_goal_id, "blocks", source=source)

    return {
        "edge_id": edge_id,
        "goal_id": goal_id,
        "depends_on_goal_id": depends_on_goal_id,
        "rel": "blocks",
    }


def get_goal_blockers(graph: Graph, goal_id: str) -> dict:
    """Identifies blockers for a goal and outputs recommendations."""
    session = graph.session(MODULE, SCOPES)
    goal = session.get_entity(goal_id)
    if not goal or goal.get("kind") != "goal":
        raise ValueError(f"goal '{goal_id}' not found")

    blocker_entities = session.neighbors(goal_id, rel="blocks", direction="out")

    blockers = []
    for b in blocker_entities:
        b_title = b.get("attrs", {}).get("title", "Dependent Goal")
        b_focus = b.get("attrs", {}).get("focus", False)
        blockers.append({
            "blocker_goal_id": b["id"],
            "title": b_title,
            "in_focus": b_focus,
        })

    if blockers:
        rec = f"Goal is blocked by {len(blockers)} goal(s). Recommend completing '{blockers[0]['title']}' first."
    else:
        rec = "No goal blockers identified. Clear to proceed!"

    return {
        "goal_id": goal_id,
        "goal_title": goal.get("attrs", {}).get("title", ""),
        "blockers_count": len(blockers),
        "blockers": blockers,
        "recommendation": rec,
    }
