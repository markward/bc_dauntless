"""The real host loop, on the busiest dev scene, with native combat on.

With DAUNTLESS_NATIVE_AUDIT=1 every dispatched sensor query (can_detect and
its pieces, occlusion) is answered by both the native kernel and the Python,
and every GameLoop.tick ends by comparing the whole mirror with its Python
objects; any difference is recorded. A clean run in which the kernel really
answered -- and the mirror audit really ran, and K1 really walked the fight's
weapons (phase 1b) -- proves the mirror keeps up with a whole fight: AI,
damage, deaths, cloaks, power and every field K1 and the beams write back,
written through the public paths the game itself uses.

K2 (the `cb.phasers` beam walk, phase 2) does NOT walk under the audit: its
kernel's own can_detect would bypass the per-query audit, so the audited step
is Python's (reason "audit"). The second test runs the same fight with the
audit OFF and proves K2 really walked its phaser beams there, tracing the
real instances, with the mirror still equal to Python at the end.
"""
import pytest

from tests.helpers import bc_assets


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def _run(monkeypatch, audit):
    """combat_stress through hl.run for 120 ticks, native on (and the audit
    when `audit`): (counts, mirror audit failures, audits run)."""
    galaxy = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy"
              / "Galaxy.nif")
    if not galaxy.is_file():
        pytest.skip("BC assets not available")
    from engine.appc import native_combat
    if not native_combat.available():
        pytest.skip("native combat bindings not built")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "16")
    if audit:
        monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")
    else:
        monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "1")
        monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)

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
    assert native_combat.audit_enabled() is audit
    if not audit:
        audit_mirror()      # once, at the end
    counts = native_combat.counts()
    print("native-combat scene (audit %s) counts:" % audit, counts,
          "audits:", audits[0])
    return counts, list(native_combat.audit_failures()), audits[0]


def test_combat_stress_runs_clean_under_the_native_audit(monkeypatch):
    counts, failures, audits = _run(monkeypatch, audit=True)
    assert failures == [], failures
    assert counts["native_calls"] > 0, counts
    assert counts["k1_records"] > 0, counts
    # K2 stood down for the audit: every step Python's.
    assert counts["k2_records"] == 0, counts
    assert counts["k2_python_steps"] > 0, counts
    assert (counts["k2_python_step_reasons"]["audit"]
            == counts["k2_python_steps"]), counts
    # GameLoop.tick audits the whole mirror once a tick.
    assert audits >= 120, audits


def test_combat_stress_walks_beams_natively_without_the_audit(monkeypatch):
    counts, failures, _audits = _run(monkeypatch, audit=False)
    assert failures == [], failures
    assert counts["k1_records"] > 0, counts
    # K2 walked the beams natively (never the whole step in Python), with
    # the session's real instances (no "instances" fallback).
    assert counts["k2_records"] > 0, counts
    assert counts["k2_python_steps"] == 0, counts
