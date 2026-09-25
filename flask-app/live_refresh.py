"""Background producer for live_state.json — the /live endpoint's source.

The serving API reads a snapshot file by mtime (no restart needed); this
module is what writes it on a cadence so the endpoint answers 200 in
production instead of 503. Design contracts:

- Opt-in via RACE_INTEL_LIVE_ENABLED=1: never changes behavior for
  dev, tests, or any deployment that does not ask for it.
- Subprocess, not import: live_race.py belongs to the model-notebooks
  dependency world (numpy/pandas/requests); running it as a script
  keeps the API process free of model-code imports and isolates any
  failure to a return code.
- One producer per machine: the thread runs in every gunicorn worker,
  so refreshes are guarded by a lockfile (O_CREAT|O_EXCL) and a
  freshness check — workers that find the snapshot younger than the
  interval simply skip their tick.
- Self-healing data: the canonical DB is a gitignored build artifact,
  so a fresh Render container does not have one. The first refresh
  builds it from the committed CSVs; containers are rebuilt on every
  deploy, which is exactly when the nightly refresh may have updated
  those CSVs.
- Failure isolation: a failed refresh logs and retries next tick; the
  API keeps serving the last good snapshot (its own staleness flag
  says how old it is). Nothing here can take the web process down.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from race_intelligence_api import LIVE_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "model-notebooks"
DB_PATH = MODEL_DIR / "datasets" / "f1_canonical.db"
LOCK_PATH = MODEL_DIR / "datasets" / "live_state.lock"

DEFAULT_INTERVAL_S = 300      # refresh cadence
FRESH_AFTER_S = DEFAULT_INTERVAL_S  # skip tick if snapshot is younger
STALE_LOCK_S = 900            # steal a lock older than this (crashed holder)
BUILD_TIMEOUT_S = 300         # build_canonical.py on a cold container
SNAPSHOT_TIMEOUT_S = 240      # live_race.py (fetch + simulate + write)
N_SIMS = 300
SEED = 42

_TRUE = {"1", "true", "yes", "on"}
_stop = threading.Event()
_started = False


def enabled() -> bool:
    """Whether the live producer should run (env opt-in)."""
    return os.environ.get("RACE_INTEL_LIVE_ENABLED", "").strip().lower() in _TRUE


def _refresh_command() -> list[str]:
    return [sys.executable, str(MODEL_DIR / "live_race.py"),
            "--db", str(DB_PATH),
            "--out", str(LIVE_PATH),
            "--sims", str(N_SIMS),
            "--seed", str(SEED)]


def _build_db_command() -> list[str]:
    return [sys.executable, str(MODEL_DIR / "build_canonical.py"),
            "--datasets", str(MODEL_DIR / "datasets"),
            "--schema", str(MODEL_DIR / "canonical_schema.sql"),
            "--db", str(DB_PATH),
            # the committed manifest stays untouched: this build exists
            # only to serve live snapshots, not to gate anything
            "--manifest", str(MODEL_DIR / "datasets" / ".live_build_manifest.json")]


def _run(cmd: list[str], timeout_s: int) -> str:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, cwd=MODEL_DIR)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:].strip()
        raise RuntimeError(
            f"refresh step failed ({' '.join(cmd[:2])}): {tail}")
    return proc.stdout


def _snapshot_age_s() -> float | None:
    try:
        return time.time() - LIVE_PATH.stat().st_mtime
    except OSError:
        return None  # missing


def _acquire_lock() -> bool:
    """O_CREAT|O_EXCL is atomic: exactly one worker wins. A lock left by
    a crashed/killed holder is stolen once it outlives STALE_LOCK_S."""
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCK_PATH, "x", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {time.time()}\n")
        return True
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            return False
        if age > STALE_LOCK_S:
            try:
                LOCK_PATH.unlink()
            except OSError:
                return False
            return _acquire_lock()
        return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def maybe_refresh(force: bool = False) -> dict:
    """Refresh the snapshot if it is missing or older than the cadence.

    Returns a small status dict (what happened + snapshot age); never
    raises — callers are background threads.
    """
    status: dict = {"refreshed": False, "reason": None}
    age = _snapshot_age_s()
    status["age_s"] = None if age is None else round(age)
    if not force and age is not None and age < FRESH_AFTER_S:
        status["reason"] = "fresh"
        return status
    if not _acquire_lock():
        status["reason"] = "locked-elsewhere"
        return status
    try:
        if not DB_PATH.exists():
            _run(_build_db_command(), BUILD_TIMEOUT_S)
        _run(_refresh_command(), SNAPSHOT_TIMEOUT_S)
        status["refreshed"] = True
        status["reason"] = "built"
        status["age_s"] = 0
    except Exception as e:  # noqa: BLE001 - the thread must survive
        status["reason"] = f"error: {e}"
    finally:
        _release_lock()
    return status


def _loop(logger) -> None:
    logger.info("live refresh thread started (interval %ss, out %s)",
                DEFAULT_INTERVAL_S, LIVE_PATH)
    while not _stop.is_set():
        res = maybe_refresh()
        if res["refreshed"]:
            logger.info("live snapshot refreshed (%s)", res)
        elif res["reason"] and str(res["reason"]).startswith("error"):
            logger.warning("live refresh failed; keeping last good "
                           "snapshot (%s)", res)
        _stop.wait(DEFAULT_INTERVAL_S)


def start_background(logger) -> threading.Thread | None:
    """Start the producer thread if enabled; idempotent per process."""
    global _started
    if not enabled():
        return None
    if _started:
        return None
    _started = True
    t = threading.Thread(target=_loop, args=(logger,),
                         name="race-intel-live-refresh", daemon=True)
    t.start()
    return t


def stop_background() -> None:
    """Signal the thread to exit (tests, graceful shutdown)."""
    _stop.set()
