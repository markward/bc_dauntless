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

Phase 3: K4 (`cb.eligibility`) and K3 (`cb.projectiles`) stand down under the
audit for the same reason (their kernels' own can_detect would bypass it), so
the audited run's mirror audit compares the torpedo table's rows with the
Python torpedoes every tick while Python flies them. Without the audit both
kernels decide every step of the fight: K4 every tick, K3 every tick with a
torpedo in flight, with no whole step handed back to Python.

Native weapon state: K0 (the weapons' charging and reloading) stands down
under the audit (reason "audit"); without it, it steps every weapon every
tick, and the C-applied write logs and the one-call scalar push run.
"""
import pytest

from tests.helpers import bc_assets
from tests.helpers.k3_fight import (check_weapon_state_paths,
                                    posed_branches, posed_fallbacks,
                                    weapon_state_paths)


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

    # Posed parts (Task 5): how many pose tables and part slots of a POSED
    # ship the mirror audit really compared (a stale slot, or any slot of
    # a ship at its NIF pose, is skipped by design).
    posed = {"tables": 0, "slots": 0}
    audit_posed = native_combat._audit_posed
    audit_slot = native_combat._audit_slot

    def counting_posed(ship, row, name, flag):
        posed["tables"] += bool(flag)
        audit_posed(ship, row, name, flag)

    def counting_slot(sub, row, name):
        ship = sub._climb_to_ship() if hasattr(type(sub), "_climb_to_ship") \
            else None
        posed["slots"] += (row["part_gen"] == native_combat.part_gen()
                           and ship is not None
                           and bool(native_combat._posed_flag(ship)))
        audit_slot(sub, row, name)
    monkeypatch.setattr(native_combat, "_audit_posed", counting_posed)
    monkeypatch.setattr(native_combat, "_audit_slot", counting_slot)

    native_combat.reset()
    assert hl.run("engine.dev_missions.combat_stress", max_ticks=120) == 0
    assert native_combat.enabled(), "native combat was off for this run"
    assert native_combat.audit_enabled() is audit
    if not audit:
        audit_mirror()      # once, at the end
    counts = native_combat.counts()
    print("native-combat scene (audit %s) counts:" % audit, counts,
          "audits:", audits[0], "posed audits:", posed,
          "posed branches:", posed_branches(counts))
    return counts, list(native_combat.audit_failures()), audits[0], posed


def test_combat_stress_runs_clean_under_the_native_audit(monkeypatch):
    counts, failures, audits, posed = _run(monkeypatch, audit=True)
    assert failures == [], failures
    # Posed parts: the Birds of Prey swing (no target yet: cruise; then
    # red), and the audit compared their pose tables and part slots with
    # Python's every tick -- clean (failures above) and not vacuous.
    assert posed["tables"] > 0 and posed["slots"] > 0, posed
    assert set(posed_fallbacks(counts).values()) == {0}, \
        posed_fallbacks(counts)
    assert counts["native_calls"] > 0, counts
    assert counts["k1_records"] > 0, counts
    # K1 walks under the audit, with no WALK_START record (round trips
    # Task 1).
    assert counts["k1_logged"]["walk_start"] > 0, counts
    # K2 stood down for the audit: every step Python's.
    assert counts["k2_records"] == 0, counts
    assert counts["k2_python_steps"] > 0, counts
    assert (counts["k2_python_step_reasons"]["audit"]
            == counts["k2_python_steps"]), counts
    # K4 and K3 stood down for the audit too: every step Python's.
    assert counts["k4_runs"] == 0 and counts["k3_runs"] == 0, counts
    k4_why = {k: n for k, n in counts["k4_python_reasons"].items() if n}
    assert list(k4_why) == ["audit"], counts
    k3_why = {k: n for k, n in counts["k3_python_reasons"].items() if n}
    assert list(k3_why) == ["audit"], counts
    assert k3_why["audit"] == counts["k3_python_steps"] > 0, counts
    # K0 stood down for the audit too (native weapon state): every
    # weapons step was the Python walk, reason "audit".
    assert counts["k0_steps"] == 0, weapon_state_paths(counts)
    k0_why = {k: n for k, n in counts["k0_python_step_reasons"].items() if n}
    assert list(k0_why) == ["audit"] and k0_why["audit"] >= 120, counts
    # GameLoop.tick audits the whole mirror once a tick.
    assert audits >= 120, audits


def test_combat_stress_walks_beams_natively_without_the_audit(monkeypatch):
    counts, failures, _audits, _posed = _run(monkeypatch, audit=False)
    assert failures == [], failures
    # Posed parts: no posed hand-back in the whole fight (posed_ship /
    # posed_target retired, part_stale 0: every slot current when read),
    # while the swinging Birds of Prey were walked natively.
    assert set(posed_fallbacks(counts).values()) == {0}, \
        posed_fallbacks(counts)
    assert counts["k1_posed"]["walks"] > 0, posed_branches(counts)
    # K2 posed lock aims and K3 posed steers are NOT asserted here: in
    # this 120-tick scene they depend on whether a lock or a torpedo meets
    # a Bird of Prey before it swings to red (identity), which varies run
    # to run (lock aims 0-84, steers 0-17 measured, posed parts Task 7) --
    # seeding every RNG did not fix it (the earlier test in the process
    # changes the outcome). The posed differentials carry both branches
    # (thousands per run).
    assert counts["k1_records"] > 0, counts
    # The round trips the plan removed (2026-11-01-native-combat-round-trips)
    # ran in the live loop: K1 walks with no WALK_START record (Task 1), lit
    # beams sustained and idle banks stopped as logged writes (Task 2), K2
    # resting contacts queued for the drain (Task 3; spec 2026-11-02 §4.3)
    # and presented by the drain itself (the shield splashes, §4.4) or its
    # Python batch. NOT asserted: K2's logged offline
    # system stop (nothing switches a phaser system off in this scene:
    # measured 0) and K3's native mount attributions (measured 10 here; like
    # the posed steers below, whether a guided shot at a subsystem flies in
    # 120 ticks varies run to run). The differentials carry both.
    logged = counts["k1_logged"]
    for key in ("walk_start", "beam_sustain", "idle_bank_stop"):
        assert logged[key] > 0, (key, logged)
    assert counts["k2_batched_contacts"] > 0, counts
    assert counts["k2_present_native"] > 0, counts
    assert counts["k2_present_native"] + counts["k2_present_python"] == \
        counts["k2_batched_contacts"], counts
    # K2 walked the beams natively (never the whole step in Python), with
    # the session's real instances (no "instances" fallback).
    assert counts["k2_records"] > 0, counts
    assert counts["k2_python_steps"] == 0, counts
    # K4 decided every tick's eligibility and K3 every torpedo step, with
    # zero whole-step fallbacks.
    assert counts["k4_runs"] > 0, counts
    assert not any(counts["k4_python_reasons"].values()), counts
    assert counts["k3_runs"] > 0 and counts["k3_records"] > 0, counts
    assert counts["k3_python_steps"] == 0, counts
    assert not any(counts["k3_python_reasons"].values()), counts
    # Native weapon state: K0 charged and reloaded every weapon every tick
    # (never handed a whole step back), its records' writes and K1 / K2's
    # were applied in C, and scalar mirror pushes went through the one-call
    # push.
    check_weapon_state_paths(counts)
    assert not any(counts["k0_python_step_reasons"].values()), counts
    assert counts["k0_records"]["DONE"] >= 120, counts
