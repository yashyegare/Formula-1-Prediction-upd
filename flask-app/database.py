"""
SQLite database layer for F1 season data.

Stores pre-seeded data from Jolpica/Ergast so the Flask API can serve
instant responses without hitting external APIs at runtime.

Schema:
  seasons       — one row per F1 season (year, race count)
  races         — one row per Grand Prix (year, round, name, circuit, country, date, is_sprint, completed)
  drivers       — one row per driver who raced in a given season
  constructors  — one row per constructor (team) active in a season
  results       — finishing order per race (driver, position, fastest_lap)
  standings     — championship standings (driver or constructor, end-of-season)
  users         — registered users (signup/login)
  predictions   — user-submitted season predictions (grids, scoring)
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "f1_data.db")


def get_db_path() -> str:
    return DB_PATH


@contextmanager
def get_connection():
    """Yield a connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            -- F1 season data (seeded from Jolpica)
            CREATE TABLE IF NOT EXISTS seasons (
                year INTEGER PRIMARY KEY,
                race_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS races (
                id TEXT PRIMARY KEY,
                year INTEGER NOT NULL,
                round_num INTEGER NOT NULL,
                name TEXT NOT NULL,
                circuit_id TEXT NOT NULL,
                country TEXT NOT NULL,
                country_code TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL DEFAULT '',
                is_sprint INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (year) REFERENCES seasons(year),
                UNIQUE(year, round_num)
            );

            CREATE TABLE IF NOT EXISTS drivers (
                id TEXT NOT NULL,
                year INTEGER NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                given_name TEXT NOT NULL DEFAULT '',
                family_name TEXT NOT NULL DEFAULT '',
                nationality TEXT NOT NULL DEFAULT '',
                team_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (id, year)
            );

            CREATE TABLE IF NOT EXISTS constructors (
                id TEXT NOT NULL,
                year INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                nationality TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#888888',
                secondary_color TEXT,
                PRIMARY KEY (id, year)
            );

            CREATE TABLE IF NOT EXISTS results (
                year INTEGER NOT NULL,
                round_num INTEGER NOT NULL,
                driver_id TEXT NOT NULL,
                team_id TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL,
                fastest_lap INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (year, round_num, driver_id)
            );

            CREATE TABLE IF NOT EXISTS standings (
                year INTEGER NOT NULL,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                position INTEGER NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (year, entity_id, entity_type)
            );

            CREATE INDEX IF NOT EXISTS idx_races_year ON races(year);
            CREATE INDEX IF NOT EXISTS idx_results_year_round ON results(year, round_num);
            CREATE INDEX IF NOT EXISTS idx_standings_year_type ON standings(year, entity_type);
            CREATE INDEX IF NOT EXISTS idx_drivers_year ON drivers(year);

            -- User accounts
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                avatar_url TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                last_login TEXT
            );

            -- User predictions (one per user per season)
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                -- Grid predictions stored as JSON: {"grids": {"2026_r1": ["verstappen", "norris", ...], ...}}
                grids_json TEXT NOT NULL DEFAULT '{}',
                -- Points system used
                points_system TEXT NOT NULL DEFAULT 'current',
                -- Whether this prediction is locked (no more edits allowed)
                locked INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                -- Accuracy score (computed server-side against real results)
                accuracy_score REAL DEFAULT 0,
                -- Metadata
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, season)
            );

            -- Leaderboard view (computed from predictions + real results)
            -- This is a materialized view, updated when scores are recalculated
            CREATE TABLE IF NOT EXISTS leaderboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                accuracy_score REAL NOT NULL DEFAULT 0,
                races_scored INTEGER NOT NULL DEFAULT 0,
                exact_matches INTEGER NOT NULL DEFAULT 0,
                total_positions INTEGER NOT NULL DEFAULT 0,
                rank INTEGER,
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, season)
            );

            CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id);
            CREATE INDEX IF NOT EXISTS idx_predictions_season ON predictions(season);
            CREATE INDEX IF NOT EXISTS idx_leaderboard_season ON leaderboard(season, accuracy_score DESC);
        """)


# ── F1 Season data queries ───────────────────────────────────────────────

def is_seeded(year: Optional[int] = None) -> bool:
    """Check if a specific year (or all years) has been seeded."""
    with get_connection() as conn:
        if year:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM seasons WHERE year = ?", (year,)
            ).fetchone()
            return row["cnt"] > 0
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM seasons").fetchone()
            return row["cnt"] > 0


def get_seeded_years() -> list[int]:
    """Return sorted list of years that have been seeded."""
    with get_connection() as conn:
        rows = conn.execute("SELECT year FROM seasons ORDER BY year").fetchall()
        return [r["year"] for r in rows]


def get_season_init_data(year: int) -> Optional[dict]:
    """
    Build the /api/init response payload from SQLite.
    Returns None if the year isn't seeded.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM seasons WHERE year = ?", (year,)
        ).fetchone()
        if row["cnt"] == 0:
            return None

        # Schedule
        race_rows = conn.execute(
            "SELECT id, name, round_num, circuit_id, country, country_code, date, is_sprint, completed "
            "FROM races WHERE year = ? ORDER BY round_num", (year,)
        ).fetchall()
        schedule = [
            {
                "id": r["id"], "name": r["name"],
                "isSprint": bool(r["is_sprint"]), "country": r["country"],
                "countryCode": r["country_code"], "order": r["round_num"],
                "completed": bool(r["completed"]), "date": r["date"],
                "round": str(r["round_num"]), "circuitId": r["circuit_id"],
                "trackSlug": r["circuit_id"],
            }
            for r in race_rows
        ]

        # Teams
        team_rows = conn.execute(
            "SELECT id, name, nationality, color, secondary_color "
            "FROM constructors WHERE year = ?", (year,)
        ).fetchall()
        teams = [
            {
                "id": t["id"], "name": t["name"],
                "nationality": t["nationality"], "color": t["color"],
                "secondaryColor": t["secondary_color"],
            }
            for t in team_rows
        ]

        # Drivers
        driver_rows = conn.execute(
            "SELECT id, code, given_name, family_name, nationality, team_id "
            "FROM drivers WHERE year = ?", (year,)
        ).fetchall()
        drivers = [
            {
                "id": d["id"], "code": d["code"],
                "givenName": d["given_name"], "familyName": d["family_name"],
                "nationality": d["nationality"], "team": d["team_id"],
            }
            for d in driver_rows
        ]

        # Race results
        result_rows = conn.execute(
            "SELECT year, round_num, driver_id, team_id, position, fastest_lap "
            "FROM results WHERE year = ? ORDER BY round_num, position", (year,)
        ).fetchall()
        race_results: dict[str, list] = {}
        for r in result_rows:
            key = f"{year}_r{r['round_num']}"
            if key not in race_results:
                race_results[key] = []
            race_results[key].append({
                "driverId": r["driver_id"], "teamId": r["team_id"],
                "position": r["position"], "fastestLap": bool(r["fastest_lap"]),
            })

        # Standings
        driver_standings = [
            {"position": s["position"], "driverId": s["entity_id"], "points": s["points"]}
            for s in conn.execute(
                "SELECT entity_id, position, points FROM standings "
                "WHERE year = ? AND entity_type = 'driver' ORDER BY position", (year,)
            ).fetchall()
        ]
        constructor_standings = [
            {"position": s["position"], "teamId": s["entity_id"], "points": s["points"]}
            for s in conn.execute(
                "SELECT entity_id, position, points FROM standings "
                "WHERE year = ? AND entity_type = 'constructor' ORDER BY position", (year,)
            ).fetchall()
        ]

        return {
            "schedule": schedule, "teams": teams, "drivers": drivers,
            "raceResults": race_results, "driverStandings": driver_standings,
            "constructorStandings": constructor_standings,
        }


