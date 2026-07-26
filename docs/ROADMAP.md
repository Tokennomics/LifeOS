# LifeOS — Roadmap (PARKED until the v0.1 gate passes)

_Written 2026-07-24, extended 2026-07-26 (Phase 3b — dating). This is a **parked** map, not a work queue. Nothing here is built until
the v0.1 gate passes (28 days of daily self-use; check `/gate`). By the product's own
distraction-sink rule: **captured, not abandoned — current gate first.** Re-read `docs/STATUS.md`
for what's actually shipped._

## The one rule that governs this whole map

**Substrate now, one autonomy layer next, everything else gated behind real users.** Over-scoping
is the primary risk. Each phase must *earn* the next through a kill-gate — a measurable condition,
not a vibe. If the core Life OS isn't retained and used daily, none of the three layers below
matter yet, and the correct action is to keep using it and build nothing.

---

## North star: personal agents that operate *within* LifeOS to deliver compounding value

The destination for the agentic layer is **personal agents running inside LifeOS that do real work
for the user** — draft the week, surface the reconnect, triage the day, prepare the retro — on the
user's own graph, on hardware the user controls. Not a chatbot bolted on; agents that read the
shared context graph, propose actions, and (with permission) execute them, getting more autonomous
as they earn trust. That is a genuine goal. The discipline below is how it gets built *safely and
sequenced*, not whether it gets built.

---

## Three layers, the calls, and what already exists

### 1. Agentic OS — **single orchestrator + typed durable workflows + propose-only** (NOT a swarm)
The 2026 production consensus converged on an **orchestrator that spawns ephemeral, isolated
sub-agents returning compressed summaries** — not a society of chatty peers negotiating. Single
agents match or beat multi-agent setups on most tasks at a fraction of the token cost; peer
negotiation is where pilots fail and where prompt-injection/collusion lives.

- **Pattern:** one competent router (we already have the Claude intent router) + a few typed,
  single-purpose module agents + durable execution (workflow/activity split, idempotent activities,
  transactional-outbox so a replay never double-books an event or double-sends a message) + a
  per-run token/AI budget.
- **Autonomy is a per-action dial:** **L0** propose-only (drafts a UI card, nothing executes) →
  **L1** approve-to-execute (user taps approve) → **L2** autonomous-within-budget (execute, log,
  keep an undo). Default every new agent capability to L0/L1.
- **Already in the repo:** `substrate/graph.py` is the only write path and records **provenance**
  (source + confidence → an `observations` row) on every write — a natural checkpoint/audit store.
  Graph **sessions enforce capability scopes** (`goals:write`, …) architecturally, not by prompts.
  The **propose-only ethos already ships**: Reconnect *drafts → you copy → you send*; Steward
  *approve-to-schedule*; Convoy invites are drafted, never auto-sent. `create_entity` accepts a
  stable `entity_id` (idempotency-key friendly); the Travel export already carries stable keys +
  timestamps. **BYOK / offline-first** ("works with no key, better with one") means we never have to
  subsidize AI cost.
- **NOT built until gated:** any inter-user, agent-to-agent negotiation; any L2 autonomy on a fresh
  capability; anything that touches money, another person, or the outside world without a human gate.

### 2. Urgency / Triage OS — **build this, NOT a safety-critical "Emergency OS"**
The genuinely life-saving part (accurate location to a dispatcher) is already solved by OS/carrier
**AML/112**, is on every modern phone, needs no app, and is **closed to third-party apps**. A solo
dev cannot match it and would inherit a life-safety reliability bar plus medical-device / negligence
/ wrongful-death exposure. So:

- **Build:** a first-party **triage/interruption layer** — priority inbox, deadline triage,
  conditional-interruption rules, a single "top" escalation slot, quiet hours, a daily
  "what matters" briefing — reading the existing graph (Horizon deadlines, calendar) + intent router.
  Pure software risk, high daily value, reuses most existing infra.
- **Build (heavily disclaimed):** a static, user-authored **critical-info card** (like Medical ID) —
  stores and displays, never detects or dispatches; and a **manual, best-effort dead-man's-switch**
  that pings *private* contacts only, framed as "peace-of-mind reminders," never a guaranteed system.
- **DO NOT build:** automated crisis/self-harm/fall detection; any auto-dial to 112/911/PSAPs;
  anything implying clinical or life-safety guarantees; anything that "listens" for danger.

### 3. Developer platform — **first-party SDK + trusted-author cohort first; open SDK last**
Every durable ecosystem (Slack, Shopify, HA/HACS, GPT Store) dogfooded first-party and seeded a
vetted cohort before opening; premature openness is the #1 cold-start killer, and untrusted
third-party code/agents in a shared personal graph is an unsolved prompt-injection/exfiltration
problem.

