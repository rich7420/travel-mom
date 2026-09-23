---
name: browser-lab-reviewer
description: Review airline Browser Lab attempts, separate safe handoffs from defects, and produce evidence-based maintenance recommendations.
user-invocable: false
---
# browser-lab-reviewer

Admin-only maintenance skill. Do not expose this workflow to Mom.

Use Browser Lab attempts, validator errors, screenshots, source URLs, task payloads, and recipe versions to classify a repeated issue as one of:

- `site_changed`: official UI or navigation changed;
- `recipe_gap`: semantic recipe omitted a stable business step;
- `agent_error`: the browser worker ignored an existing instruction;
- `validator_too_strict`: result is correct but typed validation rejects it;
- `validator_too_loose`: unsafe or mismatched data passed;
- `expected_manual_handoff`: login, passenger limit, special service, OTP, 3DS, CAPTCHA, anti-bot, or payment boundary;
- `transient`: timeout, availability fluctuation, locale/CDN issue, or temporary site outage.

## Review rule

Do not recommend changing a live recipe from one failure. Require either:

- at least two reproducible failures with equivalent evidence; or
- one high-severity validator/safety defect with a minimal regression case.

Report affected airline, recipe version, reproduction inputs, observed evidence, proposed change, risk, and tests required. Never edit or apply a live skill/recipe automatically.
