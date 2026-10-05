# Private workflows and operational recovery · 2026-10-05

This increment adds basic encrypted traveller records, original-document storage, whole-roster human verification, acknowledgement and atomic task handover, and scheduled encrypted backup bundles. It extends the existing five-workflow web workspace; OpenClaw remains optional and disabled in the local preview. Supplier transactions, payments and external messages remain manual.

## Implemented and tested

- Schema 805 adds travellers, roster proofs and attachment metadata without deleting existing business records. ID/revision/status-only private mutation responses, HMAC retry fingerprints, encrypted payloads/names/blobs, explicit audited reveal/download and closed-case guards.
- Exact-route binary upload limits and MIME/extension/signature checks; per-case storage quotas, free-space reserve, immutable files published before database references, one write under concurrent same-UUID retries, archive history and safe tamper/missing-file errors. There is no antivirus/CDR service.
- Roster category counts must match the case. Verification binds current trip constraints and every traveller revision. Traveller/trip/file changes invalidate document/pretrip proof. Exports exclude private traveller records and original blobs. Legacy cases may remain without a roster; previously prepared summaries may need regeneration after migration.
- Taipei deadline buckets grouped by owner; evidence-bearing “seen” acknowledgement distinct from completion. Any task patch clears it. Handover validates all selected revisions before atomically updating any owner, retains history and does not send notifications. Change/refund/incident templates use manual work-item records.
- Encrypted consistent SQLite/file bundles, verified inventory, interprocess locking, key-ID protection, retention, separately observed success/failure/maintenance status, and new-target-only offline restore. Private plaintext staging stays on the database volume outside the backup root. Forced-SIGKILL recovery and owned stale-work cleanup are tested. A scheduled per-user local job runs every six hours; its first schema-805 backup succeeded.
- Updated English architecture, Traditional Chinese guide, coverage matrix and recovery runbook. All 17 guide anchors remain stable. Application version stays out of visible UI.

## Reproducible evidence

| Check | Result |
|---|---|
| Python 3.12 full suite | 213 passed |
| Python 3.11 full suite | 213 passed |
| Clean production image's Python suite | 213 passed; one test-client deprecation warning |
| Existing browser regression | Chromium / Firefox / WebKit: 62 each |
| New private-workflow browser regression | Chromium / Firefox / WebKit: 44 each |
| Synthetic HTTPS signed-auth browser regression | Chromium / Firefox / WebKit: 24 each |
| Deliberate regression controls | Origin bypass and empty key cache both make the expected assertion fail |
| Hardened-container recovery drill | 20 passed |
| Application source comparison | All 61 application files match the tested image |
| Guide generation | Source/template matches generated HTML; 17 stable anchors |
| Existing local data | All rows in 15 original business tables unchanged, including 42 cases; private pre-upgrade snapshot retained |
| Actual local bundle recovery | Isolated HTTP instance serves all 42 original cases and accepts a synthetic recovery write |
| Local schedule | Per-user launchd loaded, 21600-second interval, first run exit 0; admin observes success |

The browser scenarios use synthetic data: roster create/reveal/hide/focus/verification, lost upload response recovered by UUID without retransmission, same-tab reload receipt reconciliation, cancelled private discard, two-tab traveller revision conflicts, stale roster proofs, authenticated download, invalid-signature error focus, archive history, authentication-expiry clearing, 390/768/1360 layouts with extra-large text and 44px controls, acknowledgement, stale batch handover preserving entered fields/selections with no partial transfer, successful handover, grouped tasks, closed read-only workspace and admin backup status. A separate synthetic adopted-booking fixture exercises UI roster and document verification, prepared summaries, roster edits during an open delivery form, stale export/delivery rejection, blocked drafts, re-verification and delivery of a new version with private-free customer export. Screenshots were inspected; phone actions now wrap into readable full rows instead of narrow three-button columns.

The additional HTTPS runner uses ephemeral RSA signing and TLS keys, real application JWT verification and separate operator/admin browser contexts. Browser-injected headers simulate Cloudflare's forwarded JWT. Tests cover forbidden unsigned/forged/unlisted identities, role restrictions, audited private reads, browser-generated cross-site POST Origin rejection, real expired-token 401, synthetic edge HTTP 302, login recovery, and an expired binary upload resumed with the same UUID and exactly one stored original. Its test-only server freezes key-cache time, uses a dead external proxy, and never changes production authentication code. WebKit cannot synthesize a 302 with `route.fulfill`; a small test-only ASGI edge wrapper emits actual HTTP redirects instead. No real Access edge, identity provider, cookies, MFA or Tunnel was exercised.

Deliberate regression controls ran against disposable application copies: disabling the Origin guard makes the browser's 403 assertion fail; removing cached keys causes fast failure through the dead proxy. All owned temporary app copies, servers, databases and keys are removed. The live 42-case database is never used by these runners.

