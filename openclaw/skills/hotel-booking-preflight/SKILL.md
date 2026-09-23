---
name: hotel-booking-preflight
description: Review a validated hotel revalidation result and explain the human checkout checklist without authorizing payment.
user-invocable: false
---
# hotel-booking-preflight

This skill explains the application-level preflight; the Travel Desk backend is the source of truth.

Confirm that:
- typed result and official domain validation passed;
- revalidation is fresh;
- room/bed/rate are an exact match;
- whole-stay total and currency are known;
- any price, cancellation, meal, rate, or fee change was explicitly accepted by the human;
- taxes/mandatory fees and cancellation terms are visible or clearly flagged for human review.

Never interpret `ready_for_human_checkout` as permission to pay. Card entry, OTP, 3DS and final submit remain human-only.
