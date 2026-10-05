# Manual service-order verification

Date: 2026-10-05. Scope: dedicated change, cancellation, refund and in-trip incident work orders in the existing Mom web interface, schema 806. Supplier operations, actual transfers, emergency calls and customer notifications remain human actions.

## Implemented behavior

- Request, original booking targets, owner/due/urgency/contact; virtual deadlines route to the order, including future open orders as the case's next action.
- Supplier reply, applicable contract/policy source and expiry, proposal, per-currency four-direction cash totals and whole-case final customer due. Informational fee breakdown is already included, never summed again.
- Revision-bound customer decision and execution evidence, immutable confirmed/refused supplier result, append-only communications/corrections and checked booking-result rebinding.
- Installment settlement uses the existing ledger, global refund caps and per-order remaining caps. Same UUID/actor/content replays exactly once. Voiding linked cash increments order revision and invalidates financial resolution.
- Resolution checks consent, execution, supplier result, exact cash and current booking/document/pack evidence. Previously delivered changed trips require a current replacement delivery. Immediate incident help needs no quote or payment approval; monetary incidents can use quote-free service accounting.
- Full cancellation supports retained fees and explicit cancellation closure; partial cancellation keeps remaining travel through an amended adopted quote. Only the latest resolved money assessment must match today's adopted quote. Historical settled orders remain settled after later changes or business withdrawal. Closed cases produce no service deadlines.
- Single sheet, one promoted next step, secondary actions in native disclosure, full consent summary, separate read/error/retry states and named-input preservation on conflict. Consequential retries lock on changed assessment/booking bindings. Uncertain writes freeze inputs, retain an immutable in-memory request, and reconcile a metadata-only receipt before retry or reload. Authentication expiry clears contact drafts/displays.
- Seventeen guide anchors remain stable; dedicated instructions are under the deadlines chapter. English architecture and workflow-coverage documents include the new flow. Applicable official sources were checked on 2026-10-05; no common legal percentage or eligibility engine was introduced.

## Reproducible checks

```sh
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/python scripts/build_user_guide.py --check
.venv/bin/python scripts/verify_service_orders.py --browser chromium
.venv/bin/python scripts/verify_service_orders.py --browser firefox
.venv/bin/python scripts/verify_service_orders.py --browser webkit
.venv/bin/python scripts/verify_container.py --image travel-mom-verify:service-orders-20261005
```

Python 3.12 and 3.11: **226 passed** each. Twelve service tests exercise multi-action scenarios: retained-fee cancellation/split refunds/closure, quote-free incident help and cash, caps/idempotent concurrent ledger writes/corrections, stale/expired approvals and cross-case references, refusal/corrective consent, delivered-pack replacement and real 805 migration, future cancellation routing and prior void evidence, append-only change rebinding, partial cancellation and quote supersession, unfinished-sales incident guard, full refund/withdraw/reopen, and two sequential changes without fictional historical re-approval. Exact signed-JWT routes, methods, suffixes, Origin, actor and receipt boundaries also run through incident resolution/closure.

Browser matrix: **36 new order checks + 62 workspace + 44 private-file + 24 signed-auth = 166 checks per Chromium/Firefox/WebKit**, on isolated synthetic databases. Order checks include all four workflows and refusal, partial/capped/multiple-currency cash, lost-response and reload reconciliation, planning and consequential conflicts, HTTP 401 continuation/contact cleanup, double submit, direct deadline entry, error fallback/retry, row focus, 1360px/768px/390px extra-large layout, 44px controls and no page errors. Source hashes tie final service/private/auth reports to the app and those runners; the existing workspace runner remains unchanged. Screenshots were visually inspected. This is browser verification, not physical-device or assistive-technology certification.

Hardened container: **24 checks**, including 100 HTTP writes across eight workers, restart persistence, nonroot/read-only/cap-drop execution, encrypted original/passport roundtrip, schema-806 service order/history backup/restore, lifecycle immutability and new post-restore work. These do not execute real supplier transactions or a public tunnel.

Evidence stays ignored under `data/service-order-review/`: `full-tests.log`, `python311-tests.log`, final per-engine reports/screenshots under `regression/`, `container.json`, reviewer JSON, and before/after live database checks. No test mutates the real desk; browser servers/DBs and labelled containers/volumes are disposable. A pre-upgrade validated schema-805 snapshot and encrypted bundle protect the 42-case desk before the additive migration.

An earlier WebKit private-file run failed its page-error assertion without retaining the exception text. The runner now prints exceptions on failure; final runs retain the assertion and pass. The earlier intermittent failure was not reproduced and remains a browser-stability monitoring item rather than a suppressed check.

## Review checkpoints

Backend: High because of schema/API, authorization, state/money, concurrency and multiple modules. Claude Code reviewed design and two implementation rounds in read-only mode; the usage gate reported unknown/stale snapshots (46–47 hours). Final verdict was **REVISE**, conditional on correcting historical money-order quote binding and adding two regressions. Those fixes and the full-refund/reopen plus sequential-change tests are included and pass; no fourth round was requested under the three-round review limit. All concrete blocker/major findings were addressed. The remaining low-priority historical-cancellation reopen concern was also narrowed to the current/last-closed adopted quote.

Frontend: Cursor Agent, installed GPT high-reasoning model selected from the live model list, at design and implementation checkpoints. The last completed verdict was **REVISE**. Its blocker/major and medium findings were fixed and verified by the full unchanged-source browser matrix. The final third-round attempt failed with Cursor `ActionRequiredError` (monthly usage limit, reset stated as 2026-10-09), so no final APPROVE is claimed. No paid-limit/model change or fourth review round was made. Assessment revisions remain internal because the user requires versions to stay off visible UI; API revision guards and complete consent content remain enforced.

Live desk validation: additive 805 → 806 migration and restart on loopback 8001, **42 cases**, no service orders seeded into real data. Every pre-existing table except migration metadata matched its pre-upgrade row/hash inventory exactly. Both pre- and post-upgrade encrypted backups succeeded; the existing six-hour local schedule continues using the schema-compatible runner. The public hostname/IdP, real supplier actions and actual customer usability remain deployment/business acceptance tasks.
