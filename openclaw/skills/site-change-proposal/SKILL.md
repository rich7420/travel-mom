---
name: site-change-proposal
description: Turn a confirmed airline-site change into a reviewable recipe or workspace-skill proposal with tests and rollback notes.
user-invocable: false
---
# site-change-proposal

Admin-only governed maintenance skill.

Use only after `browser-lab-reviewer` has classified a reproducible issue. Create a proposal, not a silent live mutation.

## Proposal contents

- affected airline and official domains;
- current recipe/skill name and version;
- evidence and exact reproduction inputs;
- smallest semantic change needed;
- safety impact and new/changed permissions, if any;
- regression cases and expected structured result;
- rollback path;
- expiration/re-review date for temporary workarounds.

Prefer updating the per-airline semantic recipe over adding brittle selectors. If a workspace skill must change, route it through OpenClaw Skill Workshop in proposal mode. Do not apply a proposal until a human reviews the diff, scanner state, tests, and affected Browser Lab cases.

Never add payment, card/CVV, OTP, 3DS, CAPTCHA bypass, unknown-domain navigation, shell execution, or unrestricted page JavaScript evaluation.
