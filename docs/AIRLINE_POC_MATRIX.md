# Airline official-site POC matrix — v0.7

Reviewed: 2026-08-25. Live airline websites remain authoritative; these rules are guardrails for Browser Lab, not permanent commercial-policy claims.

| Code | Airline | Official start | Important POC rule | Live-lab priority |
|---|---|---|---|---|
| CI | China Airlines | china-airlines.com flight search | do not invent party limits; use current site state | P0 |
| BR | EVA Air | booking.evaair.com | max 9 occupied tickets per transaction, infant excluded; at least one 16+ adult | P0 |
| JX | STARLUX | starlux-airlines.com flights | promotional/cache fares are discovery only; exact search + revalidation | P0 |
| CX | Cathay Pacific | cathaypacific.com book-a-trip | >9 travelers hands off from web booking | P0 |
| AE | Mandarin Airlines | mandarin-airlines.com BookingNPurchase | >4 occupied travelers hands off/split only by human decision | P1 |
| IT | Tigerair Taiwan | booking.tigerairtw.com | Waiting Room/time-limit is a manual blocker; never bypass queue | P1 |
| EK | Emirates | emirates.com book | max 9 total travelers in direct flow | P2 |
| NH | ANA | ana.co.jp plan/book | do not apply domestic-only numeric rules to international booking | P2 |

## Universal promotion gates

A carrier is not Mom-facing until repeated OpenClaw Browser tests show:

- correct route/date/party/cabin echo;
- official-domain only;
- typed output acceptance;
- usable option extraction;
- honest `manual_required` on blockers;
- no card/payment/ticketing action;
- exact revalidation of selected product.

Target for simple supported searches: ≥90% route/date/party correctness before promotion. Any wrong-domain acceptance or irreversible action is an immediate blocker.

## Evidence URLs embedded in code

Each `AirlineDefinition` carries `evidence_urls` and `source_note`; see `app/airlines.py`. Recipes also carry `last_reviewed` and regression cases under `recipes/airlines/`.
