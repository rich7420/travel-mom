# OpenClaw / ClawHub skills review — v0.7

Reviewed: 2026-08-25

## OpenClaw-native design retained

OpenClaw's browser plugin already ships `browser-automation`, so Travel Desk should not clone low-level browser mechanics into airline/hotel skills. Local workspace skills focus on business meaning and output contracts.

The project currently ships 19 local skills:

```text
airline-official-search
booking-preflight
browser-lab-reviewer
customer-reply
daily-radar
flight-search
flight-shortlist
hotel-booking-preflight
hotel-official-search
hotel-price-revalidation
hotel-search
hotel-site-attestation
itinerary-builder
pretrip-briefing
price-revalidation
quotation
search-run-coordinator
site-change-proposal
visa-check
```

## Useful community patterns reviewed

### Google Hotels skill

The ClawHub Google Hotels skill is useful as a **discovery pattern**: browser isolation, date/location search, search-only semantics, and a rule not to complete a purchase. It explicitly allows visiting a hotel's own site after presenting search results.

We borrow the separation:

```text
Discovery surface
→ shortlist
→ official site
→ typed revalidation
→ human checkout
```

We do **not** install it by default into Mom's privileged browser worker because community skills expand the supply-chain and tool surface. A later discovery worker can be separate and read-only.

### Hotel MCP/API skills

Community hotel skills backed by third-party MCP/API services are useful references for structured destination/dates/guest/budget/tag inputs. They are not the default booking source here because Mom's workflow prefers direct official websites and third-party services would transmit trip details outside the official supplier path.

## Skill security rules

- Workspace skills remain the trusted, reviewed layer.
- Community skills are reference material until manually reviewed and pinned.
- Browser worker gets only browser-related local skills + bundled `browser-automation`.
- Conversational worker cannot directly operate Browser.
- A website cannot edit or self-install a skill.
- Site-change proposals require human review before application.
- Hotel domain attestation is a backend state change, not a browser-agent judgment.