- **Build the substrate for yourself now (you are the first developer):** the **manifest as an
  enforced capability boundary** — a module gets a token granting exactly its declared graph scopes
  (`read:interests`, never `read:notes`), bus topics, and AI budget; third-party writes are tagged,
  quarantinable, revocable wholesale. `sdk/manifest_schema.json` + `module_spec.md` already exist;
  the enforcement mechanism (scoped sessions) already exists — the gap is auto-wiring the manifest's
  declared scopes to the session instead of passing them by hand.
- **Declarative-first UI**, rendered by our client (Telegram/PWA) or a sandboxed iframe — never
  arbitrary code in-process. Isolation by trust tier: declarative-only (open) → WASM
  capability-sandbox (vetted logic) → microVM only for heavy untrusted compute. **Not** shared-kernel
  containers.
- **DO NOT build:** an open third-party SDK before multi-user validation; any third-party module with
  simultaneous private-graph read **and** external-tool call without a human egress gate (that exact
  combination is the documented exfiltration path).

---

## Phases and kill-gates

- **Phase 0 — Finish the validation gate (now).** No new layers. The only "substrate" worth touching
  is what's already scoped: idempotency + provenance on writes (mostly done; the rest **is T2**).
  **Kill-gate:** if the core isn't used daily, stop — nothing below matters.
- **Phase 1 — Agentic OS, single-user, propose-only (post-gate).** 2–3 scheduled/triggered agents at
  L0/L1 (e.g. Horizon weekly-plan drafter, Reconnect nudge drafter), wrapped in durable execution with
  per-run budgets. No inter-user features. **Kill-gate:** advance only if a majority of proposals are
  accepted and agents run ~2 weeks with **zero** unintended writes.
- **Phase 2 — Urgency/Triage OS (parallel-able).** Triage/interruption module + static info card.
  **Kill-gate:** ship the manual dead-man's-switch only with clear best-effort disclaimers, verified
  multi-channel delivery, and never touching emergency services; otherwise ship only the info card.
