"""Copy only public season data to a fresh PostgreSQL database.

Never deletes rows or copies users from the shipped development SQLite file.
Restored or previously seeded databases are refused, without modifying data.
"""
import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from database import init_db


TABLES = {
    "seasons": ["year", "race_count"],
    "races": ["id", "year", "round_num", "name", "circuit_id", "country",
              "country_code", "date", "is_sprint", "completed"],
    "drivers": ["id", "year", "code", "given_name", "family_name",
                "nationality", "team_id"],
    "constructors": ["id", "year", "name", "nationality", "color", "secondary_color"],
    "results": ["year", "round_num", "driver_id", "team_id", "position", "fastest_lap"],
    "standings": ["year", "entity_id", "entity_type", "position", "points"],
}


def main():
    source = Path(__file__).with_name("f1_data.db")
    # mode=ro prevents accidentally creating an empty source database.
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as sqlite:
        data = {table: sqlite.execute(
            f"SELECT {', '.join(cols)} FROM {table}"
        ).fetchall() for table, cols in TABLES.items()}
    if any(not rows for rows in data.values()):
        raise SystemExit("Source season data is incomplete; no data copied.")

    init_db()
    with psycopg2.connect(os.environ["DATABASE_URL"]) as pg:
        with pg.cursor() as cur:
            # Lock before checking, so concurrent writers cannot race the check.
            cur.execute("LOCK TABLE " + ", ".join(TABLES) + " IN EXCLUSIVE MODE")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                if cur.fetchone()[0]:
                    raise SystemExit("Target already contains season data; no data copied.")
            for table, cols in TABLES.items():
                execute_values(cur, f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s",
                               data[table], page_size=1000)
                print(f"{table}: {len(data[table])} rows")
    print("Public season data copied. No user accounts were imported.")


if __name__ == "__main__":
    main()
