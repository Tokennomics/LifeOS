# LifeOS — Roadmap (PARKED until the v0.1 gate passes)

_Written 2026-07-24. This is a **parked** map, not a work queue. Nothing here is built until
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
- **Identity + hosting** — accounts, a reachable server, per-user data isolation. Without this there
  is nothing to discover across users. **← the one remaining blocker.**
- **Trust & safety** — ✅ *built*: block/unblock, auditable reports with a moderation queue,
  leave-always-allowed, admin-gated invite/approve, blocked users excluded from coordination.
- **Location privacy** — ✅ *city-level only* in the model (no coordinates on a crew); keep it that
  way in any public listing, and keep listing opt-in (`visibility: public` is explicit).
- **Discovery mechanics** — ✅ *built*: `admission = invite|approval|open` (admins choose who gets
  in, independent of listing), public events with topic+city, and intent-driven matching
  ("in Lisbon, want sushi night" → ranked public events/crews; private things never surface).
- **Sequencing:** private crews ✅ → invite/request lifecycle + safety ✅ → admission policy +
  intent discovery ✅ → **accounts + hosting (next)** → public directory across users.
  Everything the directory needs is built except identity; the matching engine and the privacy
  invariants are already in place and tested, so hosting is plumbing rather than design.
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
