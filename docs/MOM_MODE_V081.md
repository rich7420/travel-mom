# Mom Mode v0.8.1

## Goal

Mom Mode hides the implementation model. The operator sees **today’s work, customer cases, one next step, and human-readable progress** rather than agent/tool terminology.

## Default navigation

- **今天** — priority work, resumable searches, recent cases.
- **案件** — search and reopen a TripCase.
- **新客人** — persistent one-question-at-a-time intake.
- **問助理** — ordinary-language intent guidance when the user does not know which feature to choose.
- **設定** — default airport, frequent airlines, font size and connection token.

Engineering functions are separated at `/admin`.

## UX rules

1. Start from a TripCase whenever possible.
2. Do not ask the same fact twice if the case already contains it.
3. Ask one necessary question at a time.
4. Offer common choices and an “I don’t know” path.
5. A long-running official-site search is resumable; leaving the screen is safe.
6. Technical errors are translated into a user action, not raw logs.
7. Login / CAPTCHA / OTP / 3DS / final purchase is a human handoff.
8. Drafting a customer reply never means sending it.

## Accessibility

- Main touch targets are at least approximately 52–54 px high.
- Font modes: normal, large, extra-large.
- Keyboard focus is visible.
- Reduced-motion preferences disable transitions.
- Important buttons use text labels rather than icon-only controls.
- Strict CSP on Mom Mode avoids inline JavaScript.

## Data model

Mom Mode does not own a shadow database. It reads and writes the same:

- `trip_cases`
- `guided_sessions`
- `flight_search_runs`
- `hotel_search_runs`
- `browser_tasks`
- `user_preferences`
- `skill_feedback`

This prevents the “UI says one thing, core workflow says another” failure mode that a separate UX database would create.
