---
name: skill-evolution-proposal
description: Admin-only guidance for proposing small, evidence-backed Skill improvements that must pass held-out regression and human approval before promotion.
user-invocable: false
---
# skill-evolution-proposal

This is an **administrator / offline optimization** skill. It must not autonomously change production behavior.

A candidate proposal should contain:

1. target Skill and exact current Skill hash;
2. evidence counts by accepted / edited / prefer-future / rejected;
3. the recurring failure or preference pattern, using redacted evidence only;
4. the smallest bounded patch that addresses that pattern;
5. held-out evaluation cases and a fixed safety/regression bank;
6. expected utility improvement and any latency/token-cost change;
7. rollback target and canary plan.

## Selection gate

Reject the proposal if it only ties the current Skill, has too few independent examples, regresses a critical task, or changes a protected section. Promotion requires validation improvement plus zero safety regressions and explicit human approval.

## Permanently protected rules

Never propose edits that weaken:

- payment, card/CVV, ticketing, refund or irreversible-action gates;
- OTP, 3DS, CAPTCHA and human-login handoff;
- official-domain / hotel-site trust controls;
- PII redaction, retention or vault rules;
- browser/tool/sandbox permissions;
- authoritative-source requirements for visa, entry, health, fare and changing travel facts.

Rejected candidate edits should be retained as negative optimization evidence so the same failure is not repeatedly proposed.
