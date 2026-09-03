"""
Database layer supporting SQLite (local dev) and PostgreSQL (production).

Set DATABASE_URL env var to switch:
  - Not set / empty → SQLite (f1_data.db)
  - postgres://...  → PostgreSQL (Render, Neon, Supabase, etc.)
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Optional

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Connection helpers ──────────────────────────────────────────────────

def _is_pg() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def get_connection():
    """Yield a DB connection. SQLite for local dev, PostgreSQL for prod."""
    if _is_pg():
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "f1_data.db")
        conn = sqlite3.connect(db_path, timeout=10)
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


def _fetchone(conn, sql: str, params=()):
    """Fetch one row, returning a dict-like object for both backends."""
    cur = conn.execute(sql, params)
    if _is_pg():
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    else:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def _fetchall(conn, sql: str, params=()):
    """Fetch all rows as list of dicts."""
    if _is_pg():
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    else:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def _execute(conn, sql: str, params=()):
    """Execute a statement, return cursor for lastrowid / rowcount."""
    if _is_pg():
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    else:
        return conn.execute(sql, params)


def _now_sql() -> str:
    """SQL expression for current timestamp."""
    return "NOW()" if _is_pg() else "datetime('now')"


# ── Schema ─────────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        if _is_pg():
            _init_pg(conn)
        else:
            _init_sqlite(conn)


def _init_sqlite(conn):
    conn.executescript("""
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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT,
            reset_token TEXT,
            reset_token_expires TEXT
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            grids_json TEXT NOT NULL DEFAULT '{}',
            points_system TEXT NOT NULL DEFAULT 'current',
            locked INTEGER NOT NULL DEFAULT 0,
            locked_at TEXT,
            accuracy_score REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, season)
        );
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


