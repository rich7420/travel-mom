---
name: hotel-price-revalidation
description: Recheck the exact saved hotel room and rate plan on the approved official site before human checkout.
user-invocable: false
---
# hotel-price-revalidation

Use only for a typed hotel revalidation task linked to one validated `hotel-search-v1` option.

- Re-search the same property, dates, room count, guests, room/bed type, and rate plan.
- Do not silently substitute a nearby room or a different rate plan.
- Recheck total stay price, currency, taxes/fees, mandatory property fees, breakfast, cancellation deadline, payment timing, and membership requirement.
- If the exact product cannot be matched, return `unavailable` or `manual_required`, not a best guess.
- State every changed term explicitly.
- Return only `hotel-revalidation-v1` JSON.
- Hard stop before payment, final booking, OTP, 3DS, CAPTCHA, cancellation, or refund.
