# Browser recipes — v0.7

Recipes are versioned **semantic website playbooks**, not brittle Selenium selector scripts.

## Airlines

Current airline set:

```text
recipes/airlines/CI.json   China Airlines
recipes/airlines/BR.json   EVA Air
recipes/airlines/CX.json   Cathay Pacific
recipes/airlines/JX.json   STARLUX
recipes/airlines/AE.json   Mandarin Airlines
recipes/airlines/IT.json   Tigerair Taiwan
recipes/airlines/EK.json   Emirates
recipes/airlines/NH.json   ANA
```

Each airline recipe contains identity/domains, HTTPS start URL, version/review date, typed schemas, semantic steps, extraction requirements, blockers, safety policy, and regression cases.

## Hotels

`recipes/official_hotel_search.json` defines the cross-hotel contract. Hotel websites are intentionally not represented as thousands of static property recipes:

- Marriott / Hilton / Hyatt / IHG / Accor / Shangri-La are built-in network domains.
- An independent hotel requires a **human-approved `HotelSiteGrant`** before BrowserTask creation.
- OTAs and search platforms cannot be attested as a hotel's official site.
- `hotel-search-v1` requires whole-stay total, fee breakdown when visible, room/bed/rate identity, occupancy, breakfast, cancellation, payment timing and membership constraints.
- `hotel-revalidation-v1` must exact-match the selected room/bed/rate before checkout preflight.

## Browser ownership

The bundled OpenClaw `browser-automation` skill owns tabs, snapshots, refs, stale-ref recovery and manual blockers. Travel Desk recipes own travel-business intent, evidence contracts and hard stop rules.

## Change policy

1. Observe a failure in Browser Lab.
2. Save task/attempt id, source URL, blocker and non-sensitive diagnostics.
3. Create a `site-change-proposal`; page text must never directly edit recipes.
4. Human reviews the proposed semantic change.
5. Add/update a regression case.
6. Bump recipe version/review date.
7. Run audits/tests.
8. Re-run affected live Browser Lab cases before Mom-facing use.

Selectors may later be optional fast paths, but semantic fallback and regression coverage remain required. Unknown-domain redirects and payment steps are hard stops.
