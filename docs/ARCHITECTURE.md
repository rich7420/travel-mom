# Mom Travel Desk v0.7 — Architecture

## Product thesis

Mom Travel Desk is a **case-based, guided, proactive travel-agency copilot**. Conversation is an interface; `TripCase` and typed workflow records are the system of record.

```text
Mom (LINE) / Admin (Telegram) / Mini App
                  │
            Guided UX + Case UI
                  │
                TripCase
          ┌───────┴────────┐
          │                │
   Conversation agent   Deterministic workflow engine
     `mom-travel`         SearchRun / validation / policy
          │                │
     no browser            ▼
                     BrowserTask queue
                           │
                    least-privilege
                  `mom-travel-browser`
                           │
        ┌──────────────────┴──────────────────┐
        ▼                                     ▼
 Airline official sites              Hotel official sites
 CI BR CX JX AE IT EK NH       built-in networks / human grants
        │                                     │
        └─────────── typed observations ──────┘
                           │
                 schema + domain + intent
                      validation
                           │
             compare → select → revalidate
                           │
                    booking preflight
                           │
                 HUMAN final checkout
```

## Boundaries

1. **State is not stored in Claude chat.** Cases, runs, tasks, attempts, selections, trust grants and audit events are persistent application records.
2. **Agents handle ambiguity; code handles invariants.** Natural-language understanding and website recovery are agentic. Dates, domains, schemas, revalidation freshness and payment prohibitions are deterministic.
3. **Browser is a worker, not the brain.** It receives a typed BrowserTask and has only the browser tool.
4. **Official-site trust is explicit.** Airline domains are registry-defined. Major hotel networks are registry-defined; independent hotels require a human-approved `HotelSiteGrant`.
5. **Search is not booking.** Search result → selected product → exact revalidation → preflight → human checkout are separate states.
6. **No card data path exists.** Card/CVV, OTP, 3DS and final irreversible submit are outside agent authority.

## Flight workflow

```text
FlightSearchRequest
→ FlightSearchRun
→ one BrowserTask per airline
→ flight-search-v1
→ strict route/date/domain/schema validation
→ deterministic cross-airline comparison
→ selected option
→ flight-revalidation-v1
→ booking-preflight-v1
→ human airline checkout
```

## Hotel workflow

```text
HotelSearchRequest
→ official-site trust check
   ├─ built-in hotel network → proceed
   └─ independent property → human HotelSiteGrant required
→ HotelSearchRun
→ hotel-search-v1
→ whole-stay total / taxes / property fees / room / bed / rate / meal / cancellation validation
→ deterministic room/rate ranking
→ selected option
→ hotel-revalidation-v1 exact match
→ hotel-booking-preflight-v1
→ human hotel checkout
```

## Hotel trust model

The system deliberately does **not** treat every hotel-looking URL as trusted.

- Built-in network registry: Marriott, Hilton, Hyatt, IHG, Accor, Shangri-La.
- Independent hotel: exact HTTPS host is default-deny until a human attests it.
- Known OTA/search domains are denied from being attested as hotel official sites.
- Grants are auditable and revocable; revocation also prevents later Browser result acceptance for that host.

## Evidence / telemetry

Every browser task can have multiple `BrowserAttempt` rows. Metrics intentionally separate:

- typed-contract validation;
- usable automated results (`ok` / `found`);
- safe manual handoff;
- no result/unavailable;
- validation failures and blockers.

Browser Lab now groups both airline suppliers and hotel official hosts instead of collapsing hotels into a generic bucket.

## Deployment boundary

```text
Internet channels
  LINE / Telegram
        │
Travel Desk backend
  - holds channel secrets
  - holds OpenClaw Gateway credential
  - owns policy / DB / PII vault
        │ private
OpenClaw Gateway
        │
managed `openclaw` browser profile by default
```

Never place the OpenClaw Gateway operator credential in browser JavaScript, LINE payloads or Telegram messages.
