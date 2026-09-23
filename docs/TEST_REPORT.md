# Mom Travel Desk v0.7 — Test Report

Verification date: 2026-08-25.

## Release verdict

The packaged v0.7 build passes the **offline POC gate**. The typed flight workflow from v0.6 remains intact, and the new official-hotel-site workflow is covered end-to-end with deterministic demo data. This does **not** prove live airline/hotel website compatibility; that remains the purpose of Browser Lab on the target OpenClaw host.

## Automated test suite

Command:

```bash
pytest -q
```

Result:

```text
45 passed
```

Coverage includes:

- API health and configuration readiness;
- TripCase and guided intake behavior;
- application-level action policy and payment denial;
- LINE/Telegram disabled-channel fail-closed behavior, allowlists and webhook replay protection;
- CI/BR/CX/JX/AE/IT/EK/NH airline registry and official-domain policy;
- airline-specific passenger handoff rules;
- flight Search Run persistence, typed `flight-search-v1`, comparison, exact revalidation and checkout preflight;
- connecting-itinerary segment-chain validation;
- hotel-network registry and trusted-domain checks;
- independent-hotel human site grants and revocation;
- known OTA/search-domain attestation rejection;
- typed `hotel-search-v1` validation;
- whole-stay hotel price normalization and comparison;
- exact hotel revalidation and explicit change acceptance;
- hotel checkout preflight with payment remaining human-only;
- Browser Attempt ledger and supplier-aware Browser Lab metrics;
- frontend exposure of the v0.7 hotel workflow;
- local skill and recipe audit behavior.

## Python compilation

```bash
python -m compileall -q app
```

Result: **PASS**

## Frontend JavaScript syntax

```bash
node --check app/static/app.js
```

Result: **PASS**

## Local OpenClaw skill audit

```bash
python scripts/audit_skills.py
```

Result:

```text
OK: 19 local skills audited
```

The local skill set now includes hotel official-site search, hotel-site attestation, hotel revalidation and hotel booking preflight in addition to the flight and travel-agency workflow skills.

## Airline recipe audit

```bash
python scripts/audit_airline_recipes.py
```

Result:

```text
OK: 8 airline recipes audited; 16 regression cases
```

Covered airlines:

```text
CI  China Airlines
BR  EVA Air
CX  Cathay Pacific
JX  STARLUX
AE  Mandarin Airlines
IT  Tigerair Taiwan
EK  Emirates
NH  ANA
```

The audit validates recipe metadata, official-domain declarations, schema/safety requirements and regression-case presence. It does not claim live browser compatibility.

## Hotel semantic recipe audit

```bash
python scripts/audit_hotel_recipe.py
```

Result:

```text
OK: hotel semantic recipe audited; 4 regression cases
```

The hotel recipe enforces:

- official/trusted-site policy;
- search/revalidation contracts;
- whole-stay totals rather than misleading nightly-only prices;
- room/rate/cancellation/breakfast/fee evidence;
- no automatic payment, OTP, 3DS or CAPTCHA bypass;
- default-deny for unverified independent hotel domains and OTAs.

## Offline flight workflow demo

```bash
python scripts/run_v06_demo.py
```

Result: **PASS**

Verified sequence:

1. temporary isolated database;
2. TripCase creation;
3. CI/JX/CX flight Search Run;
4. typed demo-result ingestion;
5. deterministic comparison;
6. option selection;
7. exact price revalidation with a TWD 300 increase;
8. checkout preflight blocked before explicit acceptance;
9. checkout preflight ready after acceptance;
10. `payment_handled_by_agent=false`;
11. Browser Lab summary remains attempt-aware.

## Offline hotel workflow demo

```bash
python scripts/run_v07_demo.py
```

Result: **PASS**

Verified sequence:

1. temporary isolated database;
2. TripCase creation;
3. trusted Hilton official-site Hotel Search Run;
4. typed `hotel-search-v1` ingestion;
5. comparison of refundable/flexible vs advance-purchase rooms;
6. option selection;
7. exact `hotel-revalidation-v1` with a TWD 1,200 increase;
8. checkout preflight blocked before explicit acceptance;
9. checkout preflight ready after acceptance;
10. `payment_handled_by_agent=false`.

Demo availability and prices are synthetic and must never be shown as live quotations.

## API smoke script

```bash
python scripts/smoke_api.py
```

Result: **PASS**

Verified examples:

```text
GET  /health                       -> ok=true, app_version=0.7.0
GET  /api/system/readiness         -> offline_poc_ready=true
GET  /api/airlines                 -> CI,BR,CX,JX,AE,IT,EK,NH
POST /api/browser/flight-search    -> persistent planned run
GET  /api/hotels/networks          -> 6 built-in direct-booking networks
POST /api/browser/hotel-search     -> hotel-search-v1 planned run
GET  /api/browser/lab/summary      -> browser-lab-summary-v2
```

Built-in hotel networks in the POC are Marriott, Hilton, Hyatt, IHG, Accor and Shangri-La. Independent properties require an explicit human site grant.

## OpenClaw host-preflight shell syntax

```bash
bash -n scripts/openclaw_host_preflight.sh
```

Result: **PASS**

The script includes an OpenClaw browser deep-doctor check. The actual OpenClaw commands are intentionally not executed here because they require the target user's host, Gateway and browser installation.

## Local Markdown link check

All local documentation links referenced by the release docs resolve inside the source tree.

Result: **PASS**

## Docker/static hardening retained

Source review retains the POC hardening from v0.6:

- non-root application process;
- read-only root filesystem;
- writable `/data` volume and `/tmp` tmpfs only;
- loopback-only port publication in Compose;
- dropped Linux capabilities and `no-new-privileges`;
- application healthcheck;
- no payment-card/CVV storage path.

A real Docker build/run is still a target-host test because this execution environment does not provide the user's Docker/OpenClaw runtime.

## Not tested in this environment

The following remain explicit release blockers before claiming a live internal pilot:

- target-host `openclaw config validate`, `doctor`, `security audit` and browser deep doctor;
- live OpenClaw Gateway request routing;
- live managed Chromium operation;
- real CI/BR/CX/JX/AE/IT/EK/NH search and revalidation;
- real airline anti-bot, waiting-room, locale, login or CAPTCHA behavior;
- real Marriott/Hilton/Hyatt/IHG/Accor/Shangri-La navigation;
- independent-hotel external booking-engine redirects;
- real LINE Official Account webhook and Rich Menu/MINI App;
- production Telegram bot;
- signed-in/member-rate browser profiles;
- real customer PII;
- payment, ticket issuance, cancellation and refund execution, which remain intentionally outside agent autonomy.

## Next release gate

v0.8 should not be declared ready for Mom until live Browser Lab establishes supplier-by-supplier evidence. Recommended first wave:

1. CI / BR / JX / CX;
2. AE / IT;
3. EK / NH;
4. Hilton / Marriott / Hyatt;
5. two independent hotels that Mom actually uses.

For every supplier, record contract-validation rate, usable-success rate, manual-blocker rate, median duration, wrong-domain incidents, unsafe-action incidents and exact revalidation rate.
