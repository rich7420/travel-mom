# Mom Mode design QA

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
