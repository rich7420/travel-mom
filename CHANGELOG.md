# Changelog

## v0.8.1 — 2026-08-26

### Mom Mode UX

- Replaced the default engineering dashboard with a mobile-first `旅行社小幫手` UI at `/`.
- Moved the previous Browser Lab / supplier-trust / readiness workbench to `/admin`.
- Added Today view, priority cases, recent cases, resumable search progress and Next Best Action.
- Added first-use preferences for default origin, preferred airlines and font size.
- Guided intake now supports resume, back, save, reset, progress, date validation and shorthand such as `2大1小`.
- Added plain-language intent routing for users who do not know what to ask.
- Added friendly flight/hotel forms and background-run start/progress endpoints.
- Added customer-reply feedback controls without automatically sending messages.

### Skill evolution foundation

- Added persistent redacted `skill_feedback` evidence with feedback type, edit ratio, case reference and exact Skill SHA-256 fingerprint.
- Added proposal-readiness summaries; v0.8.1 remains capture-only and never mutates live Skills.
- Added redacted JSONL export for offline optimizer/evaluation work.
- Added `mom-mode`, `guided-intake`, `skill-feedback-capture`, and `skill-evolution-proposal` workspace Skills (23 total).
- Locked payment, PII, OTP/3DS/CAPTCHA, domain trust, permissions and authoritative-source safety rules outside evolution.

### Security / platform

- Mom Mode uses a strict CSP with no inline script/style allowances. Legacy inline code is confined to `/admin` and `/admin-static/*`.
- Reused the same migration-managed core TripCase database instead of creating a separate UX database.
- Background search start gracefully stores/resumes work when OpenClaw is disabled.

### Tests

- 62 automated tests pass.
- Total measured coverage: 80%.
- 23 Skills, 8 airline recipes / 16 airline regression cases, hotel recipe / 4 hotel regression cases all pass audits.
- Flight and hotel deterministic end-to-end safety demos pass.

## v0.7.1-reviewed — 2026-08-25

### Fixed

- Close every SQLite connection deterministically; strict ResourceWarning tests now pass.
- Reject nested card number/CVV/CVC/security-code fields anywhere in PII payloads.
- Make BrowserAttempt numbering atomic under concurrent workers.
- Reclaim stale webhook events only after a bounded same-payload processing lease.
- Remove internal exception details from BrowserTask HTTP responses.
- Mask database paths outside development environments.
- Remove the v0.7 release ambiguity by recording the executed review results.

### Security

- Add operator API authentication; optional for local development and mandatory in production.
- Fail production startup when `TRAVEL_DESK_ADMIN_TOKEN` is missing.
- Add application request-size limits and baseline response security headers.
- Keep operator token in browser `sessionStorage` only for the legacy local UI.
- Add a schema migration ledger and tested dependency constraints.

### Tests

- 52 automated tests pass.
- Pytest passes with `ResourceWarning` promoted to an error.
- Added concurrency, recursive PII, webhook lease, operator authentication, security-header, request-limit, and production fail-closed tests.
- Flight/hotel offline E2E demos and all 19 skill / 8 airline / hotel recipe audits pass.

## v0.7.0 — 2026-08-25

### Added

- EVA Air (`BR`) and Tigerair Taiwan (`IT`) official-site airline definitions and semantic recipes; airline set is now 8.
- Hotel network registry for Marriott, Hilton, Hyatt, IHG, Accor and Shangri-La.
- Auditable/revocable `HotelSiteGrant` for independent official hotel domains.
- Persistent `HotelSearchRun`.
- `hotel-search-v1`, `hotel-revalidation-v1` and `hotel-booking-preflight-v1` typed contracts.
- Hotel result validation, deterministic room/rate comparison, exact revalidation and human change-acceptance gate.
- Mobile UI for official hotel search, room comparison, revalidation, preflight, search history and site-trust management.
- Supplier-aware Browser Lab grouping for airline and hotel attempts.
- Four hotel workspace skills, bringing local skill count to 19.
- Versioned hotel semantic recipe + audit script and four regression cases.
- `scripts/run_v07_demo.py` deterministic hotel end-to-end demo.
- API tests for hotel network search, default-deny, OTA attestation denial and site-grant revocation.

