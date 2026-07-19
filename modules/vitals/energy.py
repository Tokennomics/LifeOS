"""Vitals — a LAYER, not an app: circadian energy windows every scheduler consumes.

P0 uses a stable default profile (peak/trough/rebound are stable traits); sleep import
replaces the defaults later. Horizon reads peak windows for if-then times; Steward will
batch admin into troughs.
"""

from substrate.graph import Graph

SCOPES = {"metrics:read", "metrics:write"}

DEFAULT_WINDOWS = [
    {"phase": "peak", "start": "09:00", "end": "12:00"},
    {"phase": "trough", "start": "14:00", "end": "16:00"},
    {"phase": "rebound", "start": "17:00", "end": "19:00"},
]


def windows(graph: Graph) -> list[dict]:
    session = graph.session("vitals", SCOPES)
    profiles = session.find_entities("metric", {"type": "energy_profile"}, limit=50)
    if profiles:
        return profiles[-1]["attrs"].get("windows", DEFAULT_WINDOWS)
    return DEFAULT_WINDOWS


def set_windows(graph: Graph, new_windows: list[dict], source: str = "vitals") -> dict:
    for w in new_windows:
        if w.get("phase") not in ("peak", "trough", "rebound") or "start" not in w or "end" not in w:
            raise ValueError("each window needs phase (peak|trough|rebound), start, end")
    session = graph.session("vitals", SCOPES)
    session.create_entity("metric", {"type": "energy_profile", "windows": new_windows}, source=source)
    graph.bus.publish("energy.updated", {"windows": len(new_windows), "module": "vitals"})
    return {"windows": new_windows}


def phase_start(graph: Graph, phase: str, default: str) -> str:
    for w in windows(graph):
        if w.get("phase") == phase:
            return w.get("start", default)
    return default
