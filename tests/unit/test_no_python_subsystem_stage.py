"""The subsystem stage is native only (phase 6 A1 Task 8, ruling R2): the
Python per-tick shield, power, cloak and repair code is gone, the switch
that chose it has no effect, and the power draw program with it.

What stays is SDK-facing or is a handler of the native stage's records
(engine/appc/native_subsystems.py): the breach trigger, the forced decloak,
the subsystem events, the steals, _wants_power (the engineering panel).
"""
import importlib

import App
import pytest

from engine.appc import native_combat as nc
from engine.appc import native_subsystems
from engine.appc.subsystems import (CloakingSubsystem, PoweredSubsystem,
                                    PowerSubsystem, RepairSubsystem,
                                    ShieldSubsystem)
from engine.appc.weapon_subsystems import TractorBeamSystem

_GONE = {
    ShieldSubsystem: ("Update",),
    PowerSubsystem: ("Update", "_update_flow", "_pump_consumers",
                     "_sum_wanted", "_draw", "_draw_main", "_draw_backup",
                     "_add_power_to_batteries"),
    CloakingSubsystem: ("Update", "_update_power"),
    RepairSubsystem: ("Update", "_repair_walk", "_repair_worked"),
    PoweredSubsystem: ("_update_power", "_record_draw",
                       "_passive_power_thaw", "_POWER_FREEZABLE"),
}

_KEPT = {
    PowerSubsystem: ("_trigger_breach", "StealPower",
                     "StealPowerFromReserve", "GetMainBatteryWatcher"),
    CloakingSubsystem: ("_force_decloak", "_wants_power", "StartCloaking",
                        "StopCloaking"),
    RepairSubsystem: ("_fire_repair_event", "AddToRepairList"),
    PoweredSubsystem: ("_wants_power", "_fire"),
    TractorBeamSystem: ("_wants_power", "_any_child_firing"),
}


def test_no_python_subsystem_stage_remains():
    for cls, names in _GONE.items():
        for name in names:
            assert name not in vars(cls), "%s.%s" % (cls.__name__, name)
    for cls, names in _KEPT.items():
        for name in names:
            assert hasattr(cls, name), "%s.%s" % (cls.__name__, name)
    assert not hasattr(native_subsystems, "enabled")
    with pytest.raises(ImportError):
        importlib.import_module("engine.appc.passive_power")


def test_the_switch_has_no_effect(monkeypatch):
    """DAUNTLESS_NATIVE_SUBSYSTEMS=0 is ignored: the stage is the native
    one whatever the environment says."""
    from engine.core import loop as game_loop
    monkeypatch.setenv("DAUNTLESS_NATIVE_SUBSYSTEMS", "0")
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1",
                  "DAUNTLESS_NATIVE_SUBSYSTEMS": "0"})
    native_subsystems.reset_counts()
    game_loop._update_ship_subsystems()
    assert native_subsystems.counts()["stages"] == 1


def test_a_stage_without_the_live_mirror_raises():
    """The stage needs the mirror (A2): a stage asked for before
    native_combat.configure() made it live raises, naming it."""
    from engine.core import loop as game_loop
    nc.reset()
    try:
        with pytest.raises(RuntimeError, match="mirror"):
            game_loop._update_ship_subsystems()
    finally:
        nc.configure()


def test_a_missing_native_module_raises(monkeypatch):
    """A3 (M10): no native module, no stage -- it raises instead of
    running nothing."""
    nc.configure()
    monkeypatch.setattr(native_subsystems, "_h", None)
    with pytest.raises(RuntimeError, match="_dauntless_host"):
        native_subsystems.step_all(1.0 / 60.0)


def test_the_kinds_have_no_python_piece_left():
    """The native session hands back articulation alone: there is no
    REPAIR_TAIL, and POWER_TAIL is the backup watcher's line only."""
    assert "REPAIR_TAIL" not in native_subsystems._EVENTS
    assert "REPAIR_SET" in native_subsystems._EVENTS
    assert App is not None
