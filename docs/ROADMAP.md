# Roadmap after v0.8.1

## P0 — User test of the real Mom Mode

The next user-facing checkpoint is not another architecture rewrite. Test the v0.8.1 root UI with five tasks:

1. create a new customer and stop/resume midway;
2. reopen an existing TripCase without restating context;
3. start a flight search and leave/reopen progress;
4. draft a customer reply and record one of the four feedback outcomes;
5. use “不知道怎麼問” from a vague travel-agency situation.

Record hesitation, wrong taps, repeated questions and unclear language. Keep engineering functions under `/admin`.

## P1 — Live OpenClaw Browser Lab

### Airlines

Priority order: CI → BR → JX → CX → AE → IT → EK → NH.

Run at least 10 representative cases per high-priority airline. Promotion target for a simple search path:

- route/date/party correctness ≥90%;
- wrong-domain acceptance = 0;
- final payment/ticket submission = 0;
- schema-invalid output is always rejected or needs-review;
- every CAPTCHA/login/waiting-room blocker has a clear human handoff.

### Hotels

Test Hilton, Marriott, Hyatt and at least two independent hotel booking engines actually used in the pilot. Verify whole-stay total, mandatory fee completeness, room/bed/rate identity, member-rate state and cancellation rules.

## P2 — Skill Evolution Engine v0.9

Build on the v0.8.1 redacted evidence stream:

```text
feedback buffer
→ per-skill train / selection / fixed regression split
→ small bounded candidate patch
→ frozen-agent replay
→ utility + safety gate
→ pending proposal
→ human review
→ canary
→ promote or rollback
```

Start only with:

- `customer-reply`
- `guided-intake`
- `daily-radar`

Do **not** allow autonomous evolution of payment/PII/OTP/domain/tool/sandbox/visa-authority policy.

## P3 — LINE pilot

Expose only Mom Mode workflows:

- create/resume TripCase;
- customer reply drafts + feedback;
- official flight/hotel search and progress;
- case status / Next Best Action;
- Daily Radar.

Measure completion rate, average handling time, manual blocker frequency, revision rate and repeated-question rate.

## P4 — Confirmation ingestion

After a human completes an airline/hotel purchase:

- parse confirmation email/PDF;
- cross-check dates, names, amount and PNR/confirmation number;
- attach the verified record to TripCase;
- create downstream seat/transfer/visa/pre-trip tasks.

## P5 — Travel lifecycle and production hardening

- authoritative visa/entry provider;
- weather refresh and disruption monitoring;
- route-validated itineraries;
- group-tour checklist;
- pre-trip brief/PDF/video generation;
- PostgreSQL + sequential migrations;
- durable queue/outbox;
- KMS-backed PII protection and retention/deletion;
- role-based operator sessions instead of sharing an admin token with a browser UI;
- encrypted backups, metrics and alerts;
- isolated browser profiles/workers for concurrency;
- formal privacy/security review.
