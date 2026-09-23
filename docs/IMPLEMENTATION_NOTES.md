# Implementation notes — v0.7

## OpenClaw capability assumptions

The POC targets current OpenClaw behavior reviewed on 2026-08-25:

- workspace skills are directories containing `SKILL.md` with YAML frontmatter;
- workspace skills have high precedence and can be filtered per agent;
- the browser plugin ships a bundled `browser-automation` skill;
- the managed `openclaw` browser profile is isolated from the personal browser;
- signed-in `user`/`chrome` modes exist but should be treated as sensitive escalation paths;
- page-context browser evaluation can be disabled;
- Gateway can expose `/v1/chat/completions`, whose bearer credential must stay server-side/private.

Because OpenClaw's configuration schema evolves, `openclaw.example.json5` is a reviewed template, not a substitute for target-host `config validate`, `doctor`, `security audit`, policy checks and browser deep doctor.

## Why two OpenClaw agents

The conversational and browser agents have different risk profiles.

```text
mom-travel
- understands Mom
- owns guided reasoning/drafts/planning
- no browser
- no shell/filesystem mutation

mom-travel-browser
- receives typed BrowserTask only
- browser tool only
- no shell/write/skill mutation
- returns typed evidence for backend validation
```

The backend explicitly chooses the browser model/agent for Browser tasks rather than allowing ordinary chat to gain browser access implicitly.

## Why semantic recipes, not hard-coded selectors

Airline and hotel websites change. Recipes describe:

- business intent;
- trusted starting domains;
- required inputs;
- evidence to extract;
- known blockers;
- safety/handoff behavior;
- typed output contract;
- regression cases.

OpenClaw's bundled browser skill handles snapshots, refs, tabs and stale-ref recovery. A selector fast path may be added only after live Browser Lab evidence and must never be the sole path.

## Browser output trust pipeline

Raw browser/model text is untrusted.

### Flight

```text
raw output
  ↓ JSON extraction
Pydantic `flight-search-v1`
  ↓
airline identity
  ↓
HTTPS official-domain match
  ↓
route/date/segment-chain checks
  ↓
currency/status/option checks
  ↓
auto_validated | needs_review
```

### Hotel

```text
raw output
  ↓ JSON extraction
Pydantic `hotel-search-v1`
  ↓
trusted official-site check
  ↓
hotel/date/rooms/party exact match
  ↓
room/rate/whole-stay-total checks
  ↓
fee/cancellation consistency checks
  ↓
auto_validated | needs_review
```

No customer-safe comparison is produced merely because the model says a result is correct.

## Hotel-site trust model

Known direct-booking networks are represented in a local registry. An independent hotel domain is default-deny until a human has verified and explicitly granted the exact host.

Known OTA/search domains cannot be promoted through the independent-hotel attestation route.

The current POC deliberately stops when a legitimate independent hotel redirects from its official domain to a different multi-tenant booking-engine domain. A later release should add **property-scoped booking-engine grants** rather than globally trusting a shared engine host.

## Whole-stay hotel pricing

The hotel model stores and compares whole-stay total, base amount, taxes and mandatory property fees when available. Nightly teaser prices are insufficient for ranking. The typed option also keeps:

- room type;
- bed type;
- rate plan;
- refundable state and cancellation deadline;
- breakfast inclusion;
- payment timing;
- loyalty/member-rate requirement;
- resort/destination fee;
- warnings.

## Search-run persistence

`FlightSearchRun` and `HotelSearchRun` store the original request and generated task ids. This allows resume-after-interruption, stable selection/revalidation context and case-based history without depending on an LLM conversation transcript.

## Attempt-level observability

`BrowserAttempt` preserves every try. A later successful retry does not rewrite an earlier `no_results`, validation error or manual blocker into a success. Browser Lab therefore distinguishes contract validation from usable result success.

v0.7 groups metrics by supplier identity, including `airline:CI` and `hotel:hilton.com` style providers.

## Revalidation design

Revalidation uses exact option identity before checkout.

Flight checks include flight numbers, segment sequence, dates, currency and fare identity. Hotel checks include selected room, bed/rate identity, dates, party and currency. Price/term changes are surfaced explicitly.

## Checkout preflight semantics

`ready_for_human_checkout` means only that:

- the latest typed result is valid and fresh enough;
- the requested/selected identity still matches;
- current total/currency are visible;
- material changes were explicitly accepted;
- required terms are sufficiently visible for human review.

It does **not** submit a final form, store card data, solve CAPTCHA, handle OTP/3DS, issue a ticket or guarantee inventory after the observation.

## Webhook idempotency

Channel event ids are persisted with payload hash, response and delivery status. Retried webhooks replay a prior domain result rather than repeating the domain operation. A production release should still use a durable outbound queue/outbox.

## SQLite and Docker

SQLite/WAL is adequate for the single-machine pilot. Production should move to PostgreSQL plus migrations/backups. The Docker POC remains non-root/read-only outside `/data` and `/tmp`, with loopback-only publication and no-new-privileges.

## Configuration readiness

`/api/system/readiness` is a static/configuration gate only. It does not prove live browser/channel connectivity. Real readiness requires target-host OpenClaw diagnostics plus supplier-specific Browser Lab.
