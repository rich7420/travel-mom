# Browser Lab Plan — v0.7

The executable procedure is in [`LOCAL_BROWSER_LAB_RUNBOOK.md`](LOCAL_BROWSER_LAB_RUNBOOK.md).

## Purpose

The offline suite proves persistence, typed contracts, validators, comparison and approval gates. It does **not** prove that today's airline or hotel UIs are automatable. Browser Lab closes that gap with repeatable live runs and attempt-level evidence from the target OpenClaw host.

## Supplier waves

### Wave A — Taiwan/direct-airline core

1. CI China Airlines
2. BR EVA Air
3. JX STARLUX
4. CX Cathay Pacific

Test clean isolated-profile search first. Do not introduce signed-in/member profiles until anonymous search is stable.

### Wave B — special airline behavior

5. AE Mandarin Airlines — passenger-limit and Taiwan domestic-flow cases
6. IT Tigerair Taiwan — waiting-room/time-limited-flow cases
7. EK Emirates — locale/currency/connecting itinerary cases
8. NH ANA — international/Japan-domestic entry-point differences

### Wave C — direct hotel networks

1. Hilton
2. Marriott
3. Hyatt
4. one IHG or Accor property

Test room identity, bed type, rate-plan identity, whole-stay total, tax/mandatory fee visibility, breakfast, cancellation deadline and payment timing.

### Wave D — independent hotels

Choose at least two properties Mom actually uses. Verify their official domain manually before granting trust. If an official property site redirects to a different hosted booking-engine domain, stop and document it rather than globally trusting the engine.

## Promotion metrics

For every supplier record:

- route/date/party or hotel/date/party correctness;
- typed-contract validation rate;
- usable-success rate;
- blocker/manual-handoff rate;
- median duration;
- wrong-domain count;
- unsafe-action count;
- baggage/rule extraction correctness for airlines;
- room/rate/cancellation/fee extraction correctness for hotels;
- exact revalidation rate;
- site-change/recovery notes.

A manual stop for login/CAPTCHA/OTP/3DS/waiting room is safe behavior, **not** an automated success.

## Suggested promotion threshold

A supplier should remain hidden from Mom's normal UI until a representative test set demonstrates:

- no wrong-domain navigation accepted by the backend;
- no autonomous payment/final booking behavior;
- all malformed or mismatched results rejected or routed to review;
- at least ~90% condition correctness on the intended simple-search cohort;
- a clear manual-handoff path for known blockers.

The threshold is a pilot policy, not a claim that a website will remain stable after promotion. Continue regression monitoring after release.
