# Mom Travel Desk — Executed Review & Test Report

**Date:** 2026-08-25  
**Reviewed artifacts:** claimed v0.8 UX package metadata/docs, full v0.7 source archive, and the repaired `v0.7.1-reviewed` build.

## Executive conclusion

The last complete source archive available for execution was **v0.7**. Its core travel workflows are healthy for an offline/local POC, but the originally packaged code had several security and reliability gaps.

The claimed **v0.8 UX release is not a valid runnable release in the available artifacts**:

- no v0.8 source archive or application source was present;
- only README/docs/build-report files were available;
- its own `BUILD_RESULT.txt` records `"passed": false`;
- its own pytest log records **3 failed, 9 passed** due to missing SQLite tables:
  - `ux_guided_sessions`
  - `ux_search_jobs`
  - `ux_confirmations`

Therefore, the previous claim that v0.8 was a tested downloadable build should not be relied on.

I repaired the last complete v0.7 source and produced **v0.7.1-reviewed**. This is the build tested in this report.

## Test matrix

| Check | Original v0.7 | v0.7.1-reviewed |
|---|---:|---:|
| Pytest | 45 passed | **52 passed** |
| Resource warnings as errors | failed in coverage run due to leaked SQLite connections | **passed** |
| Python compile | passed | **passed** |
| Frontend JavaScript syntax | passed | **passed** |
| Local OpenClaw skill audit | 19 passed | **19 passed** |
| Airline recipe audit | 8 recipes / 16 cases | **8 recipes / 16 cases** |
| Hotel recipe audit | 1 recipe / 4 cases | **1 recipe / 4 cases** |
| Flight offline E2E | passed | **passed** |
| Hotel offline E2E | passed | **passed** |
| Production auth smoke | not present | **passed** |
| Production missing-token guard | not present | **passed** |
| Line coverage | 23% | 23% |
| Telegram coverage | 29% | 29% |
| OpenClaw client coverage | 35% | 35% |
| Total application coverage | 74% | **75%** |

## What the offline E2E tests proved

### Flight workflow

The flight demo completed:

1. TripCase creation.
2. CI/JX/CX structured search results.
3. Typed validation and ranking.
4. Option selection.
5. Price revalidation.
6. Rejection before explicit price-change acceptance.
7. Successful booking preflight after explicit acceptance.
8. `payment_handled_by_agent = false`.

### Hotel workflow

The hotel demo completed:

1. TripCase creation.
2. Official-site hotel search result ingestion.
3. Total-stay cost comparison.
4. Room/rate selection.
5. Price revalidation.
6. Rejection before explicit price-change acceptance.
7. Successful hotel preflight after explicit acceptance.
8. `payment_handled_by_agent = false`.

These tests prove the deterministic local contracts and safety gates, **not** the reliability of real airline/hotel websites.

## Findings and disposition

| Severity | Finding | Status in v0.7.1-reviewed |
|---|---|---|
| Critical | v0.8 release had no runnable source/archive and its own build report failed | **Not repairable from available files; release blocked** |
| High | Customer/case and browser-control APIs had no operator authentication | **Fixed:** optional in dev, mandatory in production |
| High | SQLite connections were not actually closed by `with sqlite3.Connection` | **Fixed:** explicit closing context manager |
| High | Browser Lab ingest and trusted-hotel grant APIs were reachable by anyone who could reach the backend | **Fixed by operator API middleware in secured deployments** |
| High | Card/CVV rejection only inspected top-level keys | **Fixed:** recursive nested-list/dict inspection |
| Medium | Browser attempt `MAX+1` numbering could race across concurrent workers | **Fixed:** `BEGIN IMMEDIATE` atomic transaction; concurrency tested |
| Medium | Crashed webhook work could remain `processing` forever | **Fixed:** configurable bounded lease and safe same-payload reclaim |
| Medium | Browser failures returned internal exception type/details to clients | **Fixed:** generic client message; full exception stays server-side |
| Medium | No app-level request-size guard | **Fixed:** configurable Content-Length limit |
| Medium | Missing baseline security headers | **Fixed:** nosniff, frame deny, permissions policy, referrer policy, CSP |
| Medium | Production could start without API authentication | **Fixed:** startup fails closed |
| Medium | Health response exposed the database path | **Fixed in non-dev environments** |
| Medium | No schema-version record | **Partially fixed:** migration ledger added; real sequential migrations still needed |
| Medium | Dependencies were broad minimums only | **Partially fixed:** tested-version constraints file added |
| Medium | LINE, Telegram, OpenClaw integration test coverage is low | **Open** |
| Medium | v0.7 homepage exposes too many operator concepts for Mom | **Open; requires regenerated v0.8 UX source** |
| Medium | Inline `onclick` handlers require `unsafe-inline` in CSP | **Open; replace in regenerated UX** |
| Medium | Audit log has generic `human/system` actors rather than authenticated operator identity | **Open** |
| Medium | SQLite remains the single-node POC store; no backup/retention/RBAC/KMS | **Open** |
| High operational | No real CI/BR/JX/CX/AE/IT/EK/NH or hotel Browser Lab was possible in this environment | **Open; must run on the user's OpenClaw host** |

## Security behavior tested

A production subprocess was launched with an operator token:

- `GET /health` returned 200 and masked the DB path.
- `GET /api/airlines` without a token returned **401**.
- The same request with `X-Travel-Desk-Admin-Token` returned **200**.
- Security headers were present.
- Starting with `APP_ENV=production` and no token exited during startup with a non-zero status.

The legacy operator UI stores the token only in `sessionStorage`, not in project source or localStorage. This is acceptable for a local POC, but production should replace it with authenticated server-side sessions and named operator accounts.

## Remaining release blockers

Do not call this production-ready until all of the following are completed:

1. Regenerate v0.8 UX as actual source code and package it.
2. Use one migration-managed database; do not maintain a disconnected UX database.
3. Add authenticated Mom/operator roles and real audit identities.
4. Raise LINE/Telegram/OpenClaw adapter coverage and test webhook retries/timeouts.
5. Run real Browser Labs on the user's OpenClaw machine:
   - CI, BR, JX, CX first;
   - AE, IT, EK, NH second;
   - Hilton/Marriott/Hyatt plus two real independent hotels.
6. Add encrypted backups, retention/deletion controls, and production secrets management.
7. Replace inline event handlers so CSP can drop `unsafe-inline`.
8. Validate real LINE OA / Mini App behavior with Mom.
9. Add a durable job queue before parallel browser workers.
10. Complete legal/operational review before using customer passport or booking data.

## Test limitations

The environment did not contain:

- the user's OpenClaw Gateway/browser profile;
- logged-in airline or hotel sessions;
- a real LINE OA or Telegram webhook;
- a Docker daemon;
- live CI/BR/JX/CX/AE/IT/EK/NH booking pages under automation.

No live airfare, room availability, ticket issuance, payment, cancellation, refund, OTP, 3DS, or CAPTCHA was tested.

## Reproduction commands

```bash
pytest -q
pytest -q -W error::ResourceWarning
pytest --cov=app --cov-report=term-missing -q
python -m compileall -q app tests
node --check app/static/app.js
python scripts/audit_skills.py
python scripts/audit_airline_recipes.py
python scripts/audit_hotel_recipe.py
python scripts/run_v06_demo.py
python scripts/run_v07_demo.py
bash -n scripts/openclaw_host_preflight.sh
```

## Release recommendation

- **Reject the incomplete v0.8 artifact.**
- Use `v0.7.1-reviewed` only as the complete local/operator POC baseline.
- Build the next UX release from this hardened baseline, with actual source and a green packaged-build test.
