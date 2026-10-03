# Mom Travel Desk — POC v0.8.1

A **case-based, guided, proactive travel-agency copilot** built for a non-technical operator. The default UI is now a real “Mom Mode”: the user starts from today’s work or a customer case, not from prompts, agents, Browser Labs, or configuration screens.

> Product rule: **the operator should not have to learn Claude/OpenClaw. The system should learn the travel-agency workflow.**

## Current review and handoff documents

Reviewed on 2026-10-03 against the running v0.8.1 checkout:

- [Developer architecture](docs/DEVELOPER_ARCHITECTURE.md) — English implementation map, data flows, setup, and operational limits.
- [User guide draft](docs/USER_GUIDE_ZH_TW_DRAFT.md) — Traditional Chinese source for the [in-web guide](http://127.0.0.1:8001/static/guide.html), accessible from Mom Mode and its task dialogs.
- [Workflow coverage check](docs/WORKFLOW_COVERAGE_ZH_TW.md) — supported daily tasks, operational gaps and concrete next increments.
- [Current review and improvement direction](docs/REVIEW_AND_DIRECTION_ZH_TW.md) — verified findings, travel-agency workflow gaps, priorities, and acceptance criteria.

The review preview runs at <http://127.0.0.1:8001/> with a separate local database because port 8000 is occupied by another checkout. OpenClaw, LINE, and Telegram are disabled in this preview.

## Current web workflow increment

OpenClaw is optional. The shared web backend now supports consecutive customer intake, validated case edits with infant/child-age preservation, saved search requirements, manual supplier offers, comparison and persistent selection, and editable/copyable deterministic customer drafts. Expired, demo, changed-case or replaced offers cannot supply active quote amounts. Internal manual supplier/source metadata stays out of drafts. See the current handoff documents for operating limits; schema 803 adds immutable quote versions, deadline/owner tracking, verified booking confirmations, manual currency ledgers, document readiness and pretrip summary handoff. Actual supplier transactions, money transfers, customer messages and original attachments remain manual. See [agency verification](docs/AGENCY_OPERATIONS_VERIFICATION.md).

## Interface and tunnel login preparation

Mom Mode uses a warm paper and navy travel workspace, desktop side navigation, consistent line icons and numbered priority cases. The workspace adapts from two desktop columns to a single column with bottom navigation on mobile; secondary search history stays collapsed. Large text and touch controls remain available. See [visual and interaction QA](design/qa.md). Visible versions were removed from both UIs; engineering metadata and HTML comments retain the version.

For future public Tunnel deployment use the optional Cloudflare Access mode, with signed JWT verification, explicit operator/admin accounts, protected pages/APIs, origin checks and bounded key refresh. See [deployment and InsForge decision](docs/CLOUDFLARE_ACCESS_DEPLOYMENT.md). The local preview remains in token/development mode; no public tunnel is provisioned.

## What changed in v0.8.1

v0.8.1 is rebuilt from the last verified v0.7.1 baseline and uses the **same core database**. It does not create a second UX database.

- `/` — new mobile-first **旅行社小幫手** UI.
- `/admin` — the previous engineering/operator workbench, including Browser Lab and site-trust controls.
- Today view with **Next Best Action**, priority cases, recent cases, and resumable searches.
- One-question-at-a-time intake with **back / save / resume / reset**, common shorthand such as `2大1小`, and saved default airport.
- “不知道怎麼問” intent helper that turns ordinary language into a small set of concrete next steps.
- Flight and hotel searches can be created from the Mom UI, started in the background, left, and reopened later.
- Customer-reply drafts now have explicit feedback: **👍 accepted / ✏️ edited / 🧠 prefer future / 👎 rejected**.
- Skill feedback is deterministically redacted, attributed to the exact `SKILL.md` SHA-256 when possible, and stored as **evidence only**.
- Four new workspace Skills: `mom-mode`, `guided-intake`, `skill-feedback-capture`, `skill-evolution-proposal`.
- Strict Content Security Policy for Mom Mode; legacy inline scripting is isolated under `/admin` only.
- 62 automated tests pass; total measured coverage is 80%.

## Important Skill-evolution boundary

v0.8.1 implements the **safe first half** of an evolving Skill system:

```text
real usage
  → explicit Mom feedback
  → local PII redaction
  → exact Skill hash attribution
  → evidence buffer / summary
  → offline export
  → future candidate + validation gate
```

It does **not** automatically edit live `SKILL.md` files. A future optimizer must pass held-out and safety regression tests and human approval before promotion.

The following rules are permanently outside autonomous Skill evolution:

- payment, card/CVV and final ticket/booking submission;
- OTP / 3DS / CAPTCHA and human-login handoff;
- official-domain / hotel-site trust controls;
- PII handling and vault rules;
- browser/tool/sandbox permissions;
- authoritative evidence requirements for visa/entry and changing travel facts.

Read [Skill Evolution v0.8.1](docs/SKILL_EVOLUTION_V081.md).

## Current travel workflow

```text
Mom Mode / LINE later
        │
        ▼
      TripCase  ← persistent system of record
        │
        ├── Next Best Action / Daily work
        ├── Customer reply draft + feedback evidence
        │
        ├── FlightSearchRun
        │     └── CI / BR / CX / JX / AE / IT / EK / NH official sites
        │
        └── HotelSearchRun
              └── trusted official hotel sites
                       │
                       ▼
             typed result validation
                       │
                 compare / revalidate
                       │
                booking preflight
                       │
                  HUMAN checkout
```

## Airline coverage in the POC

- CI — China Airlines / 華航
- BR — EVA Air / 長榮
- CX — Cathay Pacific / 國泰
- JX — STARLUX / 星宇
- AE — Mandarin Airlines / 華信
- IT — Tigerair Taiwan / 台灣虎航
- EK — Emirates / 阿聯酋
- NH — ANA / 全日空

The live reliability of these websites still needs Browser Lab testing on the actual OpenClaw host. Offline recipes and typed contracts passing tests is **not** a claim that every live airline UI works today.

## Hotel official-site coverage

Built-in trusted networks:

- Marriott
- Hilton
- Hyatt
- IHG
- Accor
- Shangri-La

Independent hotels require an explicit human-approved exact-domain `HotelSiteGrant`. Known OTA/search sites are not accepted as hotel official sites.

## Run locally

```bash
cd /path/to/your/checkout
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]' -c constraints-tested.txt
uvicorn app.main:app --reload --host 127.0.0.1 --env-file .env
```

Open:

- Mom Mode: <http://127.0.0.1:8000/>
- Admin workbench: <http://127.0.0.1:8000/admin>

For a real upgraded database, set `TRAVEL_DESK_DB` to the existing v0.7.1 DB **after taking a backup**. Migration 801 creates the v0.8.1 preference/feedback tables and retains existing TripCases/search runs. See [Migration guide](docs/MIGRATION_V071_TO_V081.md).

## Connect OpenClaw

Keep the Gateway private and configure the backend only:

```env
OPENCLAW_ENABLED=true
OPENCLAW_BASE_URL=http://host.docker.internal:18789
OPENCLAW_GATEWAY_TOKEN=...
OPENCLAW_MODEL=openclaw/mom-travel
OPENCLAW_BROWSER_MODEL=openclaw/mom-travel-browser
OPENCLAW_BROWSER_PROFILE=openclaw
```

Copy the entire `openclaw/skills/` tree recursively, including nested `references/`, into the Mom Travel workspace, retain sibling skill directories, and copy `openclaw/AGENTS.md` as workspace rules. Adapt `openclaw/openclaw.example.json5` to the host setup.

The [official-source policy](openclaw/skills/visa-check/references/official-sources.md) requires fresh original-source checks for regulatory/document claims, applicable-date matching and explicit unresolved items. Its dated registry is discovery guidance, not a live eligibility service; these repository instructions do not prove a Gateway installation has been updated.

The conversational agent does not get browser/shell/write tools. The browser worker gets only the bounded browser surface and typed BrowserTasks.

## Export Skill feedback for offline evaluation

```bash
python scripts/export_skill_feedback.py \
  --skill customer-reply \
  --output ./data/customer-reply-feedback.jsonl
```

Only the redacted evidence records are exported. This command never modifies a Skill.

## Test

```bash
pytest -q
python -m compileall -q app scripts tests
node --check app/mom_static/app.js
node --check app/admin_static/app.js
python scripts/audit_skills.py
python scripts/audit_airline_recipes.py
python scripts/audit_hotel_recipe.py
python scripts/run_v06_demo.py
python scripts/run_v07_demo.py
```

The guide is a checked-in static asset generated from the Traditional Chinese manual. After changing the manual or guide template, regenerate it; the check below and pytest catch stale output. The renderer is a development dependency, not a runtime requirement.

```bash
python scripts/build_user_guide.py
python scripts/build_user_guide.py --check
```

Historical results are in [TEST_REPORT_V081.md](docs/TEST_REPORT_V081.md); current guide and UI checks are in [design QA](design/qa.md).

## Production boundaries

This is still an **internal POC**, not a production ticketing or booking service. It intentionally does not automate final payment, ticket issuance, refunds/cancellations, CAPTCHA/OTP/3DS, or credit-card handling. Live LINE OA, real OpenClaw Browser sessions, and production database/KMS/RBAC/backup work remain deployment milestones.
