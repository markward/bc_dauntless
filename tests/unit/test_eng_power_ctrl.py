"""TDD tests for EngPowerCtrl and EngPowerDisplay shims (Task 11)."""
import App
from engine.appc.subsystems import PoweredSubsystem


def test_bar_per_subsystem_and_refresh():
    ctrl = App.EngPowerCtrl_Create(200.0)
    assert App.EngPowerCtrl_GetPowerCtrl() is ctrl
    sensors = PoweredSubsystem("Sensor Array")
    sensors.SetNormalPowerPerSecond(100.0)
    bar = ctrl.GetBarForSubsystem(sensors)
    assert bar is not None
    assert ctrl.GetBarForSubsystem(sensors) is bar      # stable per subsystem
    assert ctrl.GetBarForSubsystem(None) is None
    sensors.SetPowerPercentageWanted(0.75)
    ctrl.Refresh()
    assert abs(bar.GetValue() - 0.75) < 1e-9


def test_display_create_calls_powerdisplay_init_safely():
    # No player exists in this test: Init must early-out without raising and
    # still register its ET_SET_PLAYER re-init handler.
    disp = App.EngPowerDisplay_Create(100.0, 200.0)
    assert App.EngPowerDisplay_GetPowerDisplay() is disp
    assert App.EngPowerDisplay_Cast(disp) is disp
    gauge = disp.CreateBatteryGauge(App.EngPowerDisplay.MAIN)
    assert gauge is not None


def test_eng_power_ctrl_cast():
    ctrl = App.EngPowerCtrl_Create(100.0)
    assert App.EngPowerCtrl_Cast(ctrl) is ctrl
    assert App.EngPowerCtrl_Cast(object()) is None


def test_eng_power_display_cast_rejects_non_display():
    disp = App.EngPowerDisplay_Create(50.0, 50.0)
    assert App.EngPowerDisplay_Cast(object()) is None
    assert App.EngPowerDisplay_Cast(disp) is disp


def test_display_constants():
    assert App.EngPowerDisplay.MAIN == 0
    assert App.EngPowerDisplay.BACKUP == 1
    assert App.EngPowerDisplay.WARP_CORE == 2


def test_display_get_conceptual_parent():
    disp = App.EngPowerDisplay_Create(80.0, 90.0)
    assert disp.GetConceptualParent() is None


def test_battery_gauge_kinds():
    disp = App.EngPowerDisplay_Create(80.0, 90.0)
    for kind in (App.EngPowerDisplay.MAIN,
                 App.EngPowerDisplay.BACKUP,
                 App.EngPowerDisplay.WARP_CORE):
        gauge = disp.CreateBatteryGauge(kind)
        assert gauge is not None
