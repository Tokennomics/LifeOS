"""Coordinate — mediator-brokered, privacy-preserving inter-user coordination (roadmap Phase 3).

A neutral first-party coordinator finds a common {time, place} for two people without
either revealing their full calendar: each side shares only a weight vector over the
*proposed* slots/places (Doodle-style availability, never the underlying calendar), the
coordinator ranks the overlap, and BOTH humans ratify the final pick before anything is
written. Peer input is treated as untrusted data (structured weights only, sanitized to the
proposed keys) — never instructions. This is the sanctioned alternative to open
agent-to-agent negotiation (which is on the Do-Not-Build list).

`core` is the pure ranking engine; `coordinator` is the graph-backed flow.
"""
