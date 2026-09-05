"""The served front end must not say things the gateway does not.

A green Python suite has never been able to see the PWA. Every honest handler in
`gateway/modules_api.py` was reachable through a card that still had the prop's people
written into the markup: an AR radar with "Elena R." at 85 metres on a bearing of 42
degrees, a leaderboard where "Elena R." had 96 Karma, a "94% Match" list whose Connect
button's entire implementation was `toast('Friend request & crew invite sent to Elena!')`.
None of those names is anybody. A user reading them believed the app had found them a
person.

Three separate things are checked here, because the front end can lie in three ways.

1. **Invented people and places.** Names and figures that were written into the markup
   rather than counted from a response. Comments are stripped first: the house style is
   that a replaced handler records what the prop claimed, so `Elena R.` appearing in a
   `/* ... */` above the replacement is the changelog working as intended. It is the
   *rendered* string that is the lie.

2. **Keys that no longer exist.** T2 rewrote twenty-three handlers. A renderer still
   reaching for `res.steward_guarantee` or `res.next_turn` puts the word `undefined` on
   the screen, which no server-side test can see. Each name below was a real response key
   before that ticket and is a real defect after it.

3. **Routes that are not served.** The same pure-text sweep the lead's `dead_routes.py`
   does: every `/v1/...` path the JS calls has to be declared on the gateway's router.

`onclick` gets its own check. The two Connect buttons were inline handlers, and inline
handlers are how a button gets shipped with no implementation behind it — there is
nothing to call, so a toast stands in for the action. Everything else in this file goes
through `on("[data-act=...]")`, which cannot be written without naming a handler.
"""

import pathlib
import re

import pytest

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces" / "app" / "www"
GATEWAY = pathlib.Path(__file__).resolve().parent.parent / "gateway"


def strip_js_comments(src: str) -> str:
    """Blank `/* */` and `//` comments, preserving line numbers.

    A regex cannot do this: `"https://x"` and a template literal holding `/*` both look
    like comment openers, and blanking either corrupts the very strings under test. This
    walks the source once, tracking which of the five contexts it is in.

    The fifth is the one that bit first. `esc()` is written with a character class —
    `.replace(/[&<>"']/g, ...)` — and a walker that does not know about regex literals
    reads the `'` inside it as a string opener, swallows everything to the next apostrophe
    and desynchronises for the rest of the file. Every comment after line 96 then survived
    the strip, and this test passed on prose it should have been blind to.
    """
    out: list[str] = []
    i, n = 0, len(src)
    # What can legally precede a regex literal: an operator or an opening bracket. After a
    # value (identifier, number, `)`, `]`) a slash is division instead.
    before_regex = set("(,=:[!&|?{};+-*%~^<>") | {"\n"}
    prev = ""
    while i < n:
        c = src[i]
        if c == "/" and prev in before_regex and not (
                i + 1 < n and src[i + 1] in "*/"):
            # A regex literal: copy it whole, including any quote or slash inside a class.
            out.append(c)
            i += 1
            in_class = False
            while i < n:
                if src[i] == "\\":
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                if src[i] == "[":
                    in_class = True
                elif src[i] == "]":
                    in_class = False
                out.append(src[i])
                if src[i] == "/" and not in_class:
                    i += 1
                    break
                if src[i] == "\n":  # not a regex after all
                    i += 1
                    break
                i += 1
            prev = "/"
            continue
        if not c.isspace():
            prev = c
        elif c == "\n":
            prev = "\n"
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                if src[i] == "\\":
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "`":
            out.append(c)
            i += 1
            depth = 0
            while i < n:
                if src[i] == "\\":
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                if src[i] == "$" and i + 1 < n and src[i + 1] == "{":
                    depth += 1
                    out.append("${")
                    i += 2
                    continue
                if src[i] == "}" and depth:
                    depth -= 1
                    out.append("}")
                    i += 1
                    continue
                out.append(src[i])
                if src[i] == "`" and not depth:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join(ch if ch == "\n" else " " for ch in src[i:end]))
            i = end
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            end = src.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_html_comments(src: str) -> str:
    return re.sub(r"<!--.*?-->",
                  lambda m: "".join(ch if ch == "\n" else " " for ch in m.group(0)),
                  src, flags=re.S)


def served_js() -> dict[str, str]:
    """Every script the app serves, comments removed, keyed by file name."""
    out = {"app.js": strip_js_comments((WWW / "app.js").read_text(encoding="utf-8"))}
    for extra in ("dashboard.js", "sync_queue.js", "travel.js", "travel-coach.js",
                  "travel-stats.js"):
        path = WWW / extra
        if path.exists():
            out[extra] = strip_js_comments(path.read_text(encoding="utf-8"))
    return out


