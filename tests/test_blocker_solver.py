import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import blocker_solver
from substrate.graph import Graph


def test_goal_dependency_linking(graph: Graph):
    session = graph.session("test", {"*"})
    g1 = session.create_entity("goal", {"title": "Main Product Launch", "focus": True}, source="test")
    g2 = session.create_entity("goal", {"title": "Security Audit Clearance", "focus": True}, source="test")

    link_res = blocker_solver.link_goal_dependency(graph, g1, g2)
    assert link_res["rel"] == "blocks"

    blockers = blocker_solver.get_goal_blockers(graph, g1)
    assert blockers["blockers_count"] == 1
    assert blockers["blockers"][0]["title"] == "Security Audit Clearance"


def test_gateway_blocker_solver_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    graph = app.state.graph
    session = graph.session("test", {"*"})
    g1 = session.create_entity("goal", {"title": "Scale Infrastructure"}, source="test")
    g2 = session.create_entity("goal", {"title": "VPS Setup"}, source="test")

    resp_l = client.post("/v1/goals/dependency", json={"goal_id": g1, "depends_on_goal_id": g2})
    assert resp_l.status_code == 200

    resp_b = client.get(f"/v1/goals/{g1}/blockers")
    assert resp_b.status_code == 200
    assert resp_b.json()["blockers_count"] == 1
