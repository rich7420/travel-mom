# Mom Mode design QA

## Workspace refinement · 2026-10-17

Source: [current brief](context.md#workspace-polish--2026-10-17). Preview: local Mom Mode `/` on port 8001. Scope: homepage, case overview, shared work sheets and presentation styling. The original verification entries below are historical results.

The homepage now places deadlines before a two-column workspace: priority cases on the left, common work and recent/history on the right. The mobile DOM keeps this reading order. The decorative route graphic is removed; the primary action is beside the compact hero text. At 1360px with large text, the hero is about **211px** tall (baseline about 304px), and the first priority card starts near **y=575**, fully inside the 900px viewport. Normal/extra-large measurements are also saved. Secondary case actions have less visual weight than the first recommendation.

The case overview uses labeled date, traveller and budget facts, full-width notes with preserved line breaks, and icon/text entries for the same five work modules. Desktop uses a centered, bounded scrollable dialog; phones retain the bottom sheet. A stress screenshot caught an oversized sticky title despite the original layout probes passing. The heading is now bounded to three lines, with the full escaped title available in a native disclosure. The added height and expand/collapse assertions catch this regression.

| Requirement | Current evidence | Result |
| --- | --- | --- |
| Actual work visible early | Compact hero, first full priority card in 1360×900 for all three font settings; before/after screenshots inspected | Pass |
| Urgent deadlines remain complete | Seven overdue/today records displayed without a four-item limit | Pass |
| Responsive reading order | 360/390/768/1024/1360px, normal/large/extra-large; visual order follows the DOM | Pass |
| Facts and original actions | Exact family counts, multiline notes, existing record counts and all five work entries retained | Pass |
| Work-sheet controls | All five SVG entries open their original modules; Back restores focus; Escape closes; Close remains inside scrolled sheet | Pass |
| Long names and notes | Unbroken destination, long customer name, literal HTML in notes, bounded sticky heading and expandable complete title | Pass |
| Degraded refresh | Existing cases remain visible with retry after a simulated 503; retry recovers | Pass |
| Layout and controls | No horizontal clipping in checked surfaces; visible buttons/help/summary targets at least 44×44px | Pass |
| Data and safety | Disposable data and keys; outbound integrations disabled; existing 8001 still serves Mom/admin/Guide and retains 42 cases, zero test service orders/customers/jobs | Pass |

Chromium, Firefox and WebKit each passed the original **238** checks plus **137** focused layout checks: **714 existing + 411 new** across the three engines. The installed headed Brave, with an isolated profile and verified native PID/command, passed another **137** checks; its owned main PID was closed. Reports with source manifests match the current application. No JavaScript errors were recorded. Three isolated negative controls fail at the intended assertions: the original homepage loses the first-card viewport guarantee, removing the title bound fails the long-header guarantee, and restoring first-child emphasis fails the refresh-error emphasis guarantee.

Python full suite passes **317**. The first full run exposed an existing date-dependent test-isolation failure: other tests' fixed departure dates tied the deliberately old urgent case and correctly competed for the four priority slots. The same test passed alone. It now uses a private temporary database via the existing settings/initialization pattern; its original ordering assertion is unchanged, and the complete suite passes. The production ranking code is unchanged. Guide generation, JavaScript syntax, new runner lint and whitespace checks pass.

Evidence: ignored `data/ui-refinement-20261017/`, including `before/`, each engine's `verified-*/layout/`, `brave-final/`, source manifests, geometry measurements, failed/full Python logs, independent reviewer outputs and the three verified negative controls. The repeatable layout runner is [verify_workspace_layout.py](../scripts/verify_workspace_layout.py). Physical phones, manual screen-reader conformance, Mom's usability acceptance, and a new public Tunnel/identity run were not performed in this UI increment.

Cursor's first completed implementation review returned **REVISE**. The clamp now sits on an inner span while the focused heading retains its explicit focus ring; the first priority retains emphasis after a prepended error notice; the desktop sticky-header offset removes the observed 4px content strip; unused flex styling and the desktop shadow were corrected. Added keyboard-focus, scroll-coverage and error-emphasis assertions pass across the checked engines. Final frontend implementation review: **three independent Cursor `auto` reviews all APPROVE** (design/simplicity; correctness/privacy/compatibility; tests/failure cases/evidence), against the same frozen diff. The installed GPT high-reasoning models were rejected by Cursor's monthly usage limit, so the three-session auto fallback followed the user's review rule. Design-check attempts returned progress text without a formal verdict; one design follow-up and two initial implementation reviews timed out. Those attempts are preserved rather than counted as approvals. The correctness reviewer approved after its fixes; fresh independent simplicity/evidence sessions approved the same final change. No reviewer finding is intentionally left unfixed. The evidence reviewer explicitly limited its browser-evidence verdict to Chromium; Codex separately verified all final Firefox/WebKit/Brave results and source manifests. Verdict: **READY for local UI review**, with the physical-device, assistive-technology and Mom acceptance limits above.

---

Date: 2026-10-03. Context: [design brief](context.md). Scope: existing local Mom UI and web authentication behavior; no public deployment.

The revised interface follows the travel-workspace direction: warm paper, deep navy, restrained terracotta, a composed hero, consistent decorative SVG line icons, numbered priority cases and compact secondary history. Desktop side navigation transforms into mobile bottom navigation. The general workflow rail is explicitly labeled and does not imply booking completion.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Clear designed desktop hierarchy | Visually inspected 1360px screenshot; four shortcuts and two workspace columns | Pass |
| Intermediate widths | 1024px extra-large text; two shortcut columns and stacked workspace | Pass |
| Tablet and mobile | 768px extra-large and 390px large/extra-large; no horizontal overflow | Pass |
| Readable controls | Existing 18/20px font preference; visible buttons at least 44px in mobile checks | Pass |
| Versions hidden | Mom/admin visible text checked; HTML version comments retained; recipe versions omitted | Pass |
| Navigation and semantics | aria-current, focused view heading, priority list labels, decorative SVG aria-hidden/focusable=false | Pass by code inspection |
| State handling | Empty new-customer action, error notice/retry, history expand/collapse | Pass |
| Access login | Safe account/role display; both stored legacy credentials cleared; 401 and opaque redirect login dialog | Pass with simulated Access responses |
| Session expiry preservation | Populated lists, unsent customer text and admin form retained; login dialog survives Escape; only explicit button reloads | Pass |
| Existing workflow | Three consecutive customers, child/infant prefills, manual flight/hotel offers, selection, draft edit/copy, reload | Pass |

The latest browser report contains **16 checks**, all passing, and no page errors. Both JavaScript syntax checks and git diff whitespace checks passed. The independent backend suite passed 130 tests on Python 3.12 and 3.11.14.

Local evidence is intentionally ignored by Git: `data/ui-auth/report.json`, `data/ui-auth/verify_ui.py`, desktop/mobile/intermediate screenshots under `data/ui-auth/`, and `data/web-workflow-browser-report.json`. Viewport previews: `after-desktop-viewport.png` and `after-mobile-large-viewport.png`. Full-page screenshots retain fixed navigation at the browser viewport position.

Review: Cursor Agent, GPT high reasoning selected from the installed model list, read-only design and implementation checkpoints. Final verdict: **APPROVE**, after three rounds. The previous implementation findings (reauthentication handling, persistent login dialog, accessible names and status colors) have been corrected and checked.

No blocking visual requirement remains open. One cosmetic minor is intentionally left: offline status uses gray text and a terracotta dot; the explicit 「離線」 label remains readable and does not rely on color. Matching text/dot warning colors can be considered later. This is not a complete screen-reader/WCAG certification; manual assistive-technology and Mom usability checks remain useful follow-up. Access responses were simulated in UI checks; actual Cloudflare policies, IdP/MFA and public tunnel behavior require the deployment runbook.


## In-web guide QA (2026-10-03)

Context: the in-web guide increment in [context](context.md). Result: requirements pass; Cursor Agent final verdict **APPROVE**, after read-only design and implementation checkpoints. High frontend complexity (new guide, CSS/JS and generation pipeline) used the installed GPT high-reasoning model, following the frontend review rule. Both optional P3 documentation findings were fixed: date-neutral constraints header and explicit successful-query condition for official options. No remaining blocker, major or minor finding for this increment.

- Guide matches the paper/navy workspace, with a contents sidebar on desktop and native collapsible contents on mobile. Screens at 1360px and 390px extra-large were visually inspected.
- Eleven chapter anchors resolve. Stable task fragments link from the shared sheet header, and settings/topbar links remain available. Reading help opens another tab with noopener; the original sheet and unsent input stay intact.
- Eleven Chrome guide checks pass: context help/data preservation, chapter navigation/limits/version hiding, 1024/768/390px extra-large controls/no overflow, font persistence, Mom 390px large/extra-large help layout, settings help, print content, and no-JavaScript reading. No page errors.
- Existing 16 UI checks pass again, including expired-login preservation. Full intake/manual-offer/selection/draft workflow passes again. All 136 pytest tests pass on Python 3.12 and 3.11.14.
- Generation drift is checked without writing. Guide assets use strict CSP; unauthenticated Access requests fail while allowed operators can read them. Token/local mode serves the instructional static assets publicly to reachable clients, consistent with the existing shell.
- Print hides navigation and controls, prints all chapters, and produced a local A4 PDF. No JavaScript is required to read or use chapter links. Guide font controls use a local preference only.

Evidence: ignored `data/guide-review/browser-report.json`, `verify_guide.py`, desktop/mobile screenshots, and `guide-print.pdf`. Existing workflow reports remain under `data/`. Manual screen-reader conformance, actual public Access deployment and Mom usability remain follow-up; no claim that most agency operations are complete.

## Agency operations QA (2026-10-03)

The latest increment retains the paper/navy/terracotta design and adds compact case tiles, a single next action, all-case deadlines and one reusable form shell. Desktop/tablet/mobile screenshots at 1360/768/390px extra-large text show no horizontal overflow and visible buttons at least 44px. The 390px ledger was visually checked; responsive amount rows separate labels and values. Six 14px navigation labels fit the mobile bar.

Twenty browser checks pass for the manual lifecycle, missing/stale output guards, authenticated public document copy/print, exact decimal balances, origin-preserving task back navigation, expired-login resume, same-intent retry after a committed lost response, success/refresh-failure duplicate prevention, stale async and poll ownership, isolated task errors and dirty-Escape preservation. Sixteen existing UI checks, eleven guide checks and nine legacy workflow checks also pass. The guide now has sixteen chapters; contextual links open a separate tab and preserve unsaved input.

Both external read-only reviewers approved: Cursor for all frontend work; Claude for High backend/schema/security/concurrency work. All material findings fixed. Minor primary-action/history-label suggestions fixed. Backend suites pass 162 tests on Python 3.12 and 3.11.14, sequentially because their fixture shares a fixed temporary DB. See [full verification](../docs/AGENCY_OPERATIONS_VERIFICATION.md) for evidence and accepted minor constraints. No live transactions, public Access deployment, manual screen-reader certification or Mom usability claim is made.

## Reliability and compact workspace QA (2026-10-03)

This increment uses the existing [context](context.md): warm paper/navy/terracotta, Mom's large text preference, manual agency work and the same webpage regardless of optional OpenClaw. The hero is shorter, work deadlines precede shortcuts, and a native collapsible section contains secondary search/selection/edit work. The case's primary recommendation and five agency modules remain visible. The general rail now covers intake/pricing, quotes, booking/payment and handoff, while retaining the accessible label that it is a general workflow rather than case progress.

Screens at 1360px desktop Home and 390/768px extra-large case views were visually inspected. No text/control collision was observed. The repeatable browser runner is [verify_mom_workspace.py](../scripts/verify_mom_workspace.py), using an ephemeral loopback server and disposable database. Synthetic screenshot/results evidence stays ignored under `data/hardening-review/browser/`.

Verified behavior includes explicit discard versus retained DOM on Cancel for close/Escape/back/replacement; pending saves lock editing/navigation; committed saves navigate without repeat writes; clean/dirty/failed case switches preserve the correct association; generation checks discard old responses; manual-entry missing-case focus; component retry/degraded preferences/catalogues; dedicated auth expiry; and template title/kind with a blank required deadline. Newly generated and edited replies use the same departure protection and are not persisted to browser storage. Test scripts evaluate function expressions under the real CSP; unsafe-eval is not enabled for testing.

Target checks cover 390/768/1360px extra-large content without horizontal overflow and at least 44px details-summary targets. Keyboard summary behavior, urgent-record focus and direct missing-date editing are checked. New SVGs are not introduced; decorative existing icons retain aria-hidden. Colors inherit established tokens, and state labels convey stale/recheck status in text. JavaScript syntax, generated-guide drift and whitespace checks pass. Manual screen-reader testing and Mom's actual workload usability remain unverified; no WCAG certification is claimed.

Independent Cursor implementation review initially found editable controls during save, pending-transition duplicate prompts, failed-switch association risk and invisible async action errors. These were fixed and covered by browser regressions. Final verdict is recorded in the hardening verification report after the final checkpoint.


Final hardening result: **41 browser checks passed**, no JavaScript errors. Keyboard expansion/collapse and urgent-record focus were verified in the modal, with selectors scoped to the sheet so underlying Home controls cannot receive inert focus. A real successful case PATCH followed by a simulated failed view refresh leaves a read-only form; retry navigation issues no second PATCH. Backend Python 3.12/3.11 each pass 171 tests. Docker context was built/exported in a disposable scratch image and inspected, then removed.

Review outcome: Claude backend **APPROVE**. Cursor's third frontend checkpoint returned **REVISE** for the committed-form refresh edge and two documentation/test details; all were corrected and the 41-check browser run passed. The three-round review cap was respected; these final narrow corrections have regression evidence but no fourth independent review. No reviewer finding is intentionally left unfixed in the frontend. Backend's optional blank/null normalization and disconnected-upload log noise remain documented conservative limits.

### Lifecycle and recovery · 2026-10-03

The guide now has **17 chapters**, including the stable lifecycle anchor. The reusable disposable browser runner accepts Chromium/Firefox/WebKit. Each engine passed **62 checks** including prior saved-refresh/dirty/generation/auth/degraded-loader regressions, lifecycle blockers, cancelled dirty close, committed-but-lost response with one UUID/event, closed history-only modules, keyboard reopen, stale-state rejection and extra-large-font no-overflow at 390/768/1360. Inspected Chromium 390px and WebKit 1360px lifecycle screenshots: content and controls remain legible without horizontal clipping. Keyboard reopen is exercised in the modal. Existing 44px control styles are retained. No physical-phone, Safari app, VoiceOver/NVDA or WCAG certification is claimed.

Backend and frontend external reviews and final counts are recorded in `docs/LIFECYCLE_RECOVERY_VERIFICATION.md`. All cases are synthetic; no customer messages or supplier transactions were sent. Restore readiness is established by the disposable container drill, not inferred from `/livez` or configuration readiness.

Final lifecycle result: Claude backend and Cursor frontend **APPROVE** at round three. Final suites pass **193 tests each** on Python 3.12/3.11, browser engines **62 checks each**, and Docker **14 checks**. Final minor UI corrections and the stopped-task recovery edge were regression-tested within the review cap. Generated draft focus, stale selected-option read-only redraw and explicit adopted-quote withdrawal are covered. See the tracked verification doc for remaining backend operational limits and image build provenance. Local preview upgraded with a validated backup; original 42 cases/business records are unchanged.


### Private roster, files and handover · 2026-10-05

The existing five-tile shell remains. A compact pretrip entry opens stacked native disclosures for basic travellers and originals. Summary rows carry ordinal/category only; full fields require explicit reveal/edit and are removed on close or authentication expiry. Phone action rows now wrap at a 160px basis, keeping long Traditional Chinese labels legible. No new navigation or nested dialog was added.

Each engine passed the existing 62 checks and 44 private-workflow checks, plus 24 synthetic HTTPS signed-auth checks, including two-tab edit conflicts, stale roster/delivery rejection, replacement-pack delivery, same-tab reload recovery and saved-upload reconciliation with no retransmission, masked summary/reveal/hide/focus, roster proof, file signature/error focus, archive/download, stale atomic handover preserving selections and evidence, grouped owner deadlines, acknowledgement and closed-case reads. Screenshots at 390/768/1360 with extra-large text were inspected; no horizontal overflow or undersized action controls were detected. Native file inputs are available; no drag-only interaction. Physical devices and manual assistive technology remain unverified.

Claude's High backend review ended APPROVE. Cursor's frontend design REVISE points were implemented; all three implementation-review attempts failed with connection stalls, so no final frontend verdict is claimed. The verification document records this review gap and accepted operating limits: [current report](../docs/PRIVATE_WORKFLOW_VERIFICATION.md).


## Dedicated service-order QA (2026-10-05)

The existing single sheet/tasks entry now provides four manual service workflows, one promoted next action, secondary native disclosure, full consent terms and per-currency money, read/retry/closed states, conflict preservation/explicit review, receipt-first uncertainty recovery with locked drafts, and contact-only auth-expiry cleanup. Screens at 1360px, 768px and 390px extra-large were visually inspected; no overflow and visible buttons at least 44px. Seventeen help fragments remain stable. The updated guide links from the same sheet.

Unchanged-source final browser matrix passes **166 checks per Chromium/Firefox/WebKit**, including **36 new service checks**. The new committed runner covers full cancellation with fees, partial refunds, quote-free assistance/accounting, changed-booking proof, supplier refusal/corrective approval, dual currencies, receipt/reload, planning and consequential 409, HTTP 401 continuation, double submit, deadline entry, row focus and read failure/fallback. Existing 62 workspace, 44 private-file and 24 signed-auth checks continue passing. No physical-device or assistive-technology certification is claimed.

Frontend review: Cursor Agent with installed GPT high-reasoning model, read-only design/change checkpoints. Round 2 verdict **REVISE** findings were corrected. The final round failed with the account's monthly usage limit; no final APPROVE is claimed. Backend Claude's final targeted financial-history finding was fixed with two regressions under the three-round limit. See [service-order verification](../docs/SERVICE_ORDER_VERIFICATION.md) for evidence and remaining review/browser-stability limits.
