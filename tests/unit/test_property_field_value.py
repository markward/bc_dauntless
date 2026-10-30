"""TGModelProperty._field_value and PowerSubsystem._prop_f's closure-free read."""
from engine.appc.properties import PowerProperty, TGModelProperty
from engine.appc.subsystems import PowerSubsystem


def _plant(prop):
    ps = PowerSubsystem("WarpCore")
    ps.SetProperty(prop)
    return ps


def test_field_value_matches_generated_getter():
    prop = PowerProperty("WarpCore")
    prop.SetMainBatteryLimit(12345.678)
    assert prop._field_value("MainBatteryLimit") == prop.GetMainBatteryLimit()
    assert prop._field_value("MainBatteryLimit") == 12345.678
    assert prop._field_value("BackupBatteryLimit") is None
    assert prop.GetBackupBatteryLimit() is None


def test_prop_f_prefers_a_real_getter():
    class P(PowerProperty):
        def GetMainBatteryLimit(self):
            return 7.0

    prop = P("WarpCore")
    prop.SetMainBatteryLimit(1.0)
    assert _plant(prop).GetMainBatteryLimit() == 7.0


def test_prop_f_skips_the_generated_getter(monkeypatch):
    prop = PowerProperty("WarpCore")
    prop.SetMainBatteryLimit(500.0)
    prop.SetBackupBatteryLimit(250.0)
    plant = _plant(prop)
    orig = TGModelProperty.__getattr__

    def guarded(self, attr):
        if attr in ("GetMainBatteryLimit", "GetBackupBatteryLimit"):
            raise AssertionError("closure built for " + attr)
        return orig(self, attr)

    monkeypatch.setattr(TGModelProperty, "__getattr__", guarded)
    assert plant.GetMainBatteryLimit() == 500.0
    assert plant.GetBackupBatteryLimit() == 250.0
