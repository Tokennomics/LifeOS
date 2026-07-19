from modules.voiceos import capture


class FakeClaude:
    available = True
    model_light = "claude-haiku-4-5"

    def __init__(self, data):
        self.data = data

    def complete_json(self, system, user, *, schema, model=None, max_tokens=16000):
        return self.data


def test_raw_capture_without_claude(graph):
    result = capture.capture("random shower thought", graph)
    assert result["method"] == "raw"
    s = graph.session("voiceos", capture.SCOPES)
    contents = s.find_entities("content", {"type": "capture"})
    assert contents[0]["attrs"]["text"] == "random shower thought"
    assert capture.format_summary(result) == "Captured."


def test_claude_extraction_creates_linked_entities(graph):
    fake = FakeClaude({"tasks": ["Book dentist"], "interests": ["bouldering"], "people": ["Sam"]})
    result = capture.capture("gotta book the dentist, also Sam wants to try bouldering", graph, claude=fake)
    assert (result["tasks"], result["interests"], result["people"]) == (1, 1, 1)

    s = graph.session("voiceos", capture.SCOPES)
    linked = s.neighbors(result["capture_id"], rel="feeds", direction="out")
    assert {e["kind"] for e in linked} == {"task", "interest", "person"}
    assert "1 tasks" in capture.format_summary(result)


def test_people_deduped_by_name(graph):
    fake = FakeClaude({"tasks": [], "interests": [], "people": ["Sam"]})
    capture.capture("saw Sam", graph, claude=fake)
    second = capture.capture("Sam again", graph, claude=fake)
    assert second["people"] == 0  # existing person reused
    s = graph.session("voiceos", capture.SCOPES)
    assert len(s.find_entities("person", {"name": "Sam"})) == 1
    # but the second capture still links to them
    assert len(s.neighbors(second["capture_id"], rel="feeds", direction="out")) == 1
