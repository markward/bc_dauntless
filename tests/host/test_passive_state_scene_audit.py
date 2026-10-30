"""The real host loop, on the busiest dev scene, with the sleep audit on.

With DAUNTLESS_PASSIVE_AUDIT=1 every sleeping weapon is also stepped the old
way each tick; any state change the sleep missed is recorded. A clean run that
still slept and woke things proves the watched fields cover a whole fight.
"""
import pytest

from tests.helpers import bc_assets


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def test_combat_stress_runs_clean_under_the_audit(monkeypatch):
    galaxy = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")
    if not galaxy.is_file():
        pytest.skip("BC assets not available")
    monkeypatch.delenv("DAUNTLESS_PASSIVE_STATE", raising=False)
    monkeypatch.delenv("DAUNTLESS_PASSIVE_AUDIT", raising=False)
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "16")
    monkeypatch.setenv("DAUNTLESS_PASSIVE_AUDIT", "1")

    from engine import host_loop as hl
    from engine.appc import passive_state

    now = [1000.0]

    def clock():
        now[0] += 0.1  # 6 ticks a frame
        return now[0]
    monkeypatch.setattr(hl, "_frame_clock", clock)

    assert hl.run("engine.dev_missions.combat_stress", max_ticks=120) == 0
    assert passive_state.enabled(), "passive state was off for this run"
    assert passive_state.audit_failures() == []
    counts = passive_state.counts()
    assert counts["slept"] > 0, counts
    assert counts["woke"] > 0, counts
