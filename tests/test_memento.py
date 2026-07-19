from modules.memento import capsules
from modules.memento.geo import haversine_m

HOME = (-27.4700, 153.0200)
CAFE = (-27.4705, 153.0206)      # ~80m from HOME
FAR = (-27.5500, 153.1000)       # ~12km away


def test_haversine_sanity():
    assert haversine_m(*HOME, *HOME) == 0
    assert 50 < haversine_m(*HOME, *CAFE) < 120
    assert haversine_m(*HOME, *FAR) > 10000


def test_drop_creates_capsule_place_edge_and_publishes(graph):
    seen = []
    graph.bus.subscribe("capsule.dropped", lambda t, p: seen.append(p))
    result = capsules.drop(graph, "first coffee here with Sam", *HOME, place_name="Corner Cafe")
    assert seen[0]["place"] == "Corner Cafe"
    session = graph.session("memento", capsules.SCOPES)
    place = session.neighbors(result["capsule_id"], rel="located_at", direction="out")
    assert place[0]["attrs"]["name"] == "Corner Cafe"
    # same place name reused, not duplicated
    capsules.drop(graph, "second memory", *HOME, place_name="Corner Cafe")
    assert len(session.find_entities("place")) == 1


def test_locked_capsules_hide_text_and_sort_by_distance(graph):
    capsules.drop(graph, "near secret", *HOME, place_name="Near")
    capsules.drop(graph, "far secret", *FAR, place_name="Far")
    listed = capsules.nearby(graph, *HOME)
    assert [c["place"] for c in listed] == ["Near", "Far"]
    assert all(c["locked"] and "text" not in c for c in listed)
    assert listed[0]["distance_m"] < 50


def test_unlock_only_within_radius(graph):
    capsules.drop(graph, "the secret", *HOME, place_name="Near", radius_m=75)
    capsules.drop(graph, "far away", *FAR, place_name="Far", radius_m=75)
    nothing = capsules.unlock(graph, *CAFE) if haversine_m(*CAFE, *HOME) > 75 else None
    result = capsules.unlock(graph, *HOME)
    assert result["unlocked"] == 1
    assert result["capsules"][0]["text"] == "the secret"
    listed = capsules.nearby(graph, *HOME)
    assert listed[0]["locked"] is False
    assert listed[0]["text"] == "the secret"
    assert listed[1]["locked"] is True
    assert nothing is None or nothing["unlocked"] == 0