def rendered_text() -> dict[str, str]:
    """app.js and index.html with comments blanked — what a user can actually be shown."""
    out = served_js()
    out["index.html"] = strip_html_comments(
        (WWW / "index.html").read_text(encoding="utf-8"))
    return out


def where(text: str, needle: str) -> str:
    lines = [f"line {k}: {line.strip()[:120]}"
             for k, line in enumerate(text.splitlines(), 1) if needle in line]
    return "\n".join(lines)


# People and places that were written into the served markup as though the app had found
# them. Every one of these was on screen for a user who had matched with nobody.
INVENTED = [
    "Elena", "Marcus T", "Sophia", "Alex V", "alex_v", "elena_s",
    "Fabrica", "Miradouro", "Lukas", "Acme AI",
    "88% Density", "94% Match", "96 Karma", "Guaranteed Crew Host",
]


@pytest.mark.parametrize("name", INVENTED)
def test_no_invented_person_or_venue_is_written_into_the_front_end(name):
    for filename, text in rendered_text().items():
        assert name not in text, (
            f"{filename} puts {name!r} on the screen. Nobody by that name is in anybody's "
            f"graph — it is markup, not a response.\n{where(text, name)}")


# Response keys that existed before T2 and do not exist after it. A renderer that still
# reads one of them writes `undefined` into the output panel, which looks to a user like
# an answer.
DEAD_KEYS = {
    "steward_guarantee": "/seeding/anchor-outings",
    "weekly_anchors": "/seeding/anchor-outings",
    "landmark_events": "/events/landmark-radar",
    "season_title": "/events/landmark-radar",
    "total_landmark_events": "/events/landmark-radar",
    "next_turn": "/routing/group-nav",
    "group_members_on_route": "/routing/group-nav",
    "waypoints_count": "/routing/group-nav",
    "grant_status": "/community/micro-grants",
    "community_fund_pool": "/community/micro-grants",
    "active_speakers": "/voice/crew-huddle",
    "noise_suppression": "/voice/crew-huddle",
    "voting_mechanism": "/dao/community-treasury",
    "active_proposals": "/dao/community-treasury",
    "pass_code": "/events/vip-guestlist",
    "access_tier": "/events/vip-guestlist",
    "curated_micro_escape": "/travel/layover-discovery",
    "gate_return_alarm": "/travel/layover-discovery",
    "safe_exploration_time": "/travel/layover-discovery",
    "photos_scanned": "/memories/analog-film-swap",
    "shared_album_url": "/memories/analog-film-swap",
    "film_stock": "/memories/analog-film-swap",
    "simulation_metrics": "/simulation/full-day-ux-optimizer",
    "simulated_24h_timeline": "/simulation/full-day-ux-optimizer",
    "profiles_evaluated": "/simulation/multi-demographic-suite",
    "universal_ux_score": "/simulation/multi-demographic-suite",
    "sub_vocal_whispers": "/wearables/ambient-whispers",
    "eyes_up_guarantee": "/wearables/ambient-whispers",
    "connected_peers": "/mesh/offline-peer-sync",
    "transport_protocol": "/mesh/offline-peer-sync",
    "edge_nodes": "/infra/edge-replication",
    "replication_latency": "/infra/edge-replication",
    "consensus_protocol": "/infra/edge-replication",
    "native_capabilities": "/native/app-store-manifest",
    "ios_bundle_id": "/native/app-store-manifest",
    "android_package": "/native/app-store-manifest",
    "social_readiness": "/wearables/sync-telemetry",
    "recovery_score_pct": "/wearables/sync-telemetry",
    "battery_boost": "/wearables/sync-telemetry",
    "svg_vector_url": "/wearables/tshirt-badge",
    "print_specs": "/wearables/tshirt-badge",
    "trust_score": "/connect/profile/{handle}",
    "mutual_nodes_count": "/connect/profile/{handle}",
    "karma_awarded": "/connect/scan-vouch",
    "verified_via": "/connect/scan-vouch",
    "total_third_places": "/seeding/third-places-directory",
    "live_status": "/seeding/third-places-directory",
    # The worst one in the file, and the one the browser walk found rather than a Python
    # assertion: the SOS panel said "Location Broadcasted to 4 Trusted Crew Members" and
    # printed an emergency PIN, over a route that answers `push_delivered: False`.
    "emergency_pin": "/safety/emergency-sos",
    "recipients_notified": "/safety/emergency-sos",
}
# `venue_name`, `perks` and `treasury_balance` are deliberately NOT in that list: each is
# still a live key on a different route the PWA also calls (the activity heatmap, the
# sponsored-perks list, `/treasury/status`). Banning the bare word would have failed on
# working code, so the venue-programme card is pinned positively below instead.


