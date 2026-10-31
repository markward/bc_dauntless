"""The real host loop, on the busiest dev scene, with the native combat
audit on.

With DAUNTLESS_NATIVE_AUDIT=1 every dispatched sensor query (can_detect and
its pieces, occlusion) is answered by both the native kernel and the Python,
and every GameLoop.tick ends by comparing the whole mirror with its Python
objects; any difference is recorded. A clean run in which the kernel really
answered -- and the mirror audit really ran, and K1 really walked the fight's
weapons (phase 1b) -- proves the mirror keeps up with a whole fight: AI,
damage, deaths, cloaks, power and every field K1 writes back, written through
the public paths the game itself uses.
"""
import pytest

from tests.helpers import bc_assets


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def test_combat_stress_runs_clean_under_the_native_audit(monkeypatch):
    galaxy = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")
    if not galaxy.is_file():
        pytest.skip("BC assets not available")
    from engine.appc import native_combat
    if not native_combat.available():
        pytest.skip("native combat bindings not built")
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "16")
    monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")

    from engine import host_loop as hl

    now = [1000.0]

    def clock():
        now[0] += 0.1  # 6 ticks a frame
        return now[0]
    monkeypatch.setattr(hl, "_frame_clock", clock)

    audits = [0]
    audit_mirror = native_combat.audit_mirror

    def counting_audit():
        audits[0] += 1
        audit_mirror()
    monkeypatch.setattr(native_combat, "audit_mirror", counting_audit)

    native_combat.reset()
    assert hl.run("engine.dev_missions.combat_stress", max_ticks=120) == 0
    assert native_combat.enabled(), "native combat was off for this run"
    assert native_combat.audit_enabled(), "the audit was off for this run"
    failures = list(native_combat.audit_failures())
    assert failures == [], failures
    counts = native_combat.counts()
    print("native-combat scene audit counts:", counts, "audits:", audits[0])
    assert counts["native_calls"] > 0, counts
    assert counts["k1_records"] > 0, counts
    # GameLoop.tick audits the whole mirror once a tick.
    assert audits[0] >= 120, audits
