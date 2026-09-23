# Mom Travel Desk v0.6 — Security Review

Review date: 2026-08-25

## Threat model

The system may eventually handle:

- customer names/contact details;
- dates of birth and passport metadata;
- itinerary/PNR/ticket information;
- supplier and member-account sessions;
- prices, internal margin and customer communications;
- an OpenClaw Gateway operator credential;
- browser pages containing untrusted content.

The most important threats are credential exposure, prompt injection through web content, accidental irreversible transactions, duplicate webhook side effects, cross-customer data leakage and incorrect live travel facts.

## Current controls

### Gateway boundary

- Gateway URL/token are server-side environment variables.
- Frontend never receives the token.
- Example deployment publishes Travel Desk on loopback only.
- Readiness warns when Gateway host appears public.
- OpenClaw documentation treats the compatible HTTP bearer path as operator-level trust; this project does not assume scopes make it a low-privilege app token.

Residual risk: compromise of the Travel Desk backend could expose the operator token. Production should use network isolation, secret manager, rotation and ideally a dedicated Gateway instance for Mom.

### Agent separation

- General Mom agent has no browser, shell or write tools.
- Browser worker has browser only.
- Browser tasks are created by application workflow, not arbitrary channel prompts.
- Per-agent skill allowlists narrow visible procedures.

Residual risk: config drift on the real OpenClaw host. Mitigation is `config schema`, `doctor`, `policy check`, readiness and deployment review.

### Browser prompt injection

- Page content is explicitly treated as untrusted.
- Browser worker cannot use shell/filesystem mutation.
- `browser.evaluateEnabled=false` in example config.
- Navigation is official-domain default-deny.
- Browser output must pass typed validation.
- Page instructions cannot change payment/credential rules.

Residual risk: model may still click a dangerous official-site control. Mitigation is task wording, least privilege, no payment endpoints, manual checkout and live Browser Lab.

### Transaction safety

Application policy denies `PAYMENT`. Final purchase, ticket issuance, cancel and refund are not implemented. Preflight only returns readiness for human checkout.

Hard stops include:

- card number/CVV;
- OTP/3DS/CAPTCHA;
- final submit/pay/issue;
- paid add-on acceptance;
- cancellation/refund execution;
- unknown redirect.

Residual risk: an airline UI may use ambiguous buttons before final payment. Browser Lab must inspect each site's flow; the Browser worker should stop early when uncertain.

### Live-data correctness

Controls:

- typed schemas;
- official HTTPS source validation;
- airline code and route/date validation;
- contiguous connection chain checks;
- observed time;
- currency grouping without hidden FX;
- exact revalidation before preflight;
- freshness threshold;
- explicit acceptance of changed price/fare/rules.

Residual risk: visible fare rules may be incomplete or localized. Unknown remains `unknown`; human must review official checkout terms.

### Channel ingress and webhook duplication

- disabled LINE/Telegram channels do not process inbound events;
- Telegram inbound requests require the configured `X-Telegram-Bot-Api-Secret-Token`; missing or invalid secrets are rejected;
- an enabled channel without a non-empty user/chat allowlist is treated as misconfigured and processes nothing;
- LINE user IDs and Telegram chat IDs are checked before workflow execution;
- persistent `(channel,event_id)` idempotency record;
- payload hash;
- response saved before send;
- replay avoids repeated case/agent work;
- Telegram callback acknowledged.

Residual risk: production delivery needs a durable outbox and explicit retry/dead-letter strategy.

### PII

- optional Fernet-encrypted local vault;
- card/CVV keys rejected;
- high-risk PII not stored in `USER.md`, `SOUL.md`, `AGENTS.md` or general memory;
- browser/agent should receive only the minimum fields needed.

Residual risk: Fernet key in environment and SQLite single-file storage are pilot-grade only. Production needs KMS, per-field access control, retention/deletion, audit, backup encryption and incident response.

### Container

- non-root user;
- read-only root filesystem;
- writable named volume only for `/data`;
- `/tmp` tmpfs;
- all Linux capabilities dropped;
- no-new-privileges;
- host port bound to loopback;
- healthcheck.

Residual risk: host Docker/Gateway and dependency supply chain remain trusted. Production should pin dependencies and scan images.

### Skills and recipes

- local skills audited for frontmatter/naming/safety markers;
- community skills are reference material, not automatically installed;
- recipe changes require human review and regression cases;
- admin review skills lack write tools.

Residual risk: static audits are not malware/runtime verification. Any external skill/plugin requires source and dependency review.

## Findings fixed in v0.6 development

| Severity | Finding | Fix |
|---|---|---|
| High | Docker `.env` could override DB to read-only `/app/data` | Compose forces `/data/travel_desk.db` |
| Medium | Browser Lab historical attempts could inherit latest task result | Persist and aggregate attempt-specific `result_status` |
| Medium | Conversational and Browser work could share one broad agent | Separate model/agent/tool policies |
| Medium | Browser page-context JS expanded injection surface | Example config sets `evaluateEnabled=false` |
| Medium | Webhook retries could duplicate work | Persistent idempotency/replay |
| Medium | Disabled or incompletely configured channels could accept inbound work | Channel-level default-deny, Telegram webhook secret and required allowlists |
| Medium | Connecting itineraries falsely failed validation | Validate contiguous segment chains |
| Low | Official task/source accepted HTTP | Require HTTPS |
| Low | Origin could equal destination | Input validation rejects it |
| Low | SQLite concurrency posture | WAL + busy timeout + normal sync |

## Production blockers

- real OpenClaw policy/config validation;
- live airline Browser Lab;
- real user authentication/RBAC;
- secure secret manager/KMS;
- PostgreSQL and migrations;
- durable job/outbox layer;
- encrypted backups and restore drill;
- observability and alerts;
- PII lifecycle/retention controls;
- dependency/image scanning;
- formal privacy/legal review.
