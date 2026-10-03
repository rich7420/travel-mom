# Migration — v0.7.1 reviewed → v0.8.1

## 1. Back up first

Stop the service and copy the current SQLite database before starting v0.8.1.

Example:

```bash
cp data/travel_desk.db data/travel_desk.before-v081.db
```

## 2. Point v0.8.1 at the existing database

```env
TRAVEL_DESK_DB=./data/travel_desk.db
```

## 3. Start once

`init_db()` runs migration 801. It creates:

- `user_preferences`
- `skill_feedback`
- related indexes

It does not drop or recreate existing TripCases, flight runs, hotel runs, browser tasks or audit data.

## 4. Verify

```bash
pytest -q
curl http://127.0.0.1:8000/health
```

Then open `/` for Mom Mode and `/admin` for the existing engineering workbench.

## Rollback

The old v0.7.1 code can still ignore the newly added tables, but the safest rollback is restoring the pre-v0.8.1 database backup together with the old application package.

## Web workflow migration 802 (2026-10-03)

The current increment adds infant/child-age fields, manual offer and selection tables, and `browser_tasks.result_attempt_id`. Startup is additive and idempotent; back up the database before upgrading. Existing cases are preserved and historical inconsistent dates remain readable and can be repaired using the case edit form.

Historical browser results lack exact producing-attempt provenance and are displayed as demo/unusable for Mom quotations after upgrade, even if they previously came from a live query. Query them again, or record a freshly verified manual supplier offer. Migration does not guess provenance from the most recent attempt. Manual and official quotations without explicit supplier expiry use `QUOTE_MAX_AGE_HOURS` (default 24), independently of the checkout revalidation window.
