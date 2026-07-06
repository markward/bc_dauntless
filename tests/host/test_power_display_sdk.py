"""Bridge/PowerDisplay.py must run UNMODIFIED against the widget shims.

Bootstrap: copy the SDK-boot fixture from the existing host-level QB test
(the one guarding the bridge-officer-speech path) — same conftest AST
transforms, same stub-list caveats (runtime stub list != test stub list).

This is the integration proof for the power-management work: the real SDK
Bridge/PowerDisplay.py Init/Update/AdjustPower and Bridge/EngineerMenuHandlers
ManagePower all run to completion against a real QuickBattle player ship
through the shim layer, with no edit to any SDK file.
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader  # noqa: F401


@pytest.fixture
def qb_booted_player(monkeypatch):
    """A live QuickBattle player ship, created by the real SDK cascade.

    Mirrors the bridge-officer-speech live path: boot the SDK under the
    mission harness (runtime loader — stub list + AST transforms included),
    run the QuickBattle Game->Episode->Mission cascade so a real player ship
    with a full subsystem complement exists on the current Game.
    """
    import App
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    player = App.Game_GetCurrentPlayer()
    assert player is not None
    return player


def _manage_power_event(n):
    """Build the int event ManagePower reads via GetInt() — the same
    typed-event convention the SDK uses (App.TGIntEvent_Create + SetInt)."""
    import App
    ev = App.TGIntEvent_Create()
    ev.SetInt(int(n))
    return ev


def _top_window_or_menu_object():
    """The `pObject` ManagePower forwards to via CallNextHandler on its
    edge cases. Any TGEventHandlerObject works; the int==5 path never
    forwards, so a plain handler object is enough."""
    from engine.appc.events import TGEventHandlerObject
    return TGEventHandlerObject()


def test_power_display_init_and_update_run(qb_booted_player):
    import App
    import Bridge.PowerDisplay as PD
    disp = App.EngPowerDisplay_Create(100.0, 200.0)   # triggers PD.Init
    PD.Update()                                        # the 0.5s refresh body

    # Bars exist and reflect the player's sliders after a Refresh.
    ctrl = App.EngPowerCtrl_GetPowerCtrl()
    player = App.Game_GetCurrentPlayer()
    sensors = player.GetSensorSubsystem()
    sensors.SetPowerPercentageWanted(0.5)
    ctrl.GetBarForSubsystem(sensors)
    ctrl.Refresh()
    assert abs(ctrl.GetBarForSubsystem(sensors).GetValue() - 0.5) < 1e-9

    # No stub leakage on the siphon-line seam: the tractor text child the CEF
    # panel reads must be a real TGParagraph, and the tractor/cloak handlers
    # must run against a synthetic event without raising.
    from engine.appc.tg_ui.widgets import TGParagraph
    tractor_text = disp.GetNthChild(PD.TRACTOR_TEXT)
    assert isinstance(tractor_text, TGParagraph)

    ev = App.TGEvent_Create()
    ev.SetDestination(player)
    PD.HandleTractor(disp, ev)
    PD.HandleCloak(disp, ev)


def test_adjust_power_throttles_proportionally_with_floor(qb_booted_player):
    import App
    import Bridge.PowerDisplay as PD
    player = App.Game_GetCurrentPlayer()
    systems = [player.GetImpulseEngineSubsystem(), player.GetWarpEngineSubsystem(),
               player.GetShields(), player.GetPhaserSystem(),
               player.GetTorpedoSystem(), player.GetPulseWeaponSystem(),
               player.GetSensorSubsystem()]
    for s in systems:
        if s:
            s.SetPowerPercentageWanted(1.25)
    # Shrink the conduits so demand > supply, then run the SDK auto-balance.
    App.EngPowerCtrl_Create(200.0)
    for s in systems:                       # bars must exist for AdjustPower
        if s:
            App.EngPowerCtrl_GetPowerCtrl().GetBarForSubsystem(s)
    PD.AdjustPower(systems)
    for s in systems:
        if s and s.GetNormalPowerWanted() > 0.0:
            assert s.GetPowerPercentageWanted() >= 0.2 - 1e-9   # 20% floor
    # weapons locked together, engines locked together:
    if player.GetPhaserSystem() and player.GetTorpedoSystem():
        assert (player.GetTorpedoSystem().GetPowerPercentageWanted()
                == player.GetPhaserSystem().GetPowerPercentageWanted())
    if player.GetImpulseEngineSubsystem() and player.GetWarpEngineSubsystem():
        assert (player.GetWarpEngineSubsystem().GetPowerPercentageWanted()
                == player.GetImpulseEngineSubsystem().GetPowerPercentageWanted())


def test_manage_power_event_flow(qb_booted_player):
    import App
    import Bridge.EngineerMenuHandlers as EMH
    App.EngPowerCtrl_Create(200.0)            # ManagePower calls Refresh()
    player = App.Game_GetCurrentPlayer()
    sensors = player.GetSensorSubsystem()
    App.EngPowerCtrl_GetPowerCtrl().GetBarForSubsystem(sensors)
    before = sensors.GetPowerPercentageWanted()
    ev = _manage_power_event(5)   # int 5 => group 2 (sensors), odd => +0.25
    EMH.ManagePower(_top_window_or_menu_object(), ev)
    after = player.GetSensorSubsystem().GetPowerPercentageWanted()
    assert abs(after - min(before + 0.25, 1.25)) < 1e-9
