# Mom Mode refinement context

Goal: Make daily travel-agency work easier to scan, with less repeated guidance and decorative weight.
User: Mom, a frequent operator with limited technical comfort; preserve large text and touch targets.
Job: Identify next case, then intake/search/select/reply through the same web interface.
Constraints: Existing FastAPI, vanilla JS and CSS; maintain DOM hooks and workflow. No version in visible Mom or admin UI; retain it in HTML comments and health metadata.
Direction: Warm paper, deep navy hero and sidebar, restrained terracotta accent, consistent SVG icons and numbered priority cases. Four clear shortcuts and secondary collapsed history. Wide desktop two-column workspace; intermediate desktop stacks the workspace; mobile uses a single column and bottom navigation.
Success: No visible version; no horizontal overflow at 390px with large/extra-large text; main actions remain >=44px; existing 3-customer/offer/draft workflow passes; loading/empty/error states remain usable.
Scope: UI refinement and optional verified Cloudflare Access backend protection, deployment guidance. Local dev remains available. Cloudflare account/tunnel provisioning and InsForge migration are later.
Assumptions: A small family/internal operator group; only explicitly allowed emails get access. Admin controls need a narrower email allowlist. Preserve existing typography preferences.
Risks: Login readiness requires actual Cloudflare Access configuration and a live deployment verification. Automated visual checks do not establish full screen-reader conformance.

## Revised visual brief (user feedback, 2026-10-03)

The first pass was tidy but insufficiently designed. Replace generic dashboard styling with an intentional travel workspace: warm paper background, deep navy brand/hero, restrained terracotta accents, consistent SVG line icons, strong headline/body hierarchy, and an integrated workflow rail. Desktop: fixed side navigation and a broad workspace with primary/secondary columns. Mobile: compact header, bottom navigation and a carefully composed hero. Preserve 18/20px typography, 44px controls and all existing case tasks. Hero graphics must be lightweight code-native SVG/CSS, with no external fonts/assets or arbitrary stock photo. No actual MFA/auth deployment changes in this visual phase.


## In-web guide and workflow coverage (2026-10-03)

Goal: Let Mom find instructions while doing work, and communicate exactly which agency tasks are supported.
Scope: Generate a readable, same-origin static guide from the existing Traditional Chinese Markdown manual; link from the app and relevant forms in a separate tab. Existing Access protection for /static applies; do not change authentication or workflow models.
Direction: Match paper/navy styling; desktop contents navigation, mobile native disclosure, large/extra-large font controls, printable content, native chapter anchors and visible new-tab guidance. Reading help must leave the original form/draft intact.
Success: Guide and source stay synchronized via deterministic generation check; all chapter links resolve; no visible version or localhost-dependent navigation; 390px extra-large no overflow; >=44px guide controls; guide usable without JS; existing workflow regression still passes; signed operator can read guide and unsigned Access requests cannot.
Assumption: Mom handles individual/family flight and hotel inquiries. Her actual workload frequency is unknown; do not claim a percentage or most end-to-end agency work covered.
Coverage: Recheck actual UI actions, services and durable records, distinguishing usable Mom workflows, optional/unverified automation, admin-only capabilities and missing business tasks. Status labels, enums and Skills descriptions are not evidence of executed bookings or delivered travel documents.
