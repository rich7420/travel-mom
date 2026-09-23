# Review: v0.5 → v0.6

## Review objective

Check whether v0.5 was merely a convincing demo or a recoverable, measurable and safely deployable Browser POC.

## Findings and changes

| Finding | Risk | v0.6 response |
|---|---|---|
| Multi-airline tasks had no durable user-level run | UI/session loss made work hard to resume | Added persistent `FlightSearchRun` and run APIs/UI |
| Selecting an option did not create a formal next stage | Old price could be carried to checkout | Added exact `flight-revalidation-v1` |
| No deterministic payment-preflight gate | Agent explanation could be mistaken for permission | Added freshness/exact-match/acceptance checklist |
| Browser Lab used task latest state for attempt success | Retry history could be overstated | Persisted attempt-specific `result_status` |
| LINE/Telegram retries could duplicate work | Duplicate cases/messages/agent calls | Added persistent inbound event idempotency/replay |
| One broad OpenClaw agent could mix conversation and browser privilege | Larger blast radius | Split `mom-travel` and browser-only worker |
| Browser evaluate was not explicitly disabled | Larger page-context injection surface | Disabled in example config |
| Route validator expected a direct segment | Valid connecting options rejected | Added contiguous segment-chain validation |
| Docker `.env` DB path overrode writable volume | Read-only container could fail at startup | Compose forces `/data/travel_desk.db` |
| SQLite default journal posture | More contention under concurrent webhooks | Enabled WAL and normal sync |
| Browser task/source accepted HTTP | Downgrade risk | HTTPS required |
| Inline handler values needed stronger escaping | Browser/model output could affect UI markup/JS | Added `esc` + `jsArg` hardening |
| No operational readiness view | Config incompleteness was hard to diagnose | Added `/api/system/readiness` and UI |
| Recipe changes had no explicit governance path | Silent breakage or unsafe auto-repair | Added versioned regression cases and proposal-only repair skill |

## Conclusion

v0.5 proved the domain layering. v0.6 turns it into an offline-complete Browser Lab candidate with persistent workflow, typed revalidation, attempt-level evidence and safer deployment boundaries.

The remaining primary uncertainty is external: real airline UI behavior on the user's OpenClaw machine.