def get_circuits(year: int) -> dict:
    """Return {race_id: circuit_id} mapping for a given year."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, circuit_id FROM races WHERE year = ? ORDER BY round_num", (year,)
        ).fetchall()
        return {r["id"]: r["circuit_id"] for r in rows}


# ── User queries ─────────────────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str, display_name: Optional[str] = None) -> int:
    """Create a new user, return user ID."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, display_name) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, display_name or username),
        )
        return cur.lastrowid


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, email, display_name, avatar_url, created_at, last_login "
            "FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, email, password_hash, display_name, created_at "
            "FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, email FROM users WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def update_last_login(user_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,)
        )


# ── Prediction queries ───────────────────────────────────────────────────

def save_prediction(user_id: int, season: int, grids_json: str,
                    points_system: str = "current") -> dict:
    """Create or update a user's prediction for a season."""
    with get_connection() as conn:
        # Upsert
        existing = conn.execute(
            "SELECT id FROM predictions WHERE user_id = ? AND season = ?",
            (user_id, season)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE predictions SET grids_json = ?, points_system = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (grids_json, points_system, existing["id"])
            )
            pred_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO predictions (user_id, season, grids_json, points_system) "
                "VALUES (?, ?, ?, ?)",
                (user_id, season, grids_json, points_system)
            )
            pred_id = cur.lastrowid

        # Read back within the same connection (transaction not yet committed)
        row = conn.execute(
            "SELECT p.*, u.username, u.display_name "
            "FROM predictions p JOIN users u ON p.user_id = u.id "
            "WHERE p.id = ?", (pred_id,)
        ).fetchone()
        return dict(row) if row else None


