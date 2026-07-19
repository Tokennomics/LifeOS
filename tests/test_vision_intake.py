from modules.horizon import vision_intake


class FakeClaude:
    available = True

    def __init__(self, data):
        self.data = data
        self.calls = []

    def complete_json(self, system, user, *, schema, model=None, max_tokens=16000):
        self.calls.append(user)
        return self.data


def test_offline_intake_writes_plan(graph):
    result = vision_intake.intake(
        "Financial freedom by 40\n- Grow the AGI brain to live\n- 3 workouts a week", graph
    )
    assert result["status"] == "created"
    assert result["method"] == "offline"
    assert result["goals"] == 2

    s = graph.session("horizon", vision_intake.SCOPES)
    visions = s.find_entities("goal", {"level": "vision"})
    assert len(visions) == 1
    feeding = s.neighbors(visions[0]["id"], rel="feeds", direction="in")
    assert len(feeding) == 2


def test_offline_empty_text_asks_questions(graph):
    result = vision_intake.intake("   \n  ", graph)
    assert result["status"] == "questions"
    assert result["questions"]
    assert "answer me this" in vision_intake.format_summary(result)


def test_claude_plan_written_with_milestones_and_tasks(graph):
    fake = FakeClaude({
        "status": "plan",
        "questions": [],
        "vision": "A connected, healthy life",
        "goals": [
            {
                "title": "Run a 10k",
                "why": "Health underpins everything else",
                "horizon_weeks": 12,
                "milestones": ["5k without stopping"],
                "tasks": [{"title": "Run Tuesday", "if_then": "If it's 6pm Tuesday, then I run 3k"}],
            }
        ],
    })
    result = vision_intake.intake("some vision", graph, claude=fake)
    assert result["method"] == "claude"
    assert (result["goals"], result["milestones"], result["tasks"]) == (1, 1, 1)
    assert fake.calls == ["some vision"]

    s = graph.session("horizon", vision_intake.SCOPES)
    tasks = s.find_entities("task")
    assert tasks[0]["attrs"]["if_then"].startswith("If it's 6pm")


def test_claude_questions_pass_through_without_writing(graph):
    fake = FakeClaude({"status": "questions", "questions": ["By when?"], "vision": "", "goals": []})
    result = vision_intake.intake("vague", graph, claude=fake)
    assert result["status"] == "questions"
    s = graph.session("horizon", vision_intake.SCOPES)
    assert s.find_entities("goal") == []


def test_plan_updated_published(graph):
    seen = []
    graph.bus.subscribe("plan.updated", lambda t, p: seen.append(p))
    vision_intake.intake("Vision\n- goal one", graph)
    assert len(seen) == 1
    assert seen[0]["goals"] == 1
