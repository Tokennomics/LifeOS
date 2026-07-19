import pytest

from substrate.bus import Bus


def test_publish_subscribe():
    bus = Bus()
    seen = []
    bus.subscribe("plan.updated", lambda t, p: seen.append((t, p)))
    bus.publish("plan.updated", {"x": 1})
    assert seen == [("plan.updated", {"x": 1})]


def test_wildcard_subscription():
    bus = Bus()
    seen = []
    bus.subscribe("*", lambda t, p: seen.append(t))
    bus.publish("plan.updated", {})
    bus.publish("admin.detected", {})
    assert seen == ["plan.updated", "admin.detected"]


def test_unknown_topic_rejected():
    bus = Bus()
    with pytest.raises(ValueError):
        bus.publish("nonsense.topic", {})
    with pytest.raises(ValueError):
        bus.subscribe("nonsense.topic", lambda t, p: None)
