import App
from engine.core.game import Game, _set_current_game
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    TorpedoSystem, PhaserSystem, WarpEngineSubsystem,
    SensorSubsystem, TractorBeamSystem, PulseWeaponSystem,
    ImpulseEngineSubsystem,
)


def setup_function(_):
    _set_current_game(None)


def test_game_get_current_player_returns_none_when_no_game():
    _set_current_game(None)
    assert App.Game_GetCurrentPlayer() is None


def test_game_get_current_player_returns_none_when_player_unset():
    g = Game()
    _set_current_game(g)
    assert App.Game_GetCurrentPlayer() is None


def test_game_set_and_get_current_player():
    g = Game()
    _set_current_game(g)
    ship = ShipClass()
    App.Game_SetCurrentPlayer(ship)
    assert App.Game_GetCurrentPlayer() is ship


def test_game_class_method_alias():
    g = Game()
    _set_current_game(g)
    ship = ShipClass()
    g.SetCurrentPlayer(ship)
    assert g.GetCurrentPlayer() is ship


def test_bare_shipclass_constructor_leaves_subsystems_unset():
    """Direct ShipClass() (used in tests) leaves slots None until set
    explicitly — only the ShipClass_Create factory populates defaults."""
    ship = ShipClass()
    assert ship.GetTorpedoSystem() is None
    assert ship.GetPhaserSystem() is None
    assert ship.GetWarpEngineSubsystem() is None
    assert ship.GetSensorSubsystem() is None
    assert ship.GetTractorBeamSystem() is None
    assert ship.GetPulseWeaponSystem() is None
    assert ship.GetImpulseEngineSubsystem() is None


def test_factory_populates_default_subsystems():
    """SDK call sites (E2M0:720, E2M2:467, E5M2:307) chain
    ``pShip.GetTorpedoSystem().SetAmmoType(...)`` without null-guarding —
    so ShipClass_Create must hand back ships with all subsystems filled in."""
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("ambassador")
    assert ship.GetTorpedoSystem() is not None
    assert ship.GetPhaserSystem() is not None
    assert ship.GetWarpEngineSubsystem() is not None
    assert ship.GetSensorSubsystem() is not None
    assert ship.GetTractorBeamSystem() is not None
    assert ship.GetPulseWeaponSystem() is not None
    assert ship.GetImpulseEngineSubsystem() is not None
    # SetAmmoType chain (E2M0 line 720) must not raise.  It's a slot
    # SELECTION — on a bare ship with no ammo loaded it's a silent no-op,
    # never a write into the slot table.
    ship.GetTorpedoSystem().SetAmmoType(2, 0)
    assert ship.GetTorpedoSystem().GetAmmoType(0) is None
    assert ship.GetTorpedoSystem().GetCurrentAmmoType() is None


def test_player_subsystem_set_then_get_round_trip():
    ship = ShipClass()
    torpedo = TorpedoSystem("Torpedo Bay")
    phaser  = PhaserSystem("Forward Phasers")
    warp    = WarpEngineSubsystem("Warp Drive")
    sensor  = SensorSubsystem("Sensors")
    tractor = TractorBeamSystem("Tractor")
    pulse   = PulseWeaponSystem("Pulse")
    impulse = ImpulseEngineSubsystem("Impulse")
    ship.SetTorpedoSystem(torpedo)
    ship.SetPhaserSystem(phaser)
    ship.SetWarpEngineSubsystem(warp)
    ship.SetSensorSubsystem(sensor)
    ship.SetTractorBeamSystem(tractor)
    ship.SetPulseWeaponSystem(pulse)
    ship.SetImpulseEngineSubsystem(impulse)
    assert ship.GetTorpedoSystem() is torpedo
    assert ship.GetPhaserSystem() is phaser
    assert ship.GetWarpEngineSubsystem() is warp
    assert ship.GetSensorSubsystem() is sensor
    assert ship.GetTractorBeamSystem() is tractor
    assert ship.GetPulseWeaponSystem() is pulse
    assert ship.GetImpulseEngineSubsystem() is impulse


def test_player_target_round_trip():
    ship = ShipClass()
    target = ShipClass()
    assert ship.GetTarget() is None
    ship.SetTarget(target)
    assert ship.GetTarget() is target


def test_player_target_subsystem_round_trip():
    ship = ShipClass()
    sub = PhaserSystem("X")
    ship.SetTargetSubsystem(sub)
    assert ship.GetTargetSubsystem() is sub


def test_player_lifecycle_default_alive_undocked():
    ship = ShipClass()
    assert ship.IsDocked() == 0
    assert ship.IsDying() == 0
    assert ship.IsDead() == 0


def test_player_set_docked_round_trip():
    ship = ShipClass()
    ship.SetDocked(1)
    assert ship.IsDocked() == 1
    ship.SetDocked(0)
    assert ship.IsDocked() == 0


def test_player_set_dead_round_trip():
    ship = ShipClass()
    ship.SetDead(1)
    assert ship.IsDead() == 1


def test_chain_player_torpedo_get_num_ammo():
    """SDK pattern: App.Game_GetCurrentPlayer().GetTorpedoSystem().GetNumAmmoTypes()."""
    g = Game()
    _set_current_game(g)
    ship = ShipClass()
    ship.SetTorpedoSystem(TorpedoSystem("Bay"))
    g.SetCurrentPlayer(ship)
    n = App.Game_GetCurrentPlayer().GetTorpedoSystem().GetNumAmmoTypes()
    assert n == 0
