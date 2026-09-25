"""
Tests for the live-snapshot producer (live_refresh.py).

The failure modes these pin:
  - the producer must be opt-in: no env flag, no thread, no side effects
    (dev machines and every other deployment keep today's behavior)
  - freshness: a young snapshot is never rebuilt; a missing/old one is
  - multi-worker safety: the lockfile blocks a second refresher, and a
    lock left by a crashed holder is stolen once stale
  - the canonical DB is built only when missing, and the build writes
    the hidden manifest — never the CI drift-guard baseline
  - failure isolation: a failed refresh releases the lock, reports the
    error, and leaves the last good snapshot in place

The subprocess itself is not executed here (live_race.py's behavior is
pinned by model-notebooks/tests/test_live_race.py); the recorded
command list is the contract.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live_refresh  # noqa: E402


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Isolate every path the producer touches into tmp_path."""
    live_dir = tmp_path / "datasets"
    live_dir.mkdir()
    monkeypatch.setattr(live_refresh, "LIVE_PATH", live_dir / "live_state.json")
    monkeypatch.setattr(live_refresh, "DB_PATH", live_dir / "f1_canonical.db")
    monkeypatch.setattr(live_refresh, "LOCK_PATH", live_dir / "live_state.lock")
    live_refresh._stop.clear()
    live_refresh._started = False
    yield live_dir
    live_refresh._stop.set()


class TestGating:
    def test_disabled_by_default(self):
        assert live_refresh.enabled() is False

    def test_env_flag_enables(self, monkeypatch):
        for v in ("1", "true", "YES", "on"):
            monkeypatch.setenv("RACE_INTEL_LIVE_ENABLED", v)
            assert live_refresh.enabled() is True, v

    def test_disabled_means_no_thread(self, workspace):
        assert live_refresh.start_background(logging.getLogger("t")) is None


class TestRefreshDecision:
    def test_fresh_snapshot_is_skipped(self, workspace):
        live_refresh.LIVE_PATH.write_text("{}", encoding="utf-8")
        res = live_refresh.maybe_refresh()
        assert res == {"refreshed": False, "reason": "fresh", "age_s": 0}

    def test_missing_snapshot_is_built(self, workspace, monkeypatch):
        cmds = []

        def fake_run(cmd, timeout_s):
            cmds.append(Path(cmd[1]).name)
            live_refresh.DB_PATH.write_text("", encoding="utf-8")
            live_refresh.LIVE_PATH.write_text("{}", encoding="utf-8")
            return "ok"

        monkeypatch.setattr(live_refresh, "_run", fake_run)
        res = live_refresh.maybe_refresh()
        assert res["refreshed"] is True and res["reason"] == "built"
        # db build first, then the snapshot script
        assert cmds == ["build_canonical.py", "live_race.py"]

    def test_existing_db_skips_the_build(self, workspace, monkeypatch):
        live_refresh.DB_PATH.write_text("", encoding="utf-8")
        cmds = []

        def fake_run(cmd, timeout_s):
            cmds.append(Path(cmd[1]).name)
            live_refresh.LIVE_PATH.write_text("{}", encoding="utf-8")
            return "ok"

        monkeypatch.setattr(live_refresh, "_run", fake_run)
        live_refresh.maybe_refresh()
        assert cmds == ["live_race.py"]

    def test_failed_refresh_reports_and_releases_lock(self, workspace,
                                                      monkeypatch):
        def boom(cmd, timeout_s):
            raise RuntimeError("openf1 unreachable")

        monkeypatch.setattr(live_refresh, "_run", boom)
        res = live_refresh.maybe_refresh()
        assert res["refreshed"] is False
        assert str(res["reason"]).startswith("error:")
        assert "openf1" in res["reason"]
        assert not live_refresh.LOCK_PATH.exists()  # never wedged


class TestMultiWorkerLock:
    def test_locked_elsewhere_is_skipped(self, workspace):
        live_refresh.LOCK_PATH.write_text("999 now", encoding="utf-8")
        res = live_refresh.maybe_refresh()
        assert res["refreshed"] is False
        assert res["reason"] == "locked-elsewhere"

    def test_stale_lock_is_stolen(self, workspace, monkeypatch):
        live_refresh.LOCK_PATH.write_text("1 crashed", encoding="utf-8")
        old = time.time() - (live_refresh.STALE_LOCK_S + 60)
        os.utime(live_refresh.LOCK_PATH, (old, old))

        def fake_run(cmd, timeout_s):
            live_refresh.LIVE_PATH.write_text("{}", encoding="utf-8")
            return "ok"

        monkeypatch.setattr(live_refresh, "_run", fake_run)
        res = live_refresh.maybe_refresh()
        assert res["refreshed"] is True
        assert not live_refresh.LOCK_PATH.exists()


class TestCommandContract:
    def test_scripts_exist(self):
        """The commands reference real files — a rename breaks prod."""
        assert live_refresh._refresh_command()[1].endswith("live_race.py")
        assert Path(live_refresh._refresh_command()[1]).exists()
        assert Path(live_refresh._build_db_command()[1]).exists()
        assert Path(
            live_refresh._build_db_command()[
                live_refresh._build_db_command().index("--schema") + 1]
        ).exists()

    def test_db_build_never_touches_the_committed_manifest(self):
        """The drift-guard baseline (build_manifest.json) is CI's
        contract — the live producer must write the hidden variant."""
        cmd = live_refresh._build_db_command()
        manifest = cmd[cmd.index("--manifest") + 1]
        assert Path(manifest).name.startswith(".live_build_manifest")

    def test_snapshot_is_deterministic(self):
        cmd = live_refresh._refresh_command()
        assert cmd[cmd.index("--seed") + 1] == str(live_refresh.SEED)


class TestLoop:
    def test_start_background_runs_and_stops(self, workspace, monkeypatch):
        monkeypatch.setenv("RACE_INTEL_LIVE_ENABLED", "1")
        calls = []

        def fake_refresh(force=False):
            calls.append(force)
            live_refresh.stop_background()  # exit after the first tick
            return {"refreshed": False, "reason": "test"}

        monkeypatch.setattr(live_refresh, "maybe_refresh", fake_refresh)
        t = live_refresh.start_background(logging.getLogger("t"))
        assert t is not None
        t.join(timeout=5)
        assert not t.is_alive()
        assert calls == [False]

    def test_idempotent_start(self, workspace, monkeypatch):
        monkeypatch.setenv("RACE_INTEL_LIVE_ENABLED", "1")
        monkeypatch.setattr(live_refresh, "maybe_refresh",
                            lambda force=False: {"refreshed": False})
        live_refresh.stop_background()
        t1 = live_refresh.start_background(logging.getLogger("t"))
        assert live_refresh.start_background(logging.getLogger("t")) is None
        live_refresh.stop_background()
        t1.join(timeout=5)


def test_snapshot_output_is_served_json(workspace, monkeypatch):
    """Whatever the producer writes must be JSON (the API reads it
    blindly); the refresh command's --out is the LIVE_PATH itself."""
    monkeypatch.setenv("RACE_INTEL_LIVE_ENABLED", "1")
    out_arg = live_refresh._refresh_command()[
        live_refresh._refresh_command().index("--out") + 1]
    assert Path(out_arg) == live_refresh.LIVE_PATH
    live_refresh.LIVE_PATH.write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8")
    assert json.loads(
        live_refresh.LIVE_PATH.read_text(encoding="utf-8"))["schema_version"] == 1
