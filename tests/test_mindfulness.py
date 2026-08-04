import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import mindfulness
from substrate.graph import Graph


def test_mindfulness_target_generation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Baseline checks
    res_base = mindfulness.generate_mindfulness_target(graph)
    assert res_base["recommended_duration_minutes"] == 5

    # Create stress log index
    session.create_entity("metric", {"type": "stress_index", "value": 85}, source="test")
    res_stress = mindfulness.generate_mindfulness_target(graph)
    assert res_stress["recommended_duration_minutes"] == 15
    assert "stress_relief_breathwork" in res_stress["session_type"]


def test_gateway_mindfulness_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/routines/mindfulness-recommendation")
    assert resp.status_code == 200
    assert "recommended_duration_minutes" in resp.json()