@pytest.mark.parametrize("key,route", sorted(DEAD_KEYS.items()))
def test_no_renderer_reads_a_response_key_that_no_longer_exists(key, route):
    # Whole word: `pass_code` must not match `fastpass_code`, which is a different route's
    # live key. A substring check here reported a defect that was not there.
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])")
    for filename, text in served_js().items():
        assert not pattern.search(text), (
            f"{filename} reads {key!r}, which {route} stopped returning. That renders as "
            f"the string 'undefined' in the output panel.\n{where(text, key)}")


def test_no_inline_onclick_handlers_survive():
    """`onclick="toast('Friend request sent to Elena!')"` was the whole implementation of
    a Connect button. An inline handler is how that ships: there is no function to write,
    so a toast can stand in for the action. Every other button here names a handler.

    Scoped to the two files this ticket owns. `dashboard.js` has one of its own and is
    somebody else's to change."""
    for filename in ("app.js", "index.html"):
        text = rendered_text()[filename]
        assert "onclick=" not in text, (
            f"{filename} still has an inline onclick. Use on(\"[data-act=...]\") so the "
            f"button has something real behind it.\n{where(text, 'onclick=')}")


def test_the_venue_programme_card_reads_what_the_route_now_returns():
    """The old card read `p.venue_name`, `p.schedule` and `p.perks` — a weekly schedule and
    a discount neither venue had agreed to. The replacement is one person's note about a
    place, and the sentence saying so is the route's own."""
    app = served_js()["app.js"]
    for key in ("not_official", "posted_by_handle", "p.venue", "p.starts_at"):
        assert key in app, f"the venue-programme card stopped reading {key!r}"
    assert "Verified Partners" not in app
    assert "exclusive perks" not in app


def test_every_path_the_pwa_calls_is_served():
    """The lead's `dead_routes.py`, as a test. A path the gateway does not declare is a
    button that throws on click, and no Python test has ever noticed one."""
    js = "\n".join(served_js().values())
    called = set(re.findall(r"""api(?:Delete)?\(\s*[`"'](/v1/[^`"'?\s]+)""", js))
    called |= set(re.findall(r"""fetch\([^)]*?[`"'](/v1/[^`"'?\s]+)""", js))

    api_src = (GATEWAY / "modules_api.py").read_text(encoding="utf-8")
    main_src = (GATEWAY / "main.py").read_text(encoding="utf-8")
    served = {"/v1" + p for p in re.findall(r'@router\.\w+\("([^"]+)"\)', api_src)}
    served |= set(re.findall(r'@app\.\w+\("(/[^"]+)"', main_src))

    def norm(path: str) -> str:
        return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "*", path)

    served_n = {norm(s) for s in served}
    dead = [c for c in sorted(called)
            if norm(c) not in served_n
            and not any(norm(c).startswith(s.rstrip("*"))
                        for s in served_n if s.endswith("*"))]
    assert not dead, f"the PWA calls paths the gateway does not serve: {dead}"


def test_the_matcher_cards_render_from_a_response_rather_than_from_markup():
    """The counterpart to the name check: the cards that used to hold invented people have
    to be reading a real route, not merely have had the names deleted."""
    app = served_js()["app.js"]
    for act, route in (("match-new-friends", "/v1/synergy/instant-match"),
                       ("find-tomorrow-am", "/v1/synergy/instant-match"),
                       ("find-tomorrow-pm", "/v1/synergy/instant-match")):
        block = app.split(f"[data-act={act}]", 1)
        assert len(block) == 2, f"the {act} handler is gone"
        body = block[1][:1400]
        assert route in body, (
            f"the {act} card no longer calls {route} — if it renders anybody at all, it "
            f"is inventing them")


def test_the_outings_attended_card_still_reads_its_honest_keys():
    """The lead replaced the "Verified Real-World Meeter" badge and its 85% reliability
    rating with a count of what you turned up to. Nothing in this ticket may quietly undo
    that, so the keys it reads are pinned here."""
    app = served_js()["app.js"]
    assert "Outings attended" in app
    for key in ("not_verification", "attended", "share_text", "suggestion"):
        assert key in app, f"the outings-attended card stopped reading {key!r}"
    assert "Verified Real-World Meeter" not in app
    assert "trust/badge" in app, "the card stopped calling /v1/trust/badge"


def test_no_card_asserts_a_verification_or_a_guarantee_in_its_own_label():
    """Copy that claims for itself what the route refuses to claim. `not_official` and
    `no_audio` are the gateway's own words and are rendered from the response; these are
    the labels that were written beside them."""
    banned = ["Verified Partners", "VIP Fast-Track", "Fast-Pass VIP",
              "Guaranteed", "Pass Verified", "Verified Third Places",
              "Verified Badges", "Karma",
              # Nothing here messages anybody: `push_delivered` is a pinned invariant.
              "Broadcasted", "BROADCAST", "Trusted Crew Members"]
    for filename, text in rendered_text().items():
        for phrase in banned:
            assert phrase not in text, (
                f"{filename} asserts {phrase!r} in its own copy.\n{where(text, phrase)}")
