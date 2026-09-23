# Mom Travel Desk v0.7 — Progress

Updated: 2026-08-25

## Milestone state

| Area | POC readiness | Current state |
|---|---:|---|
| Product / Mom UX | 88% | Case-first, one-question-at-a-time, mobile dashboard, flight + hotel actions |
| Core backend | 93% | TripCase, persistent runs/tasks/attempts, policies, audit, revalidation/preflight |
| Airline workflow | 80% offline / 45% live | Eight airline recipes; real OpenClaw Browser Lab still required |
| Hotel workflow | 75% offline / 20% live | Official-site trust, search, compare, revalidation, preflight now implemented |
| OpenClaw integration | 80% | dual agents, 19 workspace skills, private Gateway adapter |
| LINE / Telegram | 65% | webhook code hardened; no real Mom account pilot yet |
| Security / privacy | 70% | deny-by-default domains, PII vault, no payment path, trust revocation |
| Production readiness | 40% | good home/internal pilot foundation; not production booking software |

Percentages describe milestone readiness, not engineering-hours precision.

## v0.7 completed

- Added EVA (`BR`) and Tigerair Taiwan (`IT`) to airline registry and recipes, bringing supported airline recipes to 8.
- Added hotel official-network registry and default-deny independent hotel trust.
- Added auditable/revocable `HotelSiteGrant`.
- Added persistent `HotelSearchRun`.
- Added `hotel-search-v1`, `hotel-revalidation-v1`, and `hotel-booking-preflight-v1`.
- Added hotel result validation, deterministic comparison, exact revalidation and human acceptance gate.
- Added hotel workflow to mobile UI, including trust attestation/revocation.
- Browser Lab now distinguishes airline and hotel suppliers.
- Expanded local workspace skills from 15 to 19.
- Added hotel semantic recipe + regression audit.
- Added deterministic v0.7 hotel end-to-end demo.
- Added API coverage for hotel networks, default-deny, OTA rejection and grant revocation.

## Still external / unproven

The following cannot be truthfully marked complete without the user's actual OpenClaw host and browser:

- CI/BR/CX/JX/AE/IT/EK/NH live booking-page reliability;
- Hilton/Marriott/Hyatt/independent hotel engine reliability;
- signed-in member-rate flows;
- LINE Official Account webhook roundtrip;
- CAPTCHA/anti-bot frequency;
- browser recipe recovery after actual site UI changes.

## v0.7 exit gate

Code milestone is complete when:

- all automated tests pass;
- Python/JS compile checks pass;
- 19 skill audit passes;
- 8 airline recipe audit passes;
- hotel recipe audit passes;
- airline and hotel deterministic demos prove changes block preflight until accepted;
- package is clean and reproducible.

Live milestone closes only after the local Browser Lab promotion gates in the Roadmap are satisfied.
