# Manual agency lifecycle verification

Date: 2026-10-03. Scope: the shared FastAPI/SQLite application and Mom web interface. All test customers, prices, booking references and payments are synthetic. The existing port-8001 preview uses a backed-up local database; no production tunnel, supplier transaction, payment or customer message was executed.

## Implemented behavior

- Immutable quote content with monotonic versions, per-currency fees/discounts, optional private cost/margin and explicit sent/accept/reject evidence. Amendments preserve case-level payments, require reason and replace other active quote versions.
- Complete cross-case deadline lists with owners, sources, links, optimistic revision and change reasons. Today includes every overdue/today open task; completed tasks are not flagged overdue. Business display timezone is Asia/Taipei.
- Human-verified supplier confirmation records drive case booking status. Reverification can carry an existing confirmation to an amended quote without falsely voiding it. Mistyped records can be voided; normalized duplicate references in other cases raise warnings.
- Exact Decimal manual receipts/payments/refunds with currency balances and refund limits. Unknown margin or unmatched quote currency stays unknown. Local record correction is distinct from actual supplier cancellation or bank movement.
- Required document checklists, evidence and customer text/HTTPS links; binding/requirement repairs retain reasons and history. Product-specific e-ticket/hotel-voucher requirements gate complete pretrip summaries.
- Immutable pretrip source snapshots and actual handoff evidence. Incomplete/stale versions cannot be exported or marked delivered. Public HTML/PDF printing and copy share whitelisted escaped customer fields, excluding private evidence/cost/window information.
- Five compact case work entries, context-preserving task back navigation, six navigation items, isolated load errors, async sheet ownership and authenticated customer-document popups.
- One UUID per form intent survives an uncertain network/401/5xx outcome. Successful writes are marked committed before refresh: a failed refresh permits reloading, never repeating the mutation. Reauthentication resumes Mom's original form without reload.
- Sixteen guide chapters generated from one Traditional Chinese source, including all new operations. English architecture and coverage/direction documents updated.

## Verification

| Check | Result |
| --- | --- |
| Python 3.12 regression suite | **162 passed** |
| Python 3.11.14 regression suite | **162 passed**, run sequentially after 3.12 |
| Business browser scenario | **20 checks passed**, no page errors |
| Existing UI/auth regression | **16 checks passed**, no page errors |
| In-web guide regression | **11 checks passed**, no page errors |
| Existing three-customer/manual-offer/draft scenario | **9 checks passed**, no page errors |
| Required-token print on separate disposable server | Pass: authenticated popup/assets/copy, opener detached, no secret in document URL/DOM; unsigned direct export rejected |
| JavaScript syntax and guide generation drift | Pass |
| Diff whitespace | Pass |

Backend coverage includes 802 → 803 upgrade twice preserving cases/options, concurrent version allocation, identical concurrent intent replay, normalized money, omitted/null patch semantics, command rollback/retry, quote source-change race, display-name correction, actual booking rebind/document repair through delivery, private export boundaries, missing/stale export/delivery refusal, refunds/voids/unmatched currencies and cross-case references. Real RSA-signed Access operator tests exercise the lifecycle and verify exact role/path/method/origin protection. Existing suites cover underlying supplier validation, guided intake, safe case edits and authentication.

Browser coverage includes versioned quote fee/discount totals, manual sent/client acceptance, overdue task completion, exact deposit balance, booking-derived case status, missing-document output refusal, complete summary delivery, delivered snapshot staleness, modal back/focus context, 1360/768/390px extra-large controls/no overflow, expired-login resume, committed-payment lost-response replay, old-response ownership, successful-write/failed-refresh duplicate prevention, isolated task/Home errors, polling ownership and dirty-Escape preservation.

The test fixture uses one fixed temporary SQLite path. Python version suites must run sequentially; concurrent suite processes delete or mutate each other's database. Initial simultaneous verification reproduced this fixture interference; isolated sequential reruns passed both complete suites. This is a test-runner constraint, separate from the tested same-process command concurrency.

Local ignored evidence: `data/operations-review/browser-results.json`, `verify_operations.py`, viewport screenshots, `verify_token_document.py`, reviewer JSON; earlier UI/guide/workflow evidence remains under `data/`. Screens at 1360px and 390px were visually inspected. Runtime `data/local-review.db`, logs and server PID remain local.

## Independent read-only review

Backend: **Claude Code**, because schema changes, concurrent transactional state, money and security/API boundaries meet the High criteria. Usage gate allowed every call. Design → implementation → final review: **APPROVE**. All material findings were fixed. Optional omitted-versus-null patch hashing and dead-warning cleanup were fixed after approval and regression tested. An unchanged stale document binding still requires booking reverification or explicit document binding correction before readiness updates; this deliberate safety order is described in the guide. Stale delivered summaries remain stored internally but cannot be re-exported to customers; a separate labelled audit export is future scope.

Frontend: **Cursor Agent**, using the installed GPT extra-high reasoning model as required for high frontend complexity. Design → implementation → final review: **APPROVE**. All blocker/major findings were fixed. Remaining minor primary-action stale/degraded-state suggestions and raw history labels were corrected and browser-tested. The CLI returned empty results on two attempts; same-session read-only retries recovered the written reviews, without changing reviewer/model or granting write access.

No unresolved blocker or major review finding remains. Dense template formatting can be refined later if it helps maintenance; no unrelated framework or broad refactor was introduced.

## Remaining operational scope

This is a manual internal travel desk, not GDS/ticketing, banking, automated messaging, attachment storage/merging, passport OCR, a complete itinerary/group/visa product suite or full CRM. It does not validate external document links. Public Cloudflare tunnel/IdP/MFA and actual Mom usability require the existing deployment runbook and real user testing. OpenClaw remains optional and Mom's interface remains this webpage.
