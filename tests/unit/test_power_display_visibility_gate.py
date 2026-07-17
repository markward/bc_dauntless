"""EngPowerDisplay visibility gates Bridge.PowerDisplay.Update -> AdjustPower.

The engine-side conduit draw is the real power governor; AdjustPower is BC's
UI-side auto-rebalance and must run only while the engineering display is up
(or on a forced Update(1)).  See the 2026-07-17 spec.
"""
import App
import Bridge.PowerDisplay as PD
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty
from engine.appc.tg_ui import eng_power
from engine.appc.tg_ui.eng_power import EngPowerDisplay


def _player():
    ship = App.ShipClass_Create("GateShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(250000.0)
    prop.SetBackupBatteryLimit(80000.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    for s in (ship.GetImpulseEngineSubsystem(), ship.GetPhaserSystem(),
              ship.GetTorpedoSystem(), ship.GetPulseWeaponSystem()):
        if s:
            s.SetNormalPowerPerSecond(50.0)
            s.TurnOn()
    return ship


def _wired_display():
    ship = _player()
    App.Game_SetCurrentPlayer(ship)
    pd = EngPowerDisplay(400.0, 200.0)
    PD.Init(pd)                      # builds children (needs a current player)
    PD.g_idPowerDisplay = pd.GetObjID()
    return pd


def test_completely_visible_true_when_engineering_open(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: True)
    assert pd.IsCompletelyVisible() == 1


def test_completely_visible_false_when_engineering_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    assert pd.IsCompletelyVisible() == 0


def test_update_skips_adjustpower_when_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update()                      # unforced
    assert calls == []               # visibility gate fired


def test_update_runs_adjustpower_when_open(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: True)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update()
    assert calls == [1]              # gate open -> rebalance runs


def test_forced_update_runs_adjustpower_even_when_closed(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(lambda: False)
    calls = []
    monkeypatch.setattr(PD, "AdjustPower", lambda systems: calls.append(1))
    PD.Update(1)                     # bForce punches through
    assert calls == [1]


def test_no_check_falls_back_to_base_visibility(monkeypatch):
    pd = _wired_display()
    eng_power.set_engineering_open_check(None)
    # Fallback = TGPane chain-walk; the display's own _visible defaults True.
    assert pd.IsCompletelyVisible() == 1
