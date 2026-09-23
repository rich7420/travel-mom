# Local Browser Lab Runbook — v0.7

Use this on the computer that actually runs OpenClaw. The packaged/offline tests cannot prove live airline/hotel compatibility.

## 1. Preflight

```bash
cd mom-travel-desk-poc-v0.7
cp .env.example .env
# configure the private OpenClaw Gateway only on the backend
./scripts/openclaw_host_preflight.sh
```

Confirm:

- Gateway is private/loopback;
- `mom-travel` and `mom-travel-browser` are separate;
- browser profile is `openclaw` for unauthenticated discovery;
- browser plugin + bundled `browser-automation` are working;
- Travel Desk `/api/system/readiness` reports offline POC ready.

## 2. Airline campaign

Run CI/BR/JX/CX first. For each airline, cover at least:

1. simple round trip;
2. one way;
3. two adults;
4. adult + child;
5. cabin change where supported;
6. cross-month dates;
7. no-result route/date;
8. cookie/locale state;
9. a flow that causes a safe manual blocker;
10. selected-option revalidation.

Then AE/IT/EK/NH. Add Tigerair Waiting Room and time-limit scenarios. Do not defeat queues, anti-bot, CAPTCHA, OTP or 3DS.

After each run inspect `/api/browser/lab/summary`. Distinguish contract validation from usable automated success; a correct manual handoff is safe but not counted as automated success.

## 3. Hotel campaign

Start with one real property from each:

- Hilton;
- Marriott;
- Hyatt;
- two independent hotels Mom actually books.

For an independent property, manually verify the official URL and create a `HotelSiteGrant`; never grant an OTA because the rate page looks convenient.

Test:

- exact check-in/out;
- room count/adults/child ages;
- whole-stay total vs nightly headline;
- taxes/fees and mandatory property fees;
- room/bed identity;
- flexible vs non-refundable rates;
- breakfast state;
- member-rate requirements;
- cancellation deadline;
- pay-now/pay-later/pay-at-property;
- exact revalidation before preflight;
- login/member-only blocker;
- OTA redirect blocker.

## 4. Debugging a BrowserTask

Use the dashboard's Browser queue and attempt ledger. Record:

- task id;
- attempt id/source;
- browser profile;
- result status;
- validation errors;
- blocker;
- non-sensitive screenshot/log reference.

Do not copy customer passport/payment data into regression fixtures.

## 5. Recipe changes

A page failure does not authorize the browser worker to modify a skill/recipe. Create a site-change proposal, review it, add/update regression coverage, then rerun the affected campaign.

## 6. Promotion gate

Do not enable a supplier in Mom-facing LINE solely because a single test worked. Require repeated results, no wrong-domain acceptance, no irreversible actions, and understandable manual handoffs.
