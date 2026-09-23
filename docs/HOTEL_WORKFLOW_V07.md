# Hotel official-site workflow — v0.7

## Why this exists

The prior POC could rank demo hotels but did not provide a trustworthy path for the real agency habit: choose a hotel, open its own official site, compare actual room/rate conditions, then let a human complete checkout.

v0.7 turns that into typed workflow state rather than a free-form browser chat.

## 1. Establish official-site trust

### Built-in networks

The initial registry covers:

- Marriott (`marriott.com`)
- Hilton (`hilton.com`)
- Hyatt (`hyatt.com`)
- IHG (`ihg.com`)
- Accor (`all.accor.com`, `accor.com`)
- Shangri-La (`shangri-la.com`)

This is intentionally a convenience registry, not a claim that these are the only valid hotels.

### Independent properties

An independent property is default-deny. A human must verify its HTTPS site and create a `HotelSiteGrant`. The grant is stored with hotel name, domain, source/evidence note, timestamps and audit trail.

Known third-party booking/search domains (Booking.com, Agoda, Expedia, Hotels.com, Trip.com, Traveloka, Tripadvisor, Trivago, Kayak, Priceline, HotelsCombined, Klook, KKday, Rakuten, Jalan, Ctrip, Google) cannot be promoted to "official hotel site" by the attestation endpoint.

Grants are revocable from the UI/API.

## 2. Search contract: `hotel-search-v1`

The browser worker must echo exact:

- hotel name;
- check-in/out;
- rooms;
- adults;
- child ages.

Each room/rate option includes:

- whole-stay total and currency;
- base amount;
- taxes/fees;
- mandatory property/resort/destination fees when visible;
- room and bed identity;
- rate plan;
- occupancy;
- breakfast;
- refundable state and cancellation deadline;
- payment timing;
- member-rate / loyalty requirements;
- warnings and observation timestamp.

Unknown fee data is `null`, never silently assumed to be zero.

## 3. Compare

Only `auto_validated` results enter ranking. Ranking explains tradeoffs instead of hiding them:

- total price relative to cheapest validated room;
- refundable preference;
- breakfast requirement;
- fee breakdown completeness;
- pay-later/pay-at-property value;
- membership restrictions;
- configured TWD budget;
- warnings.

Mixed currencies are not silently converted.

## 4. Revalidate

Selection creates `hotel-revalidation-v1`. Revalidation must exact-match the selected:

- property;
- dates/party;
- room name;
- bed type;
- rate plan.

It then rechecks price, currency, fees, breakfast, cancellation and payment timing. A close/uncertain product match cannot pass preflight.

## 5. Preflight

`hotel-booking-preflight-v1` checks:

- typed validation;
- official-domain trust still active;
- fresh observation;
- exact room/bed/rate identity;
- whole-stay total;
- explicit human acceptance of price/term changes;
- visibility of fees/cancellation/breakfast/payment timing.

The only success state is `ready_for_human_checkout`. It is not permission for the agent to submit payment.

## 6. UI

v0.7 adds:

- **官方飯店查房** form;
- hotel-network quick selection;
- independent-site attestation gate;
- Hotel Search Run history per TripCase;
- typed room comparison;
- revalidation;
- change acceptance checkbox;
- hotel checkout preflight;
- hotel trust registry and revoke UI.

## Next Browser Lab

Before Mom-facing production use, test at least one real property each on Hilton/Marriott/Hyatt plus several independent hotel engines. Record:

- date/guest selector reliability;
- whether whole-stay totals are available pre-login;
- mandatory-fee visibility;
- cookie/locale behavior;
- login/member-rate handoff;
- anti-bot/CAPTCHA frequency;
- room/rate exact-match stability during revalidation.

## Known limitation: property-authorized external booking engines

Some independent hotel official sites legitimately hand off to a separately hosted booking engine. v0.7 intentionally **stops on that cross-domain redirect** rather than broadly trusting a multi-tenant booking-engine domain. The next safe design should use a property-scoped redirect grant (hotel + source official host + exact booking host/path + evidence), not a global allowlist for an entire SaaS booking engine.
