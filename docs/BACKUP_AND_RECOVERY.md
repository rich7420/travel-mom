# Encrypted backup and recovery

Use encrypted bundles for the live database and its immutable original documents. The key (`PII_FERNET_KEY`) must be valid, available to the application and backup job, and stored separately from backup copies. Losing it loses access to encrypted travellers, originals and bundles. No keys are placed in bundles or command arguments. Keep `.env` private (0600); public deployment still needs a secret-manager/key-custody policy.

From the application's Python environment:

```sh
.venv/bin/python -m scripts.backup_bundle run --env-file .env
.venv/bin/python -m scripts.backup_bundle status --env-file .env
```

`BACKUP_DIR` defaults to `backups` beside the configured database; `ATTACHMENTS_DIR` defaults to `attachments` there. Private directories use 0700, files 0600. Each successful bundle contains an encrypted SQLite snapshot, encrypted authenticated manifest and copies of encrypted immutable originals, including archived history. Snapshot integrity, foreign keys, schema 803/804/805/806, lifecycle triggers and referenced file decryption/hashes are checked before publication. Manifest filenames and original filenames never appear in cleartext. The live database still has legacy plaintext fields; full database encryption applies to the bundle, not the running SQLite file.

A nonblocking interprocess file lock serializes snapshot/copy/publication/retention. Brief status-read contention is retried. Retention keeps the newest 14 authenticated bundles; unknown directories and corrupt/unrecognized bundles are left alone. A failed run preserves the last successful completion and records a separate failure. Retention/orphan-scan errors are maintenance warnings after a completed backup. Report-only orphan counts cover unreferenced blobs older than 24 hours; there is no automatic file deletion.

Plain SQLite staging is on the **database volume**, in a private tool work directory, outside the backup root. An interrupted run may leave a private plaintext snapshot there; the next locked run removes its abandoned work. Backup-root staging contains encrypted content only. Do not sync the database volume or tool work directories as if they were encrypted backup bundles. A forced-SIGKILL regression verifies this separation and cleanup.

Fernet processes whole messages in memory. Database snapshots are limited to 128 MiB, original files to 10 MiB. Reserve several times the DB size in memory, plus file buffers; this is a small-desk backup format, not a large-database streaming format. The job rejects insufficient disk space and oversized databases. It uses SQLite's backup API, including committed WAL contents; never copy only a running main `.db` file.

## Schedule one runner per deployment

On macOS, generate a project-specific per-user launchd job:

```sh
.venv/bin/python scripts/install_backup_schedule.py
# Install and load a per-user job; immediately runs, then repeats every six hours:
.venv/bin/python scripts/install_backup_schedule.py --install
```

Installation writes a unique job under `~/Library/LaunchAgents`, runs without elevated privileges and refuses existing job files/loaded jobs. Logs stay in the local ignored `data` directory. The job invokes the project's Python environment and `.env`; verify its first successful status rather than assuming installation means a successful backup. To remove, use `launchctl bootout gui/$(id -u)/LABEL`, then remove that exact project plist. Do not run launchd and a second container/cron backup schedule for the same desk.

For Linux/Docker, use the deployment's scheduler to run `python -m scripts.backup_bundle run` in the same image against the data volume with the same key. The compose file does not install a second scheduler. Admin → **備份狀態** shows running, previous success/failure, retention and maintenance warning; it is admin-only under Cloudflare. There is no web restore or backup job execution inside HTTP workers.

The local schedule protects this machine's working files only. Off-site copies, a host-loss recovery drill, disk encryption, key custody, monitoring and external failure notifications still need a real deployment and account configuration. Failure status is visible in the admin UI; no email/LINE is sent.

## Restore offline to new targets

Create private parent directories, stop the disposable recovery instance, and choose paths that do not exist:

```sh
.venv/bin/python -m scripts.backup_bundle restore --env-file .env \
  --bundle /private/backups/bundle-YYYYMMDDTHHMMSS-ID \
  --database /private/recovery/desk-restored.db \
  --attachments /private/recovery/originals-restored
```

Wrong keys, tampered inventory/database/files, missing referenced originals, existing targets, dangling symlinks or database sidecars are refused. Restore validates all contents before publishing to the new database/files paths and undoes publication after handled errors. A process killed during restore may leave partial new targets: keep the original bundle, discard those **new recovery targets only**, and restore again to fresh paths. Never point a running app at a restore in progress.

Start a disposable app on a separate loopback port with integrations disabled. Set **both** `TRAVEL_DESK_DB` and `ATTACHMENTS_DIR` to the restored targets and the historical key. Verify cases, quote versions, balances, histories, authenticated traveller reveal and original download. Only then stop all production workers, switch both paths, restart and verify writes/backups. Preserve original configuration for rollback.

Changing `PII_FERNET_KEY` directly is not rotation: the live vault, existing originals, private retry fingerprints and historical bundles depend on it. Current backups reject a changed key ID. If the backup-root path changes after a crash, inspect and remove abandoned `.mom-backup-work-*` directories on the database volume after stopping all backup runners; cleanup only covers the current root’s work directory. Until a dedicated re-encryption migration exists, keep the current key; if moving to a new key, perform a supervised offline migration on a separate database/files copy, verify all decryption and counts, use a **new backup root**, retain the old key for old bundles, then switch while workers are stopped. Private command retries from before rotation may conflict; reconcile saved records rather than resubmit blindly. MultiFernet-style support is a future improvement, not currently installed.

## Reproducible container recovery drill

```sh
docker build --pull --no-cache -t travel-mom-verify:local .
.venv/bin/python scripts/verify_container.py --image travel-mom-verify:local
```

The runner owns labelled disposable containers/volumes and ephemeral loopback ports. It tests non-root execution, read-only root, tmpfs, dropped capabilities, no-new-privileges, signed token access, 100 concurrent synthetic writes, restart persistence, plain SQLite compatibility recovery, and encrypted bundle recovery including authenticated HTTP passport reveal and original download. It deletes only its uniquely labelled resources. This is a local drill, not a production RPO/RTO or long-duration load guarantee.

`scripts/database_backup.py` remains for a **database-only** validated snapshot into a new file. Those snapshots are plaintext and exclude original blobs: use only as a private pre-migration/diagnostic tool, not a complete encrypted backup.

Technical references checked 2026-10-05: [Python SQLite backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup), [SQLite online backup](https://www.sqlite.org/backup.html), [Fernet documentation](https://cryptography.io/en/latest/fernet/).
