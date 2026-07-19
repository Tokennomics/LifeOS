# Life OS Module SDK — spec v0 (dogfooded, not yet open)

A module is a unit that **reads from and writes to the shared context graph** (Law 1).
No graph contribution → no ship. Every first-party module (horizon, reconnect, convoy,
memento, steward, vitals, ledger, calibre, hearth, voiceos, calendars) follows this spec;
the external SDK opens at 2,000 WAU (Law 4).

## Contract

1. **Manifest** — `module.yaml` validating against `manifest_schema.json`: name, scopes,
   bus topics, declarative `ui_cards`, `ai_budget`.
2. **Scoped graph access** — modules never touch the DB. They receive a
   `graph.session(module_name, scopes)` and every write carries provenance
   (`source`, `confidence` → an `observations` row). Scope grammar: `<domain>:<read|write>`.
   Edge writes need write on the src kind + read on the dst kind.
3. **Bus** — publish/subscribe on the fixed topic set. Publishing is how other modules
   get smarter from your work (the compounding KPI is cross-module consumption).
4. **AI calls** — only through `gateway.claude` (server-side, cached, budgeted). Modules
   declare `heavy` or `light` default routing. Every AI feature MUST have a deterministic
   offline fallback: no key, still works.
5. **Surfaces** — modules don't own screens; they expose `/v1/...` endpoints and declare
   `ui_cards` the app renders. The app renders, never thinks (Law 8).

## Distribution (future marketplace)

- Modules run as MCP servers mounted by the gateway; scope grants happen at install,
  OAuth-style, shown to the user in plain language.
- Revenue split 80/20 dev-favoring; metered AI at cost-plus.

## Checklist for a new module

- [ ] `module.yaml` validates against the schema
- [ ] All writes go through a scoped session with provenance
- [ ] Publishes at least one bus topic or consumes another module's data
- [ ] Offline fallback for every AI path
- [ ] Tests: core logic + one gateway roundtrip
