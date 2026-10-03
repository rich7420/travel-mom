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
