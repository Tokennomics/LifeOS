"""Event bus.

v0.1: in-process pub/sub (single-process deployment on sqlite).
On postgres, publish() additionally emits pg_notify so future cross-process
consumers can LISTEN; subscribe() stays in-process until a listener loop is needed.
"""

import json

TOPICS = {
    "observation.created",
    "plan.updated",
    "event.attended",
    "capsule.dropped",
    "capsule.unlocked",
    "energy.updated",
    "admin.detected",
}


class Bus:
    def __init__(self, pg_conn=None):
        self._subs: dict[str, list] = {}
        self._pg = pg_conn

    def publish(self, topic: str, payload: dict) -> None:
        if topic not in TOPICS:
            raise ValueError(f"unknown bus topic: {topic!r} (known: {sorted(TOPICS)})")
        if self._pg is not None:
            with self._pg.cursor() as cur:
                cur.execute("SELECT pg_notify(%s, %s)", (topic, json.dumps(payload)))
        for handler in self._subs.get(topic, []) + self._subs.get("*", []):
            handler(topic, payload)

    def subscribe(self, topic: str, handler) -> None:
        """Register a handler(topic, payload). Topic '*' receives everything."""
        if topic != "*" and topic not in TOPICS:
            raise ValueError(f"unknown bus topic: {topic!r}")
        self._subs.setdefault(topic, []).append(handler)
