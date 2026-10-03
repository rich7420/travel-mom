# SQLite backup and recovery

These tools produce a new validated file and never replace a running database. Snapshots contain customer data and internal bookkeeping: keep the backup directory private, encrypted in storage, and outside the public static directories. Backup encryption and retention scheduling are not installed by this change. Retain any configured PII encryption key separately; copying SQLite does not recover a lost key.

From the repository, using the application's Python environment:

```sh
.venv/bin/python scripts/database_backup.py backup data/local-review.db /private/backups/desk-20261003.db
.venv/bin/python scripts/database_backup.py restore /private/backups/desk-20261003.db /private/recovery/desk-restored.db
```

Create the private directories first. The source is opened read-only using SQLite's backup API, which includes committed WAL transactions; do not copy just the main live `.db` file. The source directory may need write permission for SQLite shared-memory handling. The tool deliberately does not use `immutable=1`, which could ignore WAL contents.

The temporary snapshot is mode 0600 in the target directory. Before atomic publication without replacement it runs full integrity and foreign-key checks and verifies application tables and schema 803 or 804. Supporting 803 allows a verified pre-upgrade backup. Unknown versions, missing lifecycle immutability triggers and foreign-key orphans are rejected. A database with existing orphans cannot be published by this strict backup tool; preserve the original database and its sidecars and investigate on a separate copy rather than modifying the live file. Existing targets, dangling symlinks and target `-wal`, `-shm`, `-journal` files are refused. Do not reuse a live database path as the destination or create target-side SQLite connections during publication.

To recover the service:

1. Create a new restored file as above. Keep the original database and original backup.
2. Start a disposable application using the restored file, with integrations disabled and a separate loopback port. Verify expected cases, quotes, balances and evidence before switching.
3. Stop all application workers, change `TRAVEL_DESK_DB` to the new restored file, then restart. Do not copy over an active SQLite database or leave old sidecars next to the restored file.
4. Verify a known case and authenticated write, then confirm the new backups use the restored path. If recovery fails, stop the service and restore the prior configuration.

For Docker use the same application image and a new named data volume. Mount the backup volume read-only in the restore job and the new volume at `/data`. Ensure the non-root application user can write the destination volume. The reproducible synthetic drill automates this sequence:

```sh
docker build -t travel-mom-verify:local .
.venv/bin/python scripts/verify_container.py --image travel-mom-verify:local
```

It uses labelled disposable containers/volumes, ephemeral loopback ports, non-root execution, read-only root filesystem, `/tmp` tmpfs, no Linux capabilities and no-new-privileges. It verifies authentication, mounted SQLite writes, 100 concurrent synthetic writes, restart persistence and HTTP access after recovery in a second volume. It deletes only resources carrying its unique ownership label. This is a local recovery drill, not a production RPO/RTO or long-duration load guarantee.

[Python backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup) and [SQLite online backup](https://www.sqlite.org/backup.html) support the snapshot method. Technical references checked 2026-10-03.