- **Phase 3 — Inter-user coordination, mediator-brokered (only after ≥2 real users).** Privacy-
  preserving Convoy coordinator: local preference vectors → neutral coordinator computes candidate
  {time, place} via private-set-intersection-style aggregation → **human ratifies**. Single round, all
  peer content treated as untrusted, human approval mandatory. **Kill-gate:** ≥2 users who actually
  want to coordinate.
  _Engine substrate built (`modules/coordinate/`, 1:1 reconnect case): pure ranking core + graph flow
  + `/v1/coordinate/*`, tested. Generalized to **crews** (`modules/crews/`): named groups with a topic
  + home city, quorum-based group scheduling, directory-shaped browse. The live cross-device feature
  (accounts, a reachable coordinator, the second user's app) is the remaining, still-gated arc._

### Crew directory ("subs" for crews) — the public layer, NOT yet built
The idea: crews as joinable, topic+place-scoped groups — land in a new city, join the local
climbing crew. The **group primitive and scheduling are built** (above); what a *public* directory
adds is a different product with obligations the local model doesn't have, and should be treated as
its own phase with its own kill-gate:
- **Identity + per-user isolation** — ✅ *built*: accounts, hashed credentials, revocable sessions,
  per-account `owner_id` scoping enforced down at the substrate. **Hosting is what's left** — a
  reachable server with TLS and backups. That's an ops decision (NucBox vs a VPS), not a design one.
- **Trust & safety** — ✅ *built*: block/unblock, auditable reports with a moderation queue,
  leave-always-allowed, admin-gated invite/approve, blocked users excluded from coordination.
- **Location privacy** — ✅ *city-level only* in the model (no coordinates on a crew); keep it that
  way in any public listing, and keep listing opt-in (`visibility: public` is explicit).
- **Discovery mechanics** — ✅ *built*: `admission = invite|approval|open` (admins choose who gets
  in, independent of listing), public events with topic+city, and intent-driven matching
  ("in Lisbon, want sushi night" → ranked public events/crews; private things never surface).
- **Sequencing:** private crews ✅ → invite/request lifecycle + safety ✅ → admission policy +
  intent discovery ✅ → accounts + isolation ✅ → **hosting (next)** → public directory across users.

**Cross-account public reads — ✅ built.** `GraphSession.find_public()` / `get_public()` are the
single, narrow crossing of the owner boundary: `attrs.visibility == "public"` is *forced* into the
query (a caller cannot widen it), it is read-only, and scope checks still apply. On top of it,
`crews.directory()` and the whole of `discover` (find / intents / feed) now span accounts, while
anything unpublished stays invisible even to someone who knows its id.

**Cross-account membership — ✅ built.** A member subject is now either a local `person` (your
own private record of someone you know — unchanged) or an **ACCOUNT** (who someone is across the
system, which is what shared crews are built from). Bruno can browse the directory, join a
drop-in crew or be approved into a curated one, appear in Ana's roster by handle, see it in his
own `my_crews`, and leave whenever he likes — with none of it requiring an entity in the other
person's graph.

The trust boundary that makes this safe: **the grants ACL is deliberately shared across accounts;
entity data is not.** Joining writes one ACL row about yourself and never touches the owner's
entities. It can only ever put you in `requested` (or `member`, where the admin declared the crew
open) — never `admin` — and every admin-gated action on a crew you don't own requires a real
admin grant, including on adminless public crews, where the "your own group stays open to you"
leniency deliberately does not apply.

**Cross-account scheduling — ✅ built.** A cross-account crew can now also be *scheduled*. Opening
a group session grants every current crew member `coord:participant` on the coordination, and
`GraphSession.get_if_granted()` / `update_if_granted()` make that grant the way a member in another
account reaches a session they don't own. `spaces_granted()` is the reverse index, so a participant
can find their sessions instead of being handed an id out of band.

Authorisation is deliberately **two things, not one**, because they answer different questions:

- the **grant** is what lets you *reach* the entity — without it the coordination is out of your
  owner scope and reads as missing;
- the **crew** is the authority on who *belongs*. A grant row needs only `content:write` to write,
  so on its own it is an index, not a permission. Membership is re-derived from the crew on every
  action, which is what makes a forged grant worthless and makes leaving or being blocked take
  effect immediately rather than at the end of whatever was in flight.

Two consequences worth keeping: quorum is computed over **current** members only (someone who left
can't be the reason a night goes ahead, even though they answered while they were in it), and the
confirmed meet is shared state on the coordination while a *calendar entry* is a local
materialisation — `add_to_calendar` writes it into your own graph, because nobody writes an event
into somebody else's.

**Still open here:** grants themselves are not owner-authenticated at the substrate level — any
session with `content:write` can write any row. Nothing exposed reaches that (the gateway only
offers module functions, and both crews and coordinate re-derive authority from the crew), but if
the ACL is going to carry more weight than this, `grant()` should learn who is allowed to write it.
Its own ticket; it touches crews as much as coordinate.
### Phase 3b — Dating: intent-based, mutual-consent, meet-through-shared-activity — NOT built

The owner's idea (2026-07-26): "seamless dating for people who want it." It fits — but it is a
**category change, not another crew type**, and this section exists so that is decided once,
while rested, rather than re-litigated at 1am with the machinery half-written.

**Why it fits.** Most of it already exists and is tested: accounts + per-account isolation,
interest matching (`modules/discover/core.py`), city + date-window intents ("in Lisbon 12–19 Aug"),
the mutual-consent coordinator (both humans ratify; nothing is auto-booked), block / unblock /
auditable reports, and — as of cross-account scheduling — a grant-shaped way to share exactly one
thing with exactly the people entitled to it. Dating is those pieces with the **consent gate turned
up**, not a new subsystem.

**The shape to build (and the shape NOT to).** Not a swipe app. **Intent-based, mutual-consent,
meet-through-shared-activity**: you go to the sushi night or the climbing crew you were going to
anyway, and interest is only ever *revealed when it is mutual*. That is differentiated (it is the
standing complaint about the swipe model), it is safer (first meetings are in public, in a group,
around an activity), and it reuses machinery already proven instead of starting a new one.

**The one hard invariant nothing in LifeOS currently satisfies:** *dating availability must never be
visible to a non-match.* `find_public` is exactly the wrong primitive here — it publishes to the
world by design. Dating needs the **grant** shape: nothing readable until a mutual match writes the
row, and the row revocable by either side, unilaterally, forever. Design it as "invisible until
mutual", not "visible with a low rank" — the same rule already enforced in `discover` (privacy is a
filter applied *before* scoring), held one notch stricter.

**Three obligations that are not choices:**

1. **Age assurance.** Legally required for a dating service and not satisfiable by a checkbox.
   A real dependency, not a nice-to-have — and it needs a third party, which means it is the
   first LifeOS feature that cannot be "works with no API key."
2. **Special-category personal data (GDPR Art. 9).** Orientation and relationship intent are not
   ordinary attributes. Different legal basis, different retention, different breach consequences,
   and the owner is EU-based. The standing rule "no secrets in the repo, ever" acquires a sibling:
   **no orientation or dating-intent data on any public-readable path, ever** — not in
   `find_public`, not in the feed, not in `reasons` strings, not in a crew roster.
3. **Physical safety of 1:1 stranger meetings.** A crew is a group with an admin. A date is one
   person alone with someone they met online. Reporting must work *after* the meet and outside any
   crew context, and a report about a person must be able to outlive the crew it happened in.

**Sequencing — this comes after hosting, and that is not negotiable.** Every item above needs a
reachable box with TLS and backups; a directory of real people looking for dates is a far worse
thing to run on a URL that can't be reached from a phone. It is also the first feature where
shipping it badly harms *users* rather than the owner.

**Kill-gates, in order — each must pass before the next is written:**
- **G0 — hosting.** TLS, backups, a reachable host. Nothing starts before this.
- **G1 — the invariant, proven.** A mutual-match gate with a test suite that proves a non-match
  cannot see dating availability: not by listing, not by id, not by feed, not by asking for
  `visibility=public`, not via a forged grant. Same standard the isolation work was held to —
  simulated with real accounts, not just unit-tested.
- **G2 — age assurance integrated** and failing closed (no assurance ⇒ no dating surface at all).
- **G3 — post-meet safety.** Report/block that works outside a crew, with a moderation queue that
  a solo operator can actually service. If it cannot be serviced, do not ship the feature.
- **G4 — real users.** ≥2 people who actually asked for it, per the Phase 3 gate. Building a
  dating product for a user base of one is the single most expensive way to learn nothing.

**Explicitly out of scope even after all gates pass:** location sharing finer than city level;
"who's nearby right now"; any auto-introduction the humans didn't both ratify; storing dating
intent on the same entity as anything published.

- **Phase 4 — Developer platform, vetted cohort (post multi-user validation).** Open to a handful of
  named authors: declarative-only + WASM sandbox + signed manifests + instant capability revocation.
  **Kill-gate:** automated capability diff/scan + instant revoke before any open SDK.

**Metrics that move the plan:** proposal-acceptance rate (gates autonomy escalation); any >0 unintended
external action → freeze autonomy; user count (gates inter-user + platform work); per-module AI spend
vs. budget (over-budget → degrade to propose-only).

---

## Do Not Build (with the reason, so it isn't re-litigated while tired)

1. **Open agent-to-agent negotiation between users' personal agents** — prompt injection is the #1
   unsolved LLM threat, defenses are bypassable, multi-agent adds collusion/loop/exfiltration surface.
   Use a bounded, human-ratified mediator instead.
2. **Automated crisis/self-harm/fall detection or auto-dispatch to 112/911** — medical-device +
   false-positive/alarm-fatigue + wrongful-death exposure a solo dev can't bound; OS-native AML/112 is
   superior and closed to third parties anyway.
3. **Any emergency feature implied as reliable/life-safety** — the reliability bar can't be met; route
   users to OS/112.
4. **An open third-party SDK before multi-user validation** — #1 cold-start killer; unsandboxed
   community plugins in a shared personal graph = HACS failure mode + unsolved exfiltration.
5. **Third-party modules with private-read + external-tool call and no egress gate** — the documented
   high-success exfiltration path.
6. **Shared-kernel containers as the isolation boundary for untrusted code** — use WASM / microVM.
7. **Betting cross-user negotiation on A2A** — A2A does discovery + delegation, not negotiation; keep
   cross-user logic in our own bounded coordinator.
8. **A swipe-style dating surface, or any dating feature before Phase 3b's gates** — orientation and
   relationship intent are GDPR Art. 9 data, age assurance is a legal precondition, and 1:1 stranger
   meetings carry a physical-safety duty a "visible with a low rank" privacy model cannot discharge.
   Build the mutual-consent, meet-through-shared-activity shape or build nothing.
9. **Precise (sub-city) location anywhere in the social layer** — crews, events, discovery, feed and
   dating are all city-level by design. "Who's nearby right now" is the feature that turns a
   directory into a stalking tool, and it cannot be retrofitted safely once the data exists.

---

## Notes on standards (as of mid-2026, treat as directional)

MCP (tool access, elicitation for mid-call human confirmation, OAuth 2.1 for remote servers) is mature
enough to build on when Phase 1 starts. A2A is usable for discovery/delegation but **cannot express
negotiation** — don't architect inter-user bargaining on it. Delegated-authority patterns (token
exchange, short-lived attenuated agent credentials, first-class revocation) must be designed *before*
any autonomy, not after. Some external citations in the source research are unverifiable and treated
here as decorative; the architecture conclusions stand without them.

---

_This map is parked. The next action is not on this map — it's `/gate`._