def _init_pg(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            year INTEGER PRIMARY KEY,
            race_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
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
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_login TIMESTAMPTZ,
            reset_token TEXT,
            reset_token_expires TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            season INTEGER NOT NULL,
            grids_json TEXT NOT NULL DEFAULT '{}',
            points_system TEXT NOT NULL DEFAULT 'current',
            locked INTEGER NOT NULL DEFAULT 0,
            locked_at TIMESTAMPTZ,
            accuracy_score DOUBLE PRECISION DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, season)
        );
        CREATE TABLE IF NOT EXISTS leaderboard (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            season INTEGER NOT NULL,
            accuracy_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            races_scored INTEGER NOT NULL DEFAULT 0,
            exact_matches INTEGER NOT NULL DEFAULT 0,
            total_positions INTEGER NOT NULL DEFAULT 0,
            rank INTEGER,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, season)
        );
        CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id);
        CREATE INDEX IF NOT EXISTS idx_predictions_season ON predictions(season);
        CREATE INDEX IF NOT EXISTS idx_leaderboard_season ON leaderboard(season, accuracy_score DESC);
    """)
    conn.commit()


# ── Seed check ─────────────────────────────────────────────────────────

def is_seeded(year: Optional[int] = None) -> bool:
    with get_connection() as conn:
        if year:
            row = _fetchone(conn, "SELECT COUNT(*) as cnt FROM seasons WHERE year = %s" if _is_pg() else "SELECT COUNT(*) as cnt FROM seasons WHERE year = ?", (year,))
            return row["cnt"] > 0
        else:
            row = _fetchone(conn, "SELECT COUNT(*) as cnt FROM seasons")
            return row["cnt"] > 0


def get_seeded_years() -> list[int]:
    with get_connection() as conn:
        rows = _fetchall(conn, "SELECT year FROM seasons ORDER BY year")
        return [r["year"] for r in rows]


def get_season_init_data(year: int) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            row = _fetchone(conn, "SELECT COUNT(*) as cnt FROM seasons WHERE year = %s", (year,))
        else:
            row = _fetchone(conn, "SELECT COUNT(*) as cnt FROM seasons WHERE year = ?", (year,))
        if row["cnt"] == 0:
            return None

        # Schedule
        if _is_pg():
            race_rows = _fetchall(conn,
                "SELECT id, name, round_num, circuit_id, country, country_code, date, is_sprint, completed "
                "FROM races WHERE year = %s ORDER BY round_num", (year,))
        else:
            race_rows = _fetchall(conn,
                "SELECT id, name, round_num, circuit_id, country, country_code, date, is_sprint, completed "
                "FROM races WHERE year = ? ORDER BY round_num", (year,))

        schedule = [
            {
                "id": r["id"], "name": r["name"], "order": r["round_num"],
                "round": str(r["round_num"]), "circuitId": r["circuit_id"],
                "country": r["country"], "countryCode": r["country_code"],
                "date": r["date"], "isSprint": bool(r["is_sprint"]),
                "completed": bool(r["completed"]),
            }
            for r in race_rows
        ]

        # Drivers
        if _is_pg():
            driver_rows = _fetchall(conn,
                "SELECT id, code, given_name, family_name, nationality, team_id "
                "FROM drivers WHERE year = %s ORDER BY id", (year,))
        else:
            driver_rows = _fetchall(conn,
                "SELECT id, code, given_name, family_name, nationality, team_id "
                "FROM drivers WHERE year = ? ORDER BY id", (year,))
        drivers = [
            {
                "driverId": d["id"], "code": d["code"],
                "givenName": d["given_name"], "familyName": d["family_name"],
                "nationality": d["nationality"], "teamId": d["team_id"],
            }
            for d in driver_rows
        ]

        # Teams / Constructors
        if _is_pg():
            team_rows = _fetchall(conn,
                "SELECT id, name, nationality, color, secondary_color "
                "FROM constructors WHERE year = %s ORDER BY id", (year,))
        else:
            team_rows = _fetchall(conn,
                "SELECT id, name, nationality, color, secondary_color "
                "FROM constructors WHERE year = ? ORDER BY id", (year,))
        teams = [
            {
                "constructorId": t["id"], "name": t["name"],
                "nationality": t["nationality"], "color": t["color"],
                "secondaryColor": t["secondary_color"],
            }
            for t in team_rows
        ]

        # Race results
        if _is_pg():
            result_rows = _fetchall(conn,
                "SELECT round_num, driver_id, team_id, position, fastest_lap "
                "FROM results WHERE year = %s ORDER BY round_num, position", (year,))
        else:
            result_rows = _fetchall(conn,
                "SELECT round_num, driver_id, team_id, position, fastest_lap "
                "FROM results WHERE year = ? ORDER BY round_num, position", (year,))
        race_results = {}
        for r in result_rows:
            rnd = str(r["round_num"])
            if rnd not in race_results:
                race_results[rnd] = []
            race_results[rnd].append({
                "driverId": r["driver_id"], "teamId": r["team_id"],
                "position": r["position"], "fastestLap": bool(r["fastest_lap"]),
            })

        # Standings
        if _is_pg():
            standing_rows = _fetchall(conn,
                "SELECT entity_id, entity_type, position, points "
                "FROM standings WHERE year = %s ORDER BY entity_type, position", (year,))
        else:
            standing_rows = _fetchall(conn,
                "SELECT entity_id, entity_type, position, points "
                "FROM standings WHERE year = ? ORDER BY entity_type, position", (year,))
        driver_standings = []
        constructor_standings = []
        for s in standing_rows:
            entry = {
                "entityId": s["entity_id"], "position": s["position"],
                "points": s["points"],
            }
            if s["entity_type"] == "driver":
                driver_standings.append(entry)
            else:
                constructor_standings.append(entry)

        return {
            "schedule": schedule,
            "teams": teams,
            "drivers": drivers,
            "raceResults": race_results,
            "driverStandings": driver_standings,
            "constructorStandings": constructor_standings,
        }


# ── Circuit queries ────────────────────────────────────────────────────

def get_circuits(year: Optional[int] = None) -> dict:
    """Return {race_id: circuit_id} mapping, or all circuits if no year."""
    with get_connection() as conn:
        if year:
            if _is_pg():
                rows = _fetchall(conn,
                    "SELECT id, circuit_id FROM races WHERE year = %s ORDER BY round_num", (year,))
            else:
                rows = _fetchall(conn,
                    "SELECT id, circuit_id FROM races WHERE year = ? ORDER BY round_num", (year,))
            return {r["id"]: r["circuit_id"] for r in rows}
        else:
            rows = _fetchall(conn,
                "SELECT DISTINCT circuit_id, country FROM races ORDER BY country")
            return [{"id": r["circuit_id"], "country": r["country"]} for r in rows]


def get_circuit_data(circuit_id: str, year: Optional[int] = None) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            races = _fetchall(conn,
                "SELECT id, name, year, round_num, country, country_code, date, is_sprint, completed "
                "FROM races WHERE circuit_id = %s" + (" AND year = %s" if year else "") +
                " ORDER BY year DESC, round_num",
                (circuit_id,) + ((year,) if year else ()))
        else:
            races = _fetchall(conn,
                "SELECT id, name, year, round_num, country, country_code, date, is_sprint, completed "
                "FROM races WHERE circuit_id = ?" + (" AND year = ?" if year else "") +
                " ORDER BY year DESC, round_num",
                (circuit_id,) + ((year,) if year else ()))
        if not races:
            return None
        return {"circuitId": circuit_id, "races": races}


# ── User queries ───────────────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str, display_name: str = "") -> int:
    with get_connection() as conn:
        if _is_pg():
            cur = _execute(conn,
                "INSERT INTO users (username, email, password_hash, display_name) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (username, email, password_hash, display_name))
            return cur.fetchone()[0]
        else:
            cur = _execute(conn,
                "INSERT INTO users (username, email, password_hash, display_name) "
                "VALUES (?, ?, ?, ?)",
                (username, email, password_hash, display_name))
            return cur.lastrowid


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, avatar_url, created_at "
                "FROM users WHERE id = %s", (user_id,))
        else:
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, avatar_url, created_at "
                "FROM users WHERE id = ?", (user_id,))


def get_user_by_username(username: str) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, created_at "
                "FROM users WHERE username = %s", (username,))
        else:
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, created_at "
                "FROM users WHERE username = ?", (username,))


def get_user_by_email(email: str) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, created_at "
                "FROM users WHERE email = %s", (email.lower().strip(),))
        else:
            return _fetchone(conn,
                "SELECT id, username, email, password_hash, display_name, created_at "
                "FROM users WHERE email = ?", (email.lower().strip(),))


def get_user_by_reset_token(token: str) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT id, username, email, display_name FROM users "
                "WHERE reset_token = %s AND reset_token_expires > NOW()", (token,))
        else:
            return _fetchone(conn,
                "SELECT id, username, email, display_name FROM users "
                "WHERE reset_token = ? AND reset_token_expires > datetime('now')", (token,))


def set_reset_token(user_id: int, token: str, expires: str):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "UPDATE users SET reset_token = %s, reset_token_expires = %s WHERE id = %s",
                (token, expires, user_id))
        else:
            _execute(conn,
                "UPDATE users SET reset_token = ?, reset_token_expires = ? WHERE id = ?",
                (token, expires, user_id))


def reset_password(user_id: int, new_password_hash: str):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "UPDATE users SET password_hash = %s, reset_token = NULL, reset_token_expires = NULL WHERE id = %s",
                (new_password_hash, user_id))
        else:
            _execute(conn,
                "UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expires = NULL WHERE id = ?",
                (new_password_hash, user_id))


def update_user_profile(user_id: int, display_name: str = None, avatar_url: str = None):
    with get_connection() as conn:
        sets, vals = [], []
        if display_name is not None:
            ph = "%s" if _is_pg() else "?"
            sets.append(f"display_name = {ph}")
            vals.append(display_name)
        if avatar_url is not None:
            ph = "%s" if _is_pg() else "?"
            sets.append(f"avatar_url = {ph}")
            vals.append(avatar_url)
        if not sets:
            return
        vals.append(user_id)
        ph = "%s" if _is_pg() else "?"
        _execute(conn, f"UPDATE users SET {', '.join(sets)} WHERE id = {ph}", vals)


def delete_user(user_id: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn, "DELETE FROM predictions WHERE user_id = %s", (user_id,))
            _execute(conn, "DELETE FROM leaderboard WHERE user_id = %s", (user_id,))
            _execute(conn, "DELETE FROM users WHERE id = %s", (user_id,))
        else:
            _execute(conn, "DELETE FROM predictions WHERE user_id = ?", (user_id,))
            _execute(conn, "DELETE FROM leaderboard WHERE user_id = ?", (user_id,))
            _execute(conn, "DELETE FROM users WHERE id = ?", (user_id,))


def delete_user_by_email(email: str) -> bool:
    with get_connection() as conn:
        if _is_pg():
            cur = _execute(conn, "DELETE FROM users WHERE email = %s", (email.lower().strip(),))
            return cur.rowcount > 0
        else:
            cur = _execute(conn, "DELETE FROM users WHERE email = ?", (email.lower().strip(),))
            return cur.rowcount > 0


def update_last_login(user_id: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn, "UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,))
        else:
            _execute(conn, "UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))


# ── Prediction queries ─────────────────────────────────────────────────

def save_prediction(user_id: int, season: int, grids_json: str,
                    points_system: str = "current") -> dict:
    with get_connection() as conn:
        if _is_pg():
            existing = _fetchone(conn,
                "SELECT id FROM predictions WHERE user_id = %s AND season = %s",
                (user_id, season))
            if existing:
                _execute(conn,
                    "UPDATE predictions SET grids_json = %s, points_system = %s, "
                    "updated_at = NOW() WHERE id = %s",
                    (grids_json, points_system, existing["id"]))
                return {"id": existing["id"], "action": "updated"}
            else:
                cur = _execute(conn,
                    "INSERT INTO predictions (user_id, season, grids_json, points_system) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (user_id, season, grids_json, points_system))
                return {"id": cur.fetchone()[0], "action": "created"}
        else:
            existing = _fetchone(conn,
                "SELECT id FROM predictions WHERE user_id = ? AND season = ?",
                (user_id, season))
            if existing:
                _execute(conn,
                    "UPDATE predictions SET grids_json = ?, points_system = ?, "
                    "updated_at = datetime('now') WHERE id = ?",
                    (grids_json, points_system, existing["id"]))
                return {"id": existing["id"], "action": "updated"}
            else:
                cur = _execute(conn,
                    "INSERT INTO predictions (user_id, season, grids_json, points_system) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, season, grids_json, points_system))
                return {"id": cur.lastrowid, "action": "created"}


def load_prediction(user_id: int, season: int) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT id, grids_json, points_system, locked, locked_at, accuracy_score, "
                "created_at, updated_at FROM predictions WHERE user_id = %s AND season = %s",
                (user_id, season))
        else:
            return _fetchone(conn,
                "SELECT id, grids_json, points_system, locked, locked_at, accuracy_score, "
                "created_at, updated_at FROM predictions WHERE user_id = ? AND season = ?",
                (user_id, season))


def get_prediction_history(user_id: int) -> list[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchall(conn,
                "SELECT id, season, points_system, locked, accuracy_score, "
                "created_at, updated_at FROM predictions WHERE user_id = %s ORDER BY season DESC",
                (user_id,))
        else:
            return _fetchall(conn,
                "SELECT id, season, points_system, locked, accuracy_score, "
                "created_at, updated_at FROM predictions WHERE user_id = ? ORDER BY season DESC",
                (user_id,))


def delete_prediction(user_id: int, season: int) -> bool:
    with get_connection() as conn:
        if _is_pg():
            cur = _execute(conn,
                "DELETE FROM predictions WHERE user_id = %s AND season = %s",
                (user_id, season))
            return cur.rowcount > 0
        else:
            cur = _execute(conn,
                "DELETE FROM predictions WHERE user_id = ? AND season = ?",
                (user_id, season))
            return cur.rowcount > 0


def delete_all_predictions(user_id: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn, "DELETE FROM predictions WHERE user_id = %s", (user_id,))
        else:
            _execute(conn, "DELETE FROM predictions WHERE user_id = ?", (user_id,))


# ── Locked predictions ─────────────────────────────────────────────────

def lock_prediction(user_id: int, season: int, race_id: str, positions: list) -> dict:
    with get_connection() as conn:
        pred = load_prediction(user_id, season)
        if not pred:
            return {"error": "No prediction found"}
        if pred.get("locked"):
            return {"error": "Prediction is already locked"}

        import json
        grids = json.loads(pred["grids_json"]) if isinstance(pred["grids_json"], str) else pred["grids_json"]
        grids.setdefault("lockedRaces", {})
        grids["lockedRaces"][race_id] = positions

        if _is_pg():
            _execute(conn,
                "UPDATE predictions SET grids_json = %s, locked_at = NOW(), updated_at = NOW() "
                "WHERE user_id = %s AND season = %s",
                (json.dumps(grids), user_id, season))
        else:
            _execute(conn,
                "UPDATE predictions SET grids_json = ?, locked_at = datetime('now'), updated_at = datetime('now') "
                "WHERE user_id = ? AND season = ?",
                (json.dumps(grids), user_id, season))
        return {"ok": True}


def unlock_prediction(user_id: int, season: int, race_id: str) -> dict:
    with get_connection() as conn:
        pred = load_prediction(user_id, season)
        if not pred:
            return {"error": "No prediction found"}

        import json
        grids = json.loads(pred["grids_json"]) if isinstance(pred["grids_json"], str) else pred["grids_json"]
        grids.get("lockedRaces", {}).pop(race_id, None)

        if _is_pg():
            _execute(conn,
                "UPDATE predictions SET grids_json = %s, updated_at = NOW() "
                "WHERE user_id = %s AND season = %s",
                (json.dumps(grids), user_id, season))
        else:
            _execute(conn,
                "UPDATE predictions SET grids_json = ?, updated_at = datetime('now') "
                "WHERE user_id = ? AND season = ?",
                (json.dumps(grids), user_id, season))
        return {"ok": True}


def get_locked_predictions(user_id: int, season: int) -> dict:
    pred = load_prediction(user_id, season)
    if not pred:
        return {"lockedRaces": {}}
    import json
    grids = json.loads(pred["grids_json"]) if isinstance(pred["grids_json"], str) else pred["grids_json"]
    return {"lockedRaces": grids.get("lockedRaces", {})}


# ── Additional prediction queries ────────────────────────────────────────

def get_circuits_for_year(year: int) -> dict:
    """Return {race_id: circuit_id} mapping for a given year."""
    with get_connection() as conn:
        if _is_pg():
            rows = _fetchall(conn,
                "SELECT id, circuit_id FROM races WHERE year = %s ORDER BY round_num", (year,))
        else:
            rows = _fetchall(conn,
                "SELECT id, circuit_id FROM races WHERE year = ? ORDER BY round_num", (year,))
        return {r["id"]: r["circuit_id"] for r in rows}


def get_prediction_by_id(pred_id: int) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.id = %s", (pred_id,))
        else:
            return _fetchone(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.id = ?", (pred_id,))


def get_user_prediction(user_id: int, season: int) -> Optional[dict]:
    with get_connection() as conn:
        if _is_pg():
            return _fetchone(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.user_id = %s AND p.season = %s", (user_id, season))
        else:
            return _fetchone(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.user_id = ? AND p.season = ?", (user_id, season))


def lock_prediction_by_id(pred_id: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "UPDATE predictions SET locked = 1, locked_at = NOW() WHERE id = %s", (pred_id,))
        else:
            _execute(conn,
                "UPDATE predictions SET locked = 1, locked_at = datetime('now') WHERE id = ?", (pred_id,))


def get_all_predictions(season: int) -> list[dict]:
    """Get all predictions for a season (for leaderboard computation)."""
    with get_connection() as conn:
        if _is_pg():
            return _fetchall(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.season = %s ORDER BY p.accuracy_score DESC", (season,))
        else:
            return _fetchall(conn,
                "SELECT p.*, u.username, u.display_name "
                "FROM predictions p JOIN users u ON p.user_id = u.id "
                "WHERE p.season = ? ORDER BY p.accuracy_score DESC", (season,))


# ── Leaderboard queries ──────────────────────────────────────────────────

def update_leaderboard(user_id: int, season: int, accuracy_score: float,
                       races_scored: int, exact_matches: int, total_positions: int):
    """Update or insert a leaderboard entry."""
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO leaderboard (user_id, season, accuracy_score, races_scored, "
                "exact_matches, total_positions, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT(user_id, season) DO UPDATE SET "
                "accuracy_score = EXCLUDED.accuracy_score, "
                "races_scored = EXCLUDED.races_scored, "
                "exact_matches = EXCLUDED.exact_matches, "
                "total_positions = EXCLUDED.total_positions, "
                "updated_at = NOW()",
                (user_id, season, accuracy_score, races_scored, exact_matches, total_positions))
        else:
            _execute(conn,
                "INSERT INTO leaderboard (user_id, season, accuracy_score, races_scored, "
                "exact_matches, total_positions, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(user_id, season) DO UPDATE SET "
                "accuracy_score = excluded.accuracy_score, "
                "races_scored = excluded.races_scored, "
                "exact_matches = excluded.exact_matches, "
                "total_positions = excluded.total_positions, "
                "updated_at = datetime('now')",
                (user_id, season, accuracy_score, races_scored, exact_matches, total_positions))


def get_leaderboard(season: int, limit: int = 50) -> list[dict]:
    """Get the ranked leaderboard for a season."""
    with get_connection() as conn:
        if _is_pg():
            return _fetchall(conn,
                "SELECT l.*, u.username, u.display_name "
                "FROM leaderboard l JOIN users u ON l.user_id = u.id "
                "WHERE l.season = %s AND l.races_scored > 0 "
                "ORDER BY l.accuracy_score DESC LIMIT %s",
                (season, limit))
        else:
            return _fetchall(conn,
                "SELECT l.*, u.username, u.display_name "
                "FROM leaderboard l JOIN users u ON l.user_id = u.id "
                "WHERE l.season = ? AND l.races_scored > 0 "
                "ORDER BY l.accuracy_score DESC LIMIT ?",
                (season, limit))


def get_leaderboard_stats(season: int) -> dict:
    """Get summary stats for the leaderboard."""
    with get_connection() as conn:
        if _is_pg():
            total = _fetchone(conn,
                "SELECT COUNT(*) as cnt FROM leaderboard WHERE season = %s AND races_scored > 0",
                (season,))["cnt"]
            top = _fetchone(conn,
                "SELECT u.display_name, l.accuracy_score FROM leaderboard l "
                "JOIN users u ON l.user_id = u.id "
                "WHERE l.season = %s AND l.races_scored > 0 "
                "ORDER BY l.accuracy_score DESC LIMIT 1",
                (season,))
        else:
            total = _fetchone(conn,
                "SELECT COUNT(*) as cnt FROM leaderboard WHERE season = ? AND races_scored > 0",
                (season,))["cnt"]
            top = _fetchone(conn,
                "SELECT u.display_name, l.accuracy_score FROM leaderboard l "
                "JOIN users u ON l.user_id = u.id "
                "WHERE l.season = ? AND l.races_scored > 0 "
                "ORDER BY l.accuracy_score DESC LIMIT 1",
                (season,))
        return {
            "totalPredictors": total,
            "leader": {"name": top["display_name"], "score": top["accuracy_score"]} if top else None,
        }


# ── Direct-access helpers (used by the seeder) ──────────────────────────

def insert_season(year: int, race_count: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO seasons (year, race_count) VALUES (%s, %s) "
                "ON CONFLICT (year) DO UPDATE SET race_count = EXCLUDED.race_count",
                (year, race_count))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO seasons (year, race_count) VALUES (?, ?)",
                (year, race_count))


def insert_race(race_id: str, year: int, round_num: int, name: str,
                circuit_id: str, country: str, country_code: str,
                date: str, is_sprint: bool, completed: bool):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO races (id, year, round_num, name, circuit_id, country, "
                "country_code, date, is_sprint, completed) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                (race_id, year, round_num, name, circuit_id, country,
                 country_code, date, int(is_sprint), int(completed)))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO races "
                "(id, year, round_num, name, circuit_id, country, country_code, date, is_sprint, completed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (race_id, year, round_num, name, circuit_id, country,
                 country_code, date, int(is_sprint), int(completed)))


def insert_driver(driver_id: str, year: int, code: str, given_name: str,
                  family_name: str, nationality: str, team_id: str):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO drivers (id, year, code, given_name, family_name, nationality, team_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id, year) DO NOTHING",
                (driver_id, year, code, given_name, family_name, nationality, team_id))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO drivers "
                "(id, year, code, given_name, family_name, nationality, team_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (driver_id, year, code, given_name, family_name, nationality, team_id))


def insert_constructor(constructor_id: str, year: int, name: str,
                       nationality: str, color: str, secondary_color: Optional[str] = None):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO constructors (id, year, name, nationality, color, secondary_color) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id, year) DO NOTHING",
                (constructor_id, year, name, nationality, color, secondary_color))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO constructors "
                "(id, year, name, nationality, color, secondary_color) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (constructor_id, year, name, nationality, color, secondary_color))


def insert_result(year: int, round_num: int, driver_id: str, team_id: str,
                  position: int, fastest_lap: bool):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO results (year, round_num, driver_id, team_id, position, fastest_lap) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (year, round_num, driver_id) DO NOTHING",
                (year, round_num, driver_id, team_id, position, int(fastest_lap)))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO results "
                "(year, round_num, driver_id, team_id, position, fastest_lap) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (year, round_num, driver_id, team_id, position, int(fastest_lap)))


def insert_standing(year: int, entity_id: str, entity_type: str,
                    position: int, points: int):
    with get_connection() as conn:
        if _is_pg():
            _execute(conn,
                "INSERT INTO standings (year, entity_id, entity_type, position, points) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (year, entity_id, entity_type) DO NOTHING",
                (year, entity_id, entity_type, position, points))
        else:
            _execute(conn,
                "INSERT OR REPLACE INTO standings "
                "(year, entity_id, entity_type, position, points) "
                "VALUES (?, ?, ?, ?, ?)",
                (year, entity_id, entity_type, position, points))
