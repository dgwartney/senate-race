"""Merge a backed-up snapshot database into the live one, after a deploy wiped it.

Usage (on the server): python deploy/restore_snapshots.py /tmp/backup.db [data/snapshots.db]

The store reads the newest row by id, so the backup's rows are written first and the rows
the new server has saved since it started go after them: anything fetched after the
deploy stays the latest. Runs in one transaction while the app keeps running.
"""
import sqlite3
import sys

TABLES = {"snapshots": "kind, fetched_at, payload_hash, payload",
          "attempts": "kind, at, ok, error, duration_ms"}


def restore(backup: str, live: str) -> None:
    """Rewrite each table in ``live`` as backup rows followed by its own rows, both in id order."""
    db = sqlite3.connect(live, timeout=30)
    db.execute("ATTACH DATABASE ? AS b", (backup,))
    with db:
        for table, cols in TABLES.items():
            rows = db.execute(f"SELECT {cols} FROM b.{table} ORDER BY id").fetchall()
            rows += db.execute(f"SELECT {cols} FROM main.{table} ORDER BY id").fetchall()
            db.execute(f"DELETE FROM main.{table}")
            db.executemany(f"INSERT INTO main.{table} ({cols}) VALUES ({', '.join('?' * len(cols.split(',')))})",
                           rows)
    for table in TABLES:
        print(table, db.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0], "rows")
    db.close()


if __name__ == "__main__":
    restore(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/snapshots.db")
