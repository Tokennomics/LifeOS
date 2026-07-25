"""Crews — named groups with a topic and a home city ("the Lisbon climbing crew").

A crew is the group primitive the coordinator schedules for: a `content` entity
(type="crew") with membership held in the same grants ACL Hearth uses, so there is one
membership model in the system, not two.

SCOPE (deliberate): crews are LOCAL — made of people already in your graph. The public,
cross-user directory ("land in a new city, join the local climbing crew") is a separate,
still-gated arc: it needs accounts, a reachable host, moderation/reporting, and location
privacy that this local model does not. The read API here is shaped like a directory
(filter by topic/city) so that layer can sit on top without reshaping the data.
"""
