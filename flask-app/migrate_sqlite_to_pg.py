#!/usr/bin/env python3
"""
One-time bulk migration: copy the local SQLite F1 dataset into PostgreSQL.

Why this exists: with DATABASE_URL set, seed_data.py opens a fresh SSL
connection to Postgres for EVERY insert (get_connection() per row), which
makes a full seed take hours. This script copies the already-complete
local SQLite database over a single connection in one transaction —
seconds instead of hours.

Usage (PowerShell):
    cd flask-app
    $env:DATABASE_URL = "<External Database URL>"   # the host ending in -a
    python migrate_sqlite_to_pg.py

Idempotent: rows that already exist are skipped (ON CONFLICT DO NOTHING),
so it is safe to run after a partial seed or to re-run any time.
"""

import os
import sqlite3
import sys

# ── Resolve paths & connection ──────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    sys.exit(
        "ERROR: DATABASE_URL is not set.\n"
        "Set it first (PowerShell):\n"
        '  $env:DATABASE_URL = "<External Database URL>"'
    )

SQLITE_PATH = os.environ.get("F1_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "f1_data.db"
)
if not os.path.exists(SQLITE_PATH):
    sys.exit(f"ERROR: SQLite source not found at {SQLITE_PATH}")

# ── Tables to copy (full column lists, created_at left to PG defaults) ──

TABLES = {
    "seasons": ["year", "race_count"],
    "races": ["id", "year", "round_num", "name", "circuit_id", "country",
              "country_code", "date", "is_sprint", "completed"],
    "drivers": ["id", "year", "code", "given_name", "family_name",
                "nationality", "team_id"],
    "constructors": ["id", "year", "name", "nationality", "color",
                     "secondary_color"],
    "results": ["year", "round_num", "driver_id", "team_id", "position",
                "fastest_lap"],
    "standings": ["year", "entity_id", "entity_type", "position", "points"],
}


def main():
    import psycopg2
    import psycopg2.extras

    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    print(f"Source : {SQLITE_PATH}")
    print(f"Target : {DATABASE_URL.split('@')[-1]}")  # host only, no creds
    print()

    # Make sure the PG schema exists before copying
    from database import init_db
    init_db()

    pg = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        cur = pg.cursor()
        # Start from a clean slate for season data so counts are exact even
        # after partial seeds with different data (idempotent outcome).
        print("Clearing existing season data (users/predictions kept)...")
        for table in ["standings", "results", "drivers", "constructors",
                      "races", "seasons"]:
            cur.execute(f"DELETE FROM {table}")
        print("Copying (single connection, single transaction)...")

        total = 0
        for table, cols in TABLES.items():
            rows = src.execute(
                f"SELECT {', '.join(cols)} FROM {table}"
            ).fetchall()
            values = [tuple(r) for r in rows]
            if values:
                psycopg2.extras.execute_values(
                    cur,
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
                    f"ON CONFLICT DO NOTHING",
                    values,
                    page_size=1000,
                )
            print(f"  {table:14s} {len(values):>6,} rows")
            total += len(values)

        pg.commit()
        print(f"\nDone — {total:,} rows migrated.")

        # Verify against what Postgres actually has
        print("\nVerification (Postgres counts):")
        ok = True
        for table in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            print(f"  {table:14s} {n:>6,}")
        cur.execute("SELECT COUNT(*) FROM seasons")
        if cur.fetchone()[0] != 46:
            ok = False
            print("\nWARNING: expected 46 seasons — check output above.")
        if ok:
            print("\nAll expected data present. /health should now report "
                  "\"seeded\": true.")
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()
        src.close()


if __name__ == "__main__":
    main()
