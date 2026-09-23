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
