import pytest

from substrate.graph import GraphError, ProvenanceError, ScopeError


def test_create_entity_with_provenance(graph):
    s = graph.session("horizon", {"goals:write"})
    gid = s.create_entity("goal", {"title": "ship v0.1"}, source="test")
    entity = s.get_entity(gid)
    assert entity["kind"] == "goal"
    assert entity["attrs"]["title"] == "ship v0.1"
    cur = graph._execute("SELECT * FROM observations WHERE entity_id = ?", (gid,))
    obs = cur.fetchall()
    assert len(obs) == 1
    assert obs[0]["module"] == "horizon"
    assert obs[0]["source"] == "test"


def test_write_without_scope_rejected(graph):
    s = graph.session("horizon", {"goals:write"})
    with pytest.raises(ScopeError):
        s.create_entity("event", {"title": "party"}, source="test")


def test_read_without_scope_rejected(graph):
    writer = graph.session("infra", {"*"})
    eid = writer.create_entity("event", {"title": "party"}, source="seed")
    reader = graph.session("horizon", {"goals:read"})
    with pytest.raises(ScopeError):
        reader.get_entity(eid)


def test_write_scope_implies_read(graph):
    s = graph.session("horizon", {"goals:write"})
    gid = s.create_entity("goal", {}, source="test")
    assert s.get_entity(gid) is not None
    assert s.find_entities("goal") != []


def test_write_without_source_rejected(graph):
    s = graph.session("horizon", {"goals:write"})
    with pytest.raises(ProvenanceError):
        s.create_entity("goal", {}, source="")


def test_bad_confidence_rejected(graph):
    s = graph.session("horizon", {"goals:write"})
    with pytest.raises(ProvenanceError):
        s.create_entity("goal", {}, source="test", confidence=1.5)


def test_unknown_kind_rejected(graph):
    s = graph.session("infra", {"*"})
    with pytest.raises(GraphError):
        s.create_entity("spaceship", {}, source="test")


def test_update_merges_attrs_and_records_provenance(graph):
    s = graph.session("horizon", {"goals:write"})
    gid = s.create_entity("goal", {"title": "a", "level": "goal"}, source="test")
    merged = s.update_entity(gid, {"title": "b"}, source="edit")
    assert merged == {"title": "b", "level": "goal"}
    cur = graph._execute("SELECT COUNT(*) AS n FROM observations WHERE entity_id = ?", (gid,))
    assert cur.fetchone()["n"] == 2


def test_edge_requires_scope_on_both_endpoints(graph):
    infra = graph.session("infra", {"*"})
    goal = infra.create_entity("goal", {}, source="seed")
    event = infra.create_entity("event", {}, source="seed")
    s = graph.session("horizon", {"goals:write", "tasks:write"})
    with pytest.raises(ScopeError):
        s.create_edge(goal, event, "feeds", source="test")


def test_edge_unknown_rel_rejected(graph):
    s = graph.session("infra", {"*"})
    a = s.create_entity("goal", {}, source="seed")
    b = s.create_entity("goal", {}, source="seed")
    with pytest.raises(GraphError):
        s.create_edge(a, b, "teleports", source="test")


def test_edge_missing_endpoint_rejected(graph):
    s = graph.session("infra", {"*"})
    a = s.create_entity("goal", {}, source="seed")
    with pytest.raises(GraphError):
        s.create_edge(a, "nonexistent-id", "feeds", source="test")


def test_find_entities_attr_filter(graph):
    s = graph.session("horizon", {"goals:write"})
    s.create_entity("goal", {"level": "vision", "title": "v"}, source="t")
    s.create_entity("goal", {"level": "goal", "title": "g"}, source="t")
    visions = s.find_entities("goal", {"level": "vision"})
    assert len(visions) == 1
    assert visions[0]["attrs"]["title"] == "v"


def test_neighbors_directional(graph):
    s = graph.session("infra", {"*"})
    vision = s.create_entity("goal", {"level": "vision"}, source="t")
    goal = s.create_entity("goal", {"level": "goal", "title": "g1"}, source="t")
    s.create_edge(goal, vision, "feeds", source="t")
    incoming = s.neighbors(vision, rel="feeds", direction="in")
    assert [e["attrs"].get("title") for e in incoming] == ["g1"]
    outgoing = s.neighbors(goal, rel="feeds", direction="out")
    assert outgoing[0]["id"] == vision


def test_every_write_publishes_observation_created(graph):
    seen = []
    graph.bus.subscribe("observation.created", lambda t, p: seen.append(p))
    s = graph.session("horizon", {"goals:write"})
    a = s.create_entity("goal", {}, source="t")
    b = s.create_entity("goal", {}, source="t")
    s.create_edge(a, b, "feeds", source="t")
    s.update_entity(a, {"x": 1}, source="t")
    assert len(seen) == 4
    assert {p["target"] for p in seen} == {"entity", "edge"}
