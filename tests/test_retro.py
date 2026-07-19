from modules.horizon import planner, retro


def test_retro_scores_week_and_writes_metric(graph):
    s = graph.session("horizon", planner.SCOPES)
    s.create_entity("task", {"title": "a", "status": "open", "if_then": ""}, source="seed")
    s.create_entity("task", {"title": "b", "status": "open", "if_then": ""}, source="seed")
    planner.plan_week(graph)
    planner.log_done(graph, 1)

    result = retro.run_retro(graph)
    assert (result["planned"], result["done"], result["rate"]) == (2, 1, 0.5)
    assert "1/2 tasks done (50%)" in result["text"]

    metrics = graph.session("horizon", retro.SCOPES).find_entities("metric", {"type": "weekly_retro"})
    assert len(metrics) == 1
    assert metrics[0]["attrs"]["done"] == 1


def test_retro_empty_week(graph):
    result = retro.run_retro(graph)
    assert result["planned"] == 0
    assert "Nothing was planned" in result["text"]