def get_prediction(pred_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT p.*, u.username, u.display_name "
            "FROM predictions p JOIN users u ON p.user_id = u.id "
            "WHERE p.id = ?", (pred_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_prediction(user_id: int, season: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT p.*, u.username, u.display_name "
            "FROM predictions p JOIN users u ON p.user_id = u.id "
            "WHERE p.user_id = ? AND p.season = ?", (user_id, season)
        ).fetchone()
        return dict(row) if row else None


def lock_prediction(pred_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE predictions SET locked = 1, locked_at = datetime('now') WHERE id = ?",
            (pred_id,)
        )


def get_all_predictions(season: int) -> list[dict]:
    """Get all predictions for a season (for leaderboard computation)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.*, u.username, u.display_name "
            "FROM predictions p JOIN users u ON p.user_id = u.id "
            "WHERE p.season = ? ORDER BY p.accuracy_score DESC", (season,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Leaderboard queries ──────────────────────────────────────────────────

def update_leaderboard(user_id: int, season: int, accuracy_score: float,
                       races_scored: int, exact_matches: int, total_positions: int):
    """Update or insert a leaderboard entry."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO leaderboard (user_id, season, accuracy_score, races_scored, "
            "exact_matches, total_positions, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(user_id, season) DO UPDATE SET "
            "accuracy_score = excluded.accuracy_score, "
            "races_scored = excluded.races_scored, "
            "exact_matches = excluded.exact_matches, "
            "total_positions = excluded.total_positions, "
            "updated_at = datetime('now')",
            (user_id, season, accuracy_score, races_scored, exact_matches, total_positions)
        )
        # Recompute ranks
        conn.execute(
            "UPDATE leaderboard SET rank = sub.rnk FROM ("
            "  SELECT id, ROW_NUMBER() OVER (PARTITION BY season ORDER BY accuracy_score DESC) as rnk "
            "  FROM leaderboard"
            ") sub WHERE leaderboard.id = sub.id AND leaderboard.season = ?",
            (season,)
        )


def get_leaderboard(season: int, limit: int = 50) -> list[dict]:
    """Get the ranked leaderboard for a season."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT l.*, u.username, u.display_name "
            "FROM leaderboard l JOIN users u ON l.user_id = u.id "
            "WHERE l.season = ? AND l.races_scored > 0 "
            "ORDER BY l.accuracy_score DESC LIMIT ?",
            (season, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_leaderboard_stats(season: int) -> dict:
    """Get summary stats for the leaderboard."""
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM leaderboard WHERE season = ? AND races_scored > 0",
            (season,)
        ).fetchone()["cnt"]
        top = conn.execute(
            "SELECT u.display_name, l.accuracy_score FROM leaderboard l "
            "JOIN users u ON l.user_id = u.id "
            "WHERE l.season = ? AND l.races_scored > 0 "
            "ORDER BY l.accuracy_score DESC LIMIT 1",
            (season,)
        ).fetchone()
        return {
            "totalPredictors": total,
            "leader": {"name": top["display_name"], "score": top["accuracy_score"]} if top else None,
        }


# ── Direct-access helpers (used by the seeder) ──────────────────────────

def insert_season(year: int, race_count: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO seasons (year, race_count) VALUES (?, ?)",
            (year, race_count),
        )


def insert_race(race_id: str, year: int, round_num: int, name: str,
                circuit_id: str, country: str, country_code: str,
                date: str, is_sprint: bool, completed: bool):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO races "
            "(id, year, round_num, name, circuit_id, country, country_code, date, is_sprint, completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (race_id, year, round_num, name, circuit_id, country, country_code,
             date, int(is_sprint), int(completed)),
        )


def insert_driver(driver_id: str, year: int, code: str, given_name: str,
                  family_name: str, nationality: str, team_id: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO drivers "
            "(id, year, code, given_name, family_name, nationality, team_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (driver_id, year, code, given_name, family_name, nationality, team_id),
        )


def insert_constructor(constructor_id: str, year: int, name: str,
                       nationality: str, color: str, secondary_color: Optional[str] = None):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO constructors "
            "(id, year, name, nationality, color, secondary_color) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (constructor_id, year, name, nationality, color, secondary_color),
        )


def insert_result(year: int, round_num: int, driver_id: str, team_id: str,
                  position: int, fastest_lap: bool):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results "
            "(year, round_num, driver_id, team_id, position, fastest_lap) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (year, round_num, driver_id, team_id, position, int(fastest_lap)),
        )


def insert_standing(year: int, entity_id: str, entity_type: str,
                    position: int, points: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO standings "
            "(year, entity_id, entity_type, position, points) "
            "VALUES (?, ?, ?, ?, ?)",
            (year, entity_id, entity_type, position, points),
        )
