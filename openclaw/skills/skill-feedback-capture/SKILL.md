---
name: skill-feedback-capture
description: Turn explicit user adoption, edits, preferences, and rejection into redacted Skill-improvement evidence without modifying the live Skill.
user-invocable: false
---
# skill-feedback-capture

Use only when Mom Travel Desk records explicit outcome feedback such as:

- 👍 accepted without edits
- ✏️ user edited the draft
- 🧠 user says to prefer this behavior in future
- 👎 user rejects the behavior

## Evidence rules

- The application performs deterministic PII redaction before evidence is stored or exported.
- Attribute evidence to the exact `skill_key` and SHA-256 of the `SKILL.md` that produced it when available.
- Preserve the redacted draft, redacted final version, edit ratio, outcome type, case reference, and timestamp.
- A single case is an observation, not a new rule. Never update a live Skill because of one anecdote.
- Customer-specific facts stay in TripCase/CRM data and must not become global Skill instructions.

## Safety

This is **capture-only**. It cannot write, patch, install, enable, or promote a Skill. It cannot modify tool permissions, policy, domain allowlists, or safety constraints.