### Changed

- Default flight airline list is CI/BR/CX/JX/AE/IT/EK/NH.
- Hotel Browser tasks accept only built-in network domains or current human-approved independent grants.
- Browser Lab no longer collapses hotel tasks into an undifferentiated generic supplier.
- README/architecture/roadmap now treat hotels as a first-class typed workflow rather than demo ranking.

### Safety

- Expanded known OTA/search-domain denylist for hotel site attestation.
- Revoked hotel grants invalidate future trust.
- Room/rate revalidation requires exact product identity before preflight.
- Unknown fee data remains null/unknown; it is never guessed as zero.
- Payment/card/CVV/final booking/OTP/3DS/CAPTCHA bypass remain prohibited.

## v0.6.0 — 2026-08-25

### Added

- Persistent `FlightSearchRun` with tasks, manual handoffs, selected option and lifecycle status.
- Persistent `BrowserAttempt` ledger with attempt number, source, duration, blocker, validation errors, result hash and attempt-specific structured result status.
- `flight-revalidation-v1` typed contract and exact selected-itinerary revalidation.
- `booking-preflight-v1` freshness, exact-match, price/condition acceptance and human-checkout gate.
- Search-run, selection, revalidation, preflight and Browser Lab mobile UI.
- `/api/system/readiness` for offline POC, live Browser Lab and Mom LINE configuration readiness.
- LINE/Telegram persistent webhook idempotency and replay.
- Channel endpoints default-deny when disabled; enabled channels require non-empty user/chat allowlists.
- Telegram webhook verifies the configured `X-Telegram-Bot-Api-Secret-Token`; missing secret is treated as misconfiguration.
- Telegram callback acknowledgment and byte-safe callback fallback.
- Browser Lab v2 metrics separating contract validation, usable success, no-result and manual terminal outcomes.
- Three workspace skills: `search-run-coordinator`, `browser-lab-reviewer`, `site-change-proposal`.
- Six recipe metadata/version upgrades and 12 regression cases.
- `scripts/run_v06_demo.py` end-to-end offline workflow demo.
- Read-only `scripts/openclaw_host_preflight.sh` for config validation, doctor lint, security audit, Gateway status and Travel Desk readiness.

### Changed

- Separate `mom-travel` conversational agent from least-privilege `mom-travel-browser` agent.
- Disable browser page-context evaluate in the example OpenClaw config.
- Search and revalidation tasks use the dedicated browser model.
- Structured route validation now accepts contiguous connecting segment chains.
- Comparison explains TWD budget tradeoffs without hiding over-budget options.
- Official website task/result URLs now require HTTPS.
- SQLite uses WAL and `synchronous=NORMAL`.
- Docker Compose forces the writable database path to `/data/travel_desk.db` and retains loopback-only publication, read-only root filesystem, non-root user and dropped capabilities.

### Fixed

- Browser Lab no longer derives historical attempt success from a task's latest result.
- Docker `.env` can no longer override the container database onto the read-only application filesystem.
- Guided-flow cancel now clears persistent session state.
- Replayed LINE/Telegram webhook events no longer duplicate case creation or agent work.
- Browser/model-provided strings are escaped before insertion into inline UI handlers.

### Safety

- Payment, ticketing, cancellation, refund, card/CVV and OTP/3DS/CAPTCHA bypass remain prohibited.
- Unknown domains remain default-deny.
- Gateway operator token remains backend-only.
- Browser profile defaults to isolated `openclaw`.

## v0.5.0 — 2026-08-25

- Added CI/CX/JX/AE/EK/NH registry, semantic browser recipes, `flight-search-v1`, strict official-domain validation, deterministic comparison, skill/recipe audits and initial Browser Lab planning.
