# Skill Evolution Foundation — v0.8.1

## Design target

The long-term goal is a travel assistant whose Skills improve from real work while remaining **observable, validation-gated, human-approved and rollbackable**.

v0.8.1 deliberately implements evidence capture before autonomous optimization.

```text
production Skill S_k
      │
      ▼
real tasks + explicit operator outcome
      │
      ▼
local PII redaction
      │
      ▼
Skill key + exact SHA-256 attribution
      │
      ▼
redacted evidence buffer
      │
      ├── accepted
      ├── edited
      ├── prefer_future
      └── rejected
      │
      ▼
offline candidate optimizer        (future)
      │
      ▼
held-out + safety regression gate  (future)
      │
      ▼
proposal / human approval          (future)
      │
      ▼
canary → promote or rollback       (future)
```

## Implemented in v0.8.1

- `skill_feedback` storage.
- Four explicit feedback types.
- Redacted draft/final/note only.
- Case-name redaction when a TripCase is known.
- Common email, phone, PNR, ticket-number and passport-pattern redaction.
- Edit-ratio calculation for edited outputs.
- Exact SHA-256 fingerprint of the local `SKILL.md` when available.
- Per-Skill feedback summary and a conservative proposal-readiness threshold.
- JSONL export for offline evaluation.
- `skill-feedback-capture` and admin-oriented `skill-evolution-proposal` guidance.

## Not implemented yet

- LLM-generated candidate patches.
- automatic Workshop proposal creation.
- held-out evaluator runner.
- canary deployment.
- automatic promotion.

This boundary is intentional: the system must first collect high-quality, redacted outcome evidence before optimizing production behavior.

## Protected, non-evolvable policy

No optimizer may weaken or rewrite:

- payment / card / CVV / irreversible action gates;
- ticket issuance, cancellation and refund authorization;
- login / CAPTCHA / OTP / 3DS human handoff;
- official airline/hotel domain trust;
- PII redaction, vault and retention controls;
- browser/tool/sandbox permissions;
- authoritative evidence requirements for visa, entry and other changing facts.

These belong to application/runtime policy, not learnable Skill prose.

## Evidence threshold

The current summary marks a Skill “ready for proposal work” only after at least 12 observations and at least 4 observations that contain an edit, explicit future preference, or rejection. This is a triage threshold, **not** a promotion decision.

A real optimizer should still require independent held-out tasks, fixed safety regressions, strict improvement rather than a tie, and explicit human approval.