The container was built from the repository Dockerfile with `--pull --no-cache`, rather than copying over an earlier application image. A stuck Docker Desktop credential helper was stopped **only for this task's build**; an isolated empty Docker client configuration with the same local daemon allowed anonymous retrieval of the public Python base. No global Docker settings were changed. The resulting image uses non-root, read-only root, tmpfs, dropped capabilities and no-new-privileges during verification. The drill tests 100 concurrent synthetic HTTP writes across eight workers, restart persistence, database-only compatibility recovery, and full encrypted bundle recovery including real authenticated HTTP reveal/download in another volume. Owned temporary containers/volumes were removed.

The production image resolves newer dependencies than the pinned local development environment. Its full suite passed; the sole warning concerns Starlette's test client's future HTTP client migration, not a failed production request. `constraints-tested.txt` continues to describe the tested local environment, not a Docker dependency lock.

Commands (run pytest suites sequentially: their fixture uses one fixed temporary DB):

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/python scripts/verify_mom_workspace.py --browser chromium
.venv/bin/python scripts/verify_travel_files.py --browser chromium
.venv/bin/python scripts/verify_access_browser.py --browser chromium
.venv/bin/python scripts/verify_access_regressions.py
# Requires Playwright and its installed Chromium/Firefox/WebKit engines.
# Repeat browser runners with --browser firefox and --browser webkit.
.venv/bin/python scripts/build_user_guide.py --check
.venv/bin/python scripts/audit_skills.py
docker build --pull --no-cache -t travel-mom-verify:local .
.venv/bin/python scripts/verify_container.py --image travel-mom-verify:local
```

## External review

Backend was **High** because it changes security, schema/API, file lifecycle/concurrency and multiple modules. Claude performed design and implementation review in read-only mode. Final verdict: **APPROVE**. Major findings fixed: blocking upload work moved to a thread pool, crash leftovers cannot put plaintext in the backup root, and audit calls no longer stamp schema versions. Follow-ups fixed include archived-record guards, derived fingerprint keys, shared roster logic, parent-directory fsync, explicit dotenv dependency, and database-volume capacity checks. Historical key custody/rotation, memory bounds and cleanup after changing backup roots are documented. Accepted minor limits: whole-message encryption, no-op handover acceptance and source-checkout/Docker placement of the backup status module.

Frontend design used Cursor Agent with the installed high-reasoning GPT model, as required. Its **REVISE** design points informed the implementation: explicit reveal privacy, roster-level proofs, file state/retry reconciliation, atomic handover failure behavior, closed-case reads and observed backup status. **Implementation review was requested three times; all failed with repeated connection stalls and returned no review.** The three-attempt cap was respected. Frontend has local three-engine verification and visual inspection, but no final independent implementation verdict. No frontend review was sent to Claude.

The expanded Python security E2E harness received a separate High design/change checkpoint with Claude; final verdict: **APPROVE**. Its minor feedback added source hashes/timestamps, explicit Origin-error verification, a surviving window marker for no-reload recovery, and a reproducible regression-control script. Existing compact test-runner style and the single-document/exact-version fixture assumptions remain accepted low-severity limits. The regression-control runner itself is not included in the browser source manifest, and no deliberately slow (>300-second) cache-expiry browser run was performed; the fixed synthetic cache clock is explicit in the harness. Frontend implementation review remains unavailable as described above.

Claude's usage gate returned `unknown` because its cached usage snapshot was stale; the provided instructions permit review in that state, and the user was informed. No usage percentages could be determined.

## Acceptance still requiring a real environment

- Cloudflare Tunnel/Access account policy, real IdP/MFA, cookie expiry/logout, external origin protection and off-network access must be verified on the actual deployment. No public tunnel, identity account or InsForge deployment was created.
- Mom's real-case usability, physical iPhone/Safari/Android behavior, VoiceOver/NVDA and production workload acceptance remain unverified. Browser automation does not establish WCAG or assistive-technology certification.
- Local scheduled backups do not protect against host loss. Off-site storage, historical-key custody, retention/deletion policy, external failure alerts and multi-host recovery require operational configuration. No LINE/email reminder or alert was sent.
- Full group/multi-segment packages, special-service/ticket-number bindings, CRM/per-customer permissions, automatic fee/legal/visa decisions, durable search workers and in-flight remote cancellation are outside this increment. Admin stopped-worker abandonment remains API-driven.
- Travellers/originals/bundles are encrypted; legacy case/booking/task/evidence text remains plaintext in the live DB. Do not put passport or payment credentials into those fields.

Before public launch, run the checklist in `CLOUDFLARE_ACCESS_DEPLOYMENT.md`. Before Mom uses real passports, retain the encryption key separately and confirm a recovery drill on the chosen deployment. This is an implementation and local-verification report, not a claim that every travel-agency task is automated.
