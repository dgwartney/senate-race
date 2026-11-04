#!/usr/bin/env bash
# Back up or restore the live snapshot database around a deploy. See deploy/RUNBOOK.md.
#
#   deploy/snapshots.sh backup    # copy the live database to backups/snapshots-latest.db
#   deploy/snapshots.sh restore   # merge that copy into the (new) live database
set -euo pipefail

APP="${FLY_APP:-senate-race-tracker}"
LOCAL="${BACKUP_FILE:-backups/snapshots-latest.db}"
REMOTE_DB="data/snapshots.db"
REMOTE_TMP="/tmp/snapshots-backup.db"
cd "$(dirname "$0")/.."

counts() {  # kind, rows, newest fetch
  echo "snapshots per kind:"
  sqlite3 "$1" "select '  ' || kind, count(*), max(fetched_at) from snapshots group by kind;"
}

case "${1:-}" in
  backup)
    # SQLite's backup API gives a consistent copy while the app keeps writing (WAL mode).
    fly ssh console -a "$APP" -C "python -c \"import sqlite3; s=sqlite3.connect('$REMOTE_DB'); d=sqlite3.connect('$REMOTE_TMP'); s.backup(d); d.close()\""
    mkdir -p "$(dirname "$LOCAL")"
    rm -f "$LOCAL"
    fly ssh sftp get -a "$APP" "$REMOTE_TMP" "$LOCAL"
    [ "$(sqlite3 "$LOCAL" 'pragma integrity_check;')" = ok ] || { echo "backup failed integrity check" >&2; exit 1; }
    cp "$LOCAL" "backups/snapshots-$(date +%Y%m%d-%H%M%S).db"
    counts "$LOCAL"
    ;;
  restore)
    [ -f "$LOCAL" ] || { echo "no backup at $LOCAL; run '$0 backup' first" >&2; exit 1; }
    # deploy/ is not in the image, so the merge script travels with the backup.
    fly ssh console -a "$APP" -C "rm -f /tmp/restore.db /tmp/restore_snapshots.py"
    fly ssh sftp put -a "$APP" "$LOCAL" /tmp/restore.db
    fly ssh sftp put -a "$APP" deploy/restore_snapshots.py /tmp/restore_snapshots.py
    fly ssh console -a "$APP" -C "python /tmp/restore_snapshots.py /tmp/restore.db $REMOTE_DB"
    ;;
  *)
    echo "usage: $0 backup|restore" >&2
    exit 2
    ;;
esac
