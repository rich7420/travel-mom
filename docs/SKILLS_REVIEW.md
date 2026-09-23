# OpenClaw Skills review for Mom Travel Desk v0.6

Reviewed: 2026-08-25

## Findings from current OpenClaw

### Skills are the correct workflow layer

OpenClaw skills are directories with a `SKILL.md` file containing YAML frontmatter and instructions. Eligibility is resolved at run time, and per-agent skill allowlists can expose different sets to the conversational and browser agents.

For this project, that means:

- use Skills for stable travel workflow knowledge;
- use the application for state, validation and irreversible-action policy;
- do not turn every department into a persistent autonomous agent;
- keep the Browser worker's skills narrow.

### Reuse the bundled browser skill

The browser plugin provides `browser-automation`, including the longer operating loop for tabs, snapshots, stable refs, stale-ref recovery and manual blockers. Our `airline-official-search` skill should specify travel business constraints, not duplicate low-level browser mechanics.

### Workspace skills are preferable for this pilot

Workspace skills are scoped to the Mom workspace and have high precedence. They can be reviewed with the project, versioned and audited. This is safer than installing many community skills into a browser profile that may later contain customer or member-account context.

### Skill Workshop/self-learning should be governed

OpenClaw's Skill Workshop and self-learning flow can propose or apply workspace skill changes. For an airline booking workflow, autonomous application is too aggressive for the first pilot. The recommended posture is:

```text
self-learning = propose
site-change observation
  ↓
proposal with evidence
  ↓
human review
  ↓
recipe/skill patch
  ↓
new regression test
  ↓
audit + Browser Lab rerun
```

The current `site-change-proposal` skill is admin-only and does not have write tools. It produces a patch proposal rather than editing live recipes.

## Community skills/plugins reviewed

### Trip.com TripGenie

Useful pattern:

- one travel-query router;
- handles multiple travel intents;
- API-backed rather than pure browser scraping.

Not adopted directly because the pilot's business requirement is official airline/hotel websites and internal case workflow, not replacing the supplier/search channel with Trip.com.

### Expedia OpenClaw plugin

Useful pattern:

- real availability and booking links through a provider adapter;
- no browser scraping;
- plugin tools can be allowlisted.

This may become a useful comparison/discovery provider later, especially for hotels. It does not replace official-site revalidation and Mom's existing direct-booking habit.

### OpenClaw Tour Planner / TripAI / other travel skills

Useful patterns:

- natural-language travel intent routing;
- itinerary/weather/attraction decomposition;
- Chinese-language travel query handling.

We borrow UX and routing ideas, but do not install them into the privileged Browser Agent. General travel-planning skills may eventually be evaluated for the non-browser `mom-travel` agent after code/security review.

### TripIt Calendar

Useful pattern:

- narrow routing contract that clearly states when the skill should and should not trigger.

Our skills now use similarly narrow descriptions to avoid invoking live flight search for unrelated itinerary-history questions.

## Current local skill set

### Conversational/workflow agent

| Skill | Purpose |
|---|---|
| `search-run-coordinator` | gather missing search fields and create/resume a run |
| `flight-search` | understand flight requirements |
| `flight-shortlist` | explain validated comparison tradeoffs |
| `hotel-search` | hotel requirement intake; real provider work is future |
| `itinerary-builder` | construct practical itineraries |
| `customer-reply` | draft travel-agent customer replies |
| `quotation` | prepare customer-facing quotation draft |
| `visa-check` | enforce authoritative-source requirement |
| `pretrip-briefing` | build pre-trip material |
| `daily-radar` | explain prioritized case work |

### Browser worker

| Skill | Purpose |
|---|---|
| bundled `browser-automation` | browser mechanics |
| `airline-official-search` | official domain, typed output and safety contract |
| `price-revalidation` | exact selected-option revalidation |
| `booking-preflight` | gather/check evidence before human checkout |

### Admin-only review

| Skill | Purpose |
|---|---|
| `browser-lab-reviewer` | interpret attempts without overstating success |
| `site-change-proposal` | propose reviewed recipe updates from evidence |

## Why community skills are not blindly installed

A travel skill can bring code, CLI dependencies, persistent browser state, external APIs and broader tool requests. Browser profiles can contain authenticated sessions, and the Gateway token is highly privileged. Therefore:

1. inspect Skill Card/files/requirements;
2. pin version or commit where possible;
3. verify tool/environment needs;
4. run in a disposable workspace/profile;
5. keep it off the Browser Agent until reviewed;
6. add local regression tests around any adopted behavior.

## Audit rules in this repository

`python scripts/audit_skills.py` checks:

- YAML frontmatter exists;
- `name` matches folder and naming rules;
- description is present and reasonably scoped;
- browser/payment safety language is present where required;
- admin-only skills are marked appropriately.

This is static review, not a malware scanner or runtime proof.

## Sources reviewed

- OpenClaw Skills: `https://docs.openclaw.ai/tools/skills`
- Creating Skills: `https://docs.openclaw.ai/tools/creating-skills`
- Skills Config: `https://docs.openclaw.ai/tools/skills-config`
- Browser: `https://docs.openclaw.ai/tools/browser`
- Browser Control: `https://docs.openclaw.ai/tools/browser-control`
- Skill Workshop: `https://docs.openclaw.ai/tools/skill-workshop`
- Self-learning: `https://docs.openclaw.ai/tools/self-learning`
- Gateway Security: `https://docs.openclaw.ai/gateway/security`
- ClawHub TripGenie, Expedia Travel, Tour Planner, TripAI, TripIt Calendar entries.
