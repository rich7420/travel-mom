# Lifecycle and recovery verification · 2026-10-03

This increment completes explicit business closure/reopening and reproducible local backup, recovery and browser verification. It uses synthetic records only; no supplier booking, payment, customer message, public Tunnel or identity-provider account was created.

## Implemented

- Dedicated evidence-bearing close/reopen commands, stale-state fingerprints, actor-bound UUID replay, atomic status/event/audit writes and additive schema 804. Lifecycle events reject SQL updates/deletes.
- Completed vs withdrawn closure blockers, supplier-settlement attestation, explicit audited quote-adoption withdrawal, and reopening derived from current records. Legacy closed cases can reopen after checking.
- Closed case write guards and history-only UI, including search/option history and direct sales entry paths. Planned/queued searches do not block closure; actual running work does. Admin-only evidence operation for a stopped, stuck worker.
- New-file-only validated SQLite backup/restore, committed WAL coverage, no replacement of existing targets or sidecars, schema/trigger/integrity/FK checks and 0600 atomic publication.
- Generated Traditional Chinese guide chapter with stable `#lifecycle` anchor; architecture, workflow coverage and recovery/deployment instructions updated. Software version remains absent from visible UI.

## Reproducible evidence

- Python 3.12 and Python 3.11 suites: **193 passed each**. Suites run sequentially because the test fixture shares a fixed temporary database.
- Chromium (local Chrome), Playwright Firefox and Playwright WebKit: **62 checks each**, no JavaScript errors. Includes dirty/save/auth/stale-generation regressions, lost close response with one retry UUID/event, stale lifecycle rejection, history-only closed search and option views, direct closed sales entry rejection, all open task edit actions, keyboard reopening and 390/768/1360 extra-large-font no-overflow.
- Docker: **14 hardened-container checks passed**. Production token rejection; non-root/read-only-root filesystem, tmpfs, dropped capabilities and no-new-privileges; Mom/admin/guide assets; actual request body limit; 100 synthetic writes with 8 workers; restart preserves 101 cases; live snapshot and read-only-source restore to a second volume; restored HTTP read/write plus both close/reopen events and immutability triggers. All owned containers and volumes removed by label-checked cleanup.
- Full repository Dockerfile image built earlier this turn. Final clean rebuild stalled while fetching registry metadata. Runtime verification used that freshly built full image as a local base and copied current app/scripts with the original non-root owner. This verifies the current application under the existing installed dependencies; it does not assert a successful fresh final registry/dependency resolution. No Dockerfile behavior changed.
- Node syntax, generated-guide drift, **23 local skill checks** and diff whitespace verified. No travel legal rules or contract text changed; official Python SQLite, Docker and Playwright technical references were checked and linked in architecture/runbook.

Commands:

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/python scripts/verify_mom_workspace.py --browser chromium --chrome /path/to/chrome --output data/lifecycle-review/chromium
.venv/bin/python scripts/verify_mom_workspace.py --browser firefox --output data/lifecycle-review/firefox
.venv/bin/python scripts/verify_mom_workspace.py --browser webkit --output data/lifecycle-review/webkit
.venv/bin/python scripts/verify_container.py --image travel-mom-verify:local
.venv/bin/python scripts/build_user_guide.py --check
.venv/bin/python scripts/audit_skills.py
```

Ignored `data/lifecycle-review/` retains synthetic screenshots, reports, container drill output and read-only CLI reviewer transcripts. The tracked scripts are the repeatable evidence; runtime reports are not committed as product assets.

## Independent reviews

Design and implementation checkpoints: Claude Code for backend (security, concurrency, schema and public API); Cursor Agent with the dynamically selected high-reasoning GPT model for frontend. Both found substantive issues that were confirmed and fixed: planned searches blocking closure and closed search-history mutation affordances. Final third-round verdict: **Claude APPROVE; Cursor APPROVE**. Claude's final recommended recovery gap (running revalidation under a completed run, or standalone running task) was fixed with the same locked evidence pattern and stale/attestation/idempotence/role tests. Cursor's final minor suggestions (cross-tab close refresh, generated-draft keyboard focus and adopted-quote withdrawal UI coverage) were fixed and exercised by the final 62-check runs. The supplied three-round limit was respected; these narrow post-verdict corrections have regression evidence without a fourth independent review.

Accepted backend minors: two audit rows retain stop evidence plus the generic command trace; legacy browser write routes keep their 400 error contract while new closed-run/start routes use 409; administrative abandonment requires actually stopping/waiting for the in-process call, rather than claiming automatic remote cancellation. Late callbacks on an open case remain an operational limitation; closed business writes are guarded. No blocker/major reviewer disagreement remains.

## Still outside local evidence

Real Cloudflare Access policies/IdP/MFA/cookies/DNS/Tunnel; physical phone/Safari and assistive technology; Mom's real workload and supplier confirmation checks; long-duration/multi-process load, operational RPO/RTO, automated backup scheduling/encryption/retention and a fresh final dependency build remain unverified. The modest concurrent smoke is not a throughput benchmark. Configuration readiness and liveness do not prove production recovery or login.

Next product priorities remain passenger roster and controlled original attachments, authorized reminders/handovers, and dedicated change/cancellation/incident workflows. OpenClaw stays optional behind this web interface. The current increment does not add external notifications or store passport scans.


## Local preview upgrade

The active loopback preview at `127.0.0.1:8001` was backed up with the validated SQLite API before schema 804, then restarted. Mom, admin, guide and liveness return 200. All original **42 cases**, offers/selections and agency business records compare exactly with the pre-upgrade snapshot. No real case was closed or edited during verification. The private snapshot is ignored under `data/lifecycle-review/live-before-804.db`.
