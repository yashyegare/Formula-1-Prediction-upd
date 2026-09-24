-- ============================================================================
-- canonical_schema.sql — the F1 Data Platform's canonical model (Phase 2)
--
-- Design decisions (each one is a contract, not a preference):
--
-- 1. Natural keys over surrogate IDs. (year, round) identifies a race,
--    (year, round, driverId) identifies an entry — the exact keys every
--    existing artifact (cleaned_data.csv, error_decomposition.py,
--    backtest_wf.py) already joins on. The Phase-1 key-collision bug
--    (quali lookup keyed without year) is structurally impossible here:
--    every fact table carries year+round, and PRIMARY KEYs enforce it.
-- 2. SQLite STRICT tables + real types + CHECKs + FOREIGN KEYs. SQLite
--    keeps this runnable everywhere (the repo is CSV-based, no warehouse
--    exists yet); STRICT/CHECK/FK give it warehouse-grade hygiene. Every
--    table maps to PostgreSQL unchanged (integer/text/real + PERCENTILE
--    rewrites), so the migration path stays open.
-- 3. status as a first-class dimension. Phase 1's blocker: 2026 Jolpica
--    ships generic statuses ("Retired"), so cause sub-classification
--    silently degrades. Facts carry status_id + is_dnf + dnf_cause; the
--    taxonomy lives in ONE dimension table, so a richer future feed
--    re-classifies without touching any consumer.
-- 4. Views, not copies. The decomposition evidence (lap-level field
--    medians, slow-lap flags, running-order gains, point-in-time
--    standings) is computed in SQL over the facts — a single source of
--    truth whose contracts match the pandas implementations the tests
--    already pin.
--
-- Lineage: every row is loaded from datasets/*.csv by build_canonical.py,
-- which stamps build_manifest (source row counts, canonical row counts,
-- per-table deltas, git SHA). CI byte-compares the CSV-derived manifest
-- against the committed one — the same drift-guard contract the ML
-- pipeline already applies to cleaned_data.csv and current_roster.json.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ── Dimensions ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_driver (
    driverId     TEXT PRIMARY KEY,
    driverRef    TEXT NOT NULL,
    code         TEXT,
    forename     TEXT NOT NULL,
    surname      TEXT NOT NULL,
    dob          TEXT,
    nationality  TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS dim_constructor (
    constructorId TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    nationality   TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS dim_circuit (
    circuitId TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    location  TEXT,
    country   TEXT,
    lat       REAL,
    lng       REAL
) STRICT;

-- The DNF taxonomy as a dimension: status text -> is_dnf + cause class.
-- Reuses build_training_data's MECHANICAL_/DRIVER_ERROR_ sets (pinned by
-- tests); a richer future feed adds rows or flips dnf_cause here only.
CREATE TABLE IF NOT EXISTS dim_status (
    statusId  INTEGER PRIMARY KEY,
    status    TEXT NOT NULL,
    is_dnf    INTEGER NOT NULL CHECK (is_dnf IN (0, 1)),
    dnf_cause TEXT CHECK (dnf_cause IS NULL OR dnf_cause IN ('mech', 'driver', 'other'))
) STRICT;

-- ── Facts ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fact_race (
    year       INTEGER NOT NULL CHECK (year BETWEEN 1950 AND 2100),
    round      INTEGER NOT NULL CHECK (round >= 1),
    circuitId  TEXT NOT NULL REFERENCES dim_circuit(circuitId),
    name       TEXT NOT NULL,
    date       TEXT,
    time       TEXT,
    PRIMARY KEY (year, round)
) STRICT;

CREATE TABLE IF NOT EXISTS fact_quali_entry (
    year           INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    driverId       TEXT NOT NULL REFERENCES dim_driver(driverId),
    constructorId  TEXT NOT NULL REFERENCES dim_constructor(constructorId),
    position       INTEGER CHECK (position IS NULL OR position >= 1),
    q1_ms          REAL,
    q2_ms          REAL,
    q3_ms          REAL,
    gap_to_pole_s  REAL,
    PRIMARY KEY (year, round, driverId),
    FOREIGN KEY (year, round) REFERENCES fact_race(year, round)
) STRICT;

CREATE TABLE IF NOT EXISTS fact_race_entry (
    year           INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    driverId       TEXT NOT NULL REFERENCES dim_driver(driverId),
    constructorId  TEXT NOT NULL REFERENCES dim_constructor(constructorId),
    grid           INTEGER CHECK (grid IS NULL OR grid >= 0),
    position       INTEGER CHECK (position IS NULL OR position >= 0),
    positionOrder  INTEGER CHECK (positionOrder IS NULL OR positionOrder >= 1),
    points         REAL NOT NULL CHECK (points >= 0),
    laps           INTEGER NOT NULL CHECK (laps >= 0),
    statusId       INTEGER NOT NULL REFERENCES dim_status(statusId),
    is_dnf         INTEGER NOT NULL CHECK (is_dnf IN (0, 1)),
    dnf_cause      TEXT CHECK (dnf_cause IS NULL OR dnf_cause IN ('mech', 'driver', 'other')),
    PRIMARY KEY (year, round, driverId),
    FOREIGN KEY (year, round) REFERENCES fact_race(year, round)
) STRICT;

CREATE TABLE IF NOT EXISTS fact_lap (
    year          INTEGER NOT NULL,
    round         INTEGER NOT NULL,
    lap           INTEGER NOT NULL CHECK (lap >= 1),
    driverId      TEXT NOT NULL REFERENCES dim_driver(driverId),
    position      REAL,
    time_str      TEXT,
    milliseconds  REAL CHECK (milliseconds IS NULL OR milliseconds > 0),
    PRIMARY KEY (year, round, lap, driverId),
    FOREIGN KEY (year, round) REFERENCES fact_race(year, round)
) STRICT;

CREATE TABLE IF NOT EXISTS fact_pit_stop (
    year       INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    driverId   TEXT NOT NULL REFERENCES dim_driver(driverId),
    lap        INTEGER NOT NULL CHECK (lap >= 1),
    stop       INTEGER NOT NULL CHECK (stop >= 1),
    duration_s REAL,
    PRIMARY KEY (year, round, driverId, stop),
    FOREIGN KEY (year, round) REFERENCES fact_race(year, round)
) STRICT;

-- Driver AND constructor snapshots in one table, discriminated by kind
-- ('driver' | 'constructor') — one PK, one check, no nullable-half-key.
-- Exactly one of the two ID columns is non-null per row.
CREATE TABLE IF NOT EXISTS fact_championship_snapshot (
    year           INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('driver', 'constructor')),
    entity_id      TEXT NOT NULL,
    points         REAL NOT NULL CHECK (points >= 0),
    wins           INTEGER CHECK (wins IS NULL OR wins >= 0),
    position       INTEGER CHECK (position IS NULL OR position >= 1),
    PRIMARY KEY (year, round, kind, entity_id)
) STRICT;

-- ── Views: point-in-time standings (training-side contract) ────────────────

-- For each snapshot row, the entity's PREVIOUS snapshot (prior round within
-- the season; round 1 falls through to the previous season's final via the
-- ord = year*1000 + round ordering — the same ordering
-- build_training_data._attach_prior_standings implements in pandas) and
-- the share-of-leader ratio within the same snapshot.
CREATE VIEW IF NOT EXISTS v_standings_pit AS
WITH snaps AS (
    SELECT year, round, kind, entity_id, points, position,
           points / NULLIF(MAX(points) OVER (PARTITION BY year, round, kind), 0)
               AS leader_ratio,
           year * 1000 + round AS ord
    FROM fact_championship_snapshot
)
SELECT year, round, kind, entity_id, points, position, leader_ratio, ord,
       LAG(ord) OVER (PARTITION BY kind, entity_id ORDER BY ord) AS prev_ord,
       LAG(points) OVER (PARTITION BY kind, entity_id ORDER BY ord) AS prev_points,
       LAG(position) OVER (PARTITION BY kind, entity_id ORDER BY ord) AS prev_position
FROM snaps;

-- ── Views: race intelligence (the SQL home of Phase-1 evidence) ────────────

-- Lap-level evidence: field-median lap per (race, lap), the race's median
-- lap (green-flag reference), and the slow-lap flag. Contract identical to
-- error_decomposition.race_lap_evidence: is_slow_lap = field_median_ms >
-- SLOW_LAP_FACTOR(1.20) * race_median_ms. Median via ROW_NUMBER over
-- ordering (SQLite has no PERCENTILE_CONT).
CREATE VIEW IF NOT EXISTS v_race_lap_evidence AS
WITH lap_ranked AS (
    SELECT year, round, lap, milliseconds,
           ROW_NUMBER() OVER (PARTITION BY year, round, lap
                              ORDER BY milliseconds) AS rn,
           COUNT(*) OVER (PARTITION BY year, round, lap) AS n
    FROM fact_lap
    WHERE milliseconds IS NOT NULL
),
lap_median AS (
    SELECT year, round, lap,
           AVG(milliseconds) AS field_median_ms
    FROM lap_ranked
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY year, round, lap
),
race_median AS (
    SELECT year, round, AVG(field_median_ms) AS race_median_ms
    FROM (
        SELECT year, round, lap, field_median_ms,
               ROW_NUMBER() OVER (PARTITION BY year, round ORDER BY field_median_ms) AS rn,
               COUNT(*) OVER (PARTITION BY year, round) AS n
        FROM lap_median
    )
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY year, round
)
SELECT m.year, m.round, m.lap, m.field_median_ms,
       r.race_median_ms,
       CASE WHEN m.field_median_ms > 1.20 * r.race_median_ms THEN 1 ELSE 0 END AS is_slow_lap
FROM lap_median m
JOIN race_median r ON r.year = m.year AND r.round = m.round;

-- Slow-lap summary per race (SC exposure): count, first slow lap, share.
CREATE VIEW IF NOT EXISTS v_race_sc_exposure AS
SELECT year, round,
       SUM(is_slow_lap)                    AS sc_laps,
       MIN(CASE WHEN is_slow_lap = 1 THEN lap END) AS sc_first_lap,
       ROUND(AVG(is_slow_lap), 4)          AS sc_share,
       COUNT(*)                            AS laps_recorded
FROM v_race_lap_evidence
GROUP BY year, round;

-- Per-driver running-order gains vs grid slot (lap 1 and last recorded
-- lap). Matches error_decomposition.running_position_gains: gain =
-- quali_pos - running position, positive = ahead of grid slot.
CREATE VIEW IF NOT EXISTS v_running_position_gains AS
WITH fl AS (
    SELECT year, round, driverId, lap, position,
           ROW_NUMBER() OVER (PARTITION BY year, round, driverId
                              ORDER BY lap ASC)  AS rn_first,
           ROW_NUMBER() OVER (PARTITION BY year, round, driverId
                              ORDER BY lap DESC) AS rn_last
    FROM fact_lap
    WHERE position IS NOT NULL
)
SELECT f.year, f.round, f.driverId,
       f.position AS lap1_pos,
       l.position AS last_pos,
       l.lap      AS last_lap
FROM fl f
JOIN fl l
  ON l.year = f.year AND l.round = f.round AND l.driverId = f.driverId
WHERE f.rn_first = 1 AND l.rn_last = 1;

-- Driver grid->flag gain (positive = gained places), joined with quali
-- position for the running-order evidence consumers.
CREATE VIEW IF NOT EXISTS v_driver_race_evidence AS
SELECT g.year, g.round, g.driverId,
       q.position AS quali_pos,
       g.lap1_pos,
       q.position - g.lap1_pos AS lap1_gain,
       g.last_pos,
       q.position - g.last_pos AS last_gain,
       g.last_lap
FROM v_running_position_gains g
JOIN fact_quali_entry q
  ON q.year = g.year AND q.round = g.round AND q.driverId = g.driverId;

-- Miss-attribution convenience view: one row per race entry with the
-- bucket outcome (P1-3 / P4-10 / P11+), DNF cause, and SC exposure —
-- error_decomposition's universe, expressed over the canonical model.
CREATE VIEW IF NOT EXISTS v_race_entry_outcome AS
SELECT e.year, e.round, e.driverId, e.constructorId,
       e.position, e.positionOrder, e.grid, e.statusId, s.status,
       e.is_dnf, e.dnf_cause, e.points, e.laps,
       CASE
           WHEN e.position BETWEEN 1 AND 3  THEN 1
           WHEN e.position BETWEEN 4 AND 10 THEN 2
           WHEN e.position > 10             THEN 3
           ELSE NULL
       END AS outcome_bucket,
       sc.sc_laps, sc.sc_first_lap, sc.sc_share
FROM fact_race_entry e
JOIN dim_status s ON s.statusId = e.statusId
LEFT JOIN v_race_sc_exposure sc ON sc.year = e.year AND sc.round = e.round;
