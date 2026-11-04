# Runbook: deploying during the count

The results database (`data/snapshots.db`) lives on the Fly machine's temporary disk. Every
`fly deploy` or restart erases it. Until it's restored, the page has no race results unless
civicAPI answers, and the lead-over-the-night chart starts over. Deploy during the count only
to fix something, and always wrap the deploy in a backup and a restore.

Run every command from the project root. You need the `fly` CLI (logged in) and `sqlite3`.

## Steps

1. **Back up** the live database:

   ```bash
   deploy/snapshots.sh backup
   ```

   This writes `backups/snapshots-latest.db` plus a timestamped copy, checks it, and prints
   the number of saved updates per kind. Take the backup immediately before deploying, so
   little is lost in between.

2. **Deploy:**

   ```bash
   fly deploy --remote-only
   ```

   Wait for "Visit your newly deployed app". The new machine starts with an empty database.

3. **Restore** straight away:

   ```bash
   deploy/snapshots.sh restore
   ```

   This uploads the backup and `deploy/restore_snapshots.py`, then merges them into the
   live database. The backup's rows go first, and anything the new server has already
   fetched goes after them, so it stays the latest. The command prints the row counts.

4. **Check** the live site (your custom domain, or `https://<app>.fly.dev`):

   - The race results are back, not "Waiting for the first results update" or "Could not
     load results".
   - The time on any yellow "Latest update failed" note matches the last good update
     before the deploy.
   - Ohio's and Texas's details say "Counts from … Secretary of State".

## Checking freshness without deploying

When did the last results update succeed, and what failed since?

```bash
fly ssh console -a "${FLY_APP:-senate-race-tracker}" -C "python -c \"
import sqlite3; c=sqlite3.connect('data/snapshots.db')
print('last ok races:', c.execute(\\\"select max(at) from attempts where kind='races' and ok=1\\\").fetchone())
for r in c.execute('select kind, at, ok, substr(error,1,70) from attempts order by id desc limit 10'): print(r)\""
```

Times are UTC (ET + 5 hours).

## Per-state sources

`sources.toml` sets each state's preferred results source. `source = "official"` uses the
state's own feed from `src/officials.py`, which must also be listed in `OFFICIAL_FEEDS` in
`fly.toml`. Every other state uses civicAPI. A state falls back to civicAPI on its own if its
feed fails, so a state feed outage needs no action.

## If something goes wrong

- **The restore printed an error:** the backup is still on disk. Fix the cause and rerun
  `deploy/snapshots.sh restore`. The merge runs in a single transaction, so a failed run
  leaves the database unchanged. Don't rerun a restore that succeeded: it would add the backup's
  history a second time.
- **The new build is broken:** roll back with `fly releases -a "${FLY_APP:-senate-race-tracker}"` and
  `fly deploy --image <previous image>`, then restore again.
- **`fly ssh` hangs:** check that the machine is running with `fly status -a "${FLY_APP:-senate-race-tracker}"`.
