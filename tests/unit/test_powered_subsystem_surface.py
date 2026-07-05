"""PoweredSubsystem full SDK power surface — Task 1 of the power-management plan.

Pins draw-mode constants, BC-faithful defaults, slider clamping + rescale,
event delivery, Turn/SetPowerSource, and the GetNormalPowerWanted alias.
"""
import App
from engine.appc.subsystems import (
    PoweredSubsystem, PSM_MAIN_FIRST, PSM_BACKUP_FIRST, PSM_BACKUP_ONLY,
)


def _reset_handlers():
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def test_draw_mode_constants():
    assert (PSM_MAIN_FIRST, PSM_BACKUP_FIRST, PSM_BACKUP_ONLY) == (0, 1, 2)
    assert PoweredSubsystem.POWER_MODE == PSM_MAIN_FIRST


def test_spawn_defaults_bc_faithful():
    ps = PoweredSubsystem("Sensors")
    # BC spawn sequence: every consumer starts at 100% wanted.
    assert ps.GetPowerPercentageWanted() == 1.0
    assert ps.GetPowerWanted() == 0.0
    assert ps.GetPowerReceived() == 0.0
    assert ps.GetNormalPowerPercentage() == 1.0


def test_set_power_percentage_clamps_and_rescales():
    ps = PoweredSubsystem("Phasers")
    ps.SetNormalPowerPerSecond(300.0)
    ps.SetPowerWanted(300.0)
    ps.SetPowerPercentageWanted(2.0)          # clamps to 1.25
    assert ps.GetPowerPercentageWanted() == 1.25
    # BC FUN_00562430: powerWanted rescales by pct/old (old was 1.0)
    assert abs(ps.GetPowerWanted() - 375.0) < 1e-9
    ps.SetPowerPercentageWanted(-1.0)         # clamps to 0.0
    assert ps.GetPowerPercentageWanted() == 0.0


def test_set_power_percentage_posts_event():
    """SetPowerPercentageWanted broadcasts ET_SUBSYSTEM_POWER_CHANGED via the
    event manager.  Pattern mirrors test_cloaking_subsystem's _CapturedEvents:
    register a global broadcast handler, trigger the action, assert receipt."""
    _reset_handlers()
    captured = []
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SUBSYSTEM_POWER_CHANGED, captured, __name__ + "._on_power_changed"
    )
    ps = PoweredSubsystem("Shields")
    ps.SetPowerPercentageWanted(0.5)
    assert len(captured) == 1
    App.g_kEventManager.RemoveBroadcastHandler(
        App.ET_SUBSYSTEM_POWER_CHANGED, captured, __name__ + "._on_power_changed"
    )
    _reset_handlers()


def test_turn_and_power_source():
    ps = PoweredSubsystem("Sensors")
    ps.Turn(1)
    assert ps.IsOn() == 1
    ps.Turn(0)
    assert ps.IsOn() == 0
    ps.SetPowerSource(1)      # stored, no behaviour yet
    assert ps.GetNormalPowerWanted() == ps.GetNormalPowerPerSecond()


def _on_power_changed(handler, event):
    handler.append(event.GetSource())
