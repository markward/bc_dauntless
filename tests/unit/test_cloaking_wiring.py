"""W5.T2 — Cloaking property getters + ship wiring + hardpoint loading + App exports.

W5.T1 landed the CloakingSubsystem state machine; this pins the plumbing that
makes a cloak-capable ship actually return a working subsystem from
GetCloakingSubsystem(), exposes it through GetSubsystems(), drives its per-tick
Update from the game loop, and lets the SDK CloakShip preprocessor
(sdk/Build/scripts/AI/Preprocessors.py:2068) engage the cloak.
"""
import App

from engine.appc.properties import CloakingSubsystemProperty
from engine.appc.subsystems import CloakingSubsystem, CLOAK_TRANSITION_DURATION
from engine.appc.ships import ShipClass, ShipClass_Create


# ── CloakingSubsystemProperty scalar field ────────────────────────────────────

def test_cloak_strength_round_trip():
    p = CloakingSubsystemProperty("Cloaking Device")
    p.SetCloakStrength(100.0)
    assert p.GetCloakStrength() == 100.0


def test_cloak_strength_has_sane_default():
    p = CloakingSubsystemProperty("Cloaking Device")
    # Default must be a real number, not None, so the mapping never divides by
    # a missing value.
    assert isinstance(p.GetCloakStrength(), float)


# ── Ship wiring ───────────────────────────────────────────────────────────────

def test_get_cloaking_subsystem_none_by_default():
    """A freshly-created ship has no cloak (most ships aren't cloak-capable)."""
    ship = ShipClass_Create("Galaxy")
    assert ship.GetCloakingSubsystem() is None


def test_set_get_cloaking_subsystem():
    ship = ShipClass()
    cs = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cs)
    assert ship.GetCloakingSubsystem() is cs


def test_set_cloaking_subsystem_attaches_parent_ship():
    """Mirrors SetRepairSubsystem — _attach_subsystem wires the back-ref so the
    subsystem can climb to its ship."""
    ship = ShipClass()
    cs = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cs)
    assert cs._climb_to_ship() is ship


def test_cloaking_subsystem_appears_in_get_subsystems():
    """SDK Preprocessors.py:865 walks GetSubsystems(); the cloak must be visible
    to AI subsystem targeting / iteration."""
    ship = ShipClass()
    cs = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cs)
    assert cs in ship.GetSubsystems()


def test_cloaking_subsystem_absent_from_get_subsystems_when_none():
    ship = ShipClass_Create("Galaxy")
    # No cloak — nothing in the list should be a CloakingSubsystem.
    assert not any(isinstance(s, CloakingSubsystem) for s in ship.GetSubsystems())


# ── App.py exports ────────────────────────────────────────────────────────────

def test_app_cloaking_subsystem_create():
    cs = App.CloakingSubsystem_Create("Cloaking Device")
    assert isinstance(cs, CloakingSubsystem)
    assert cs.GetName() == "Cloaking Device"


def test_app_cloaking_subsystem_cast_passes_cloak():
    cs = CloakingSubsystem("Cloaking Device")
    assert App.CloakingSubsystem_Cast(cs) is cs


def test_app_cloaking_subsystem_cast_rejects_non_cloak():
    assert App.CloakingSubsystem_Cast(object()) is None
    assert App.CloakingSubsystem_Cast(None) is None


# ── Hardpoint / SetupProperties construction ──────────────────────────────────

def test_setup_properties_creates_and_attaches_cloak():
    """A CloakingSubsystemProperty in the property set yields a live
    CloakingSubsystem attached via SetCloakingSubsystem (the warbird /
    birdofprey / vorcha hardpoint pattern)."""
    ship = ShipClass_Create("Warbird")
    cp = CloakingSubsystemProperty("Cloaking Device")
    cp.SetCloakStrength(100.0)
    ship.GetPropertySet().AddToSet("Scene Root", cp)
    ship.SetupProperties()

    cloak = ship.GetCloakingSubsystem()
    assert cloak is not None
    assert isinstance(cloak, CloakingSubsystem)
    assert cloak.GetProperty() is cp


def test_setup_properties_derives_transition_duration_from_strength():
    """CloakStrength maps to the transition duration: a fully-rated device
    (strength 100) cloaks in the canonical CLOAK_TRANSITION_DURATION; a weaker
    device is slower (duration scales inversely with strength)."""
    ship = ShipClass_Create("Warbird")
    cp = CloakingSubsystemProperty("Cloaking Device")
    cp.SetCloakStrength(100.0)
    ship.GetPropertySet().AddToSet("Scene Root", cp)
    ship.SetupProperties()
    cloak = ship.GetCloakingSubsystem()
    assert cloak._transition_duration == CLOAK_TRANSITION_DURATION

    # Half-strength device takes twice as long to complete the transition.
    ship2 = ShipClass_Create("Warbird")
    cp2 = CloakingSubsystemProperty("Cloaking Device")
    cp2.SetCloakStrength(50.0)
    ship2.GetPropertySet().AddToSet("Scene Root", cp2)
    ship2.SetupProperties()
    cloak2 = ship2.GetCloakingSubsystem()
    assert cloak2._transition_duration == CLOAK_TRANSITION_DURATION * 2.0


def test_setup_properties_no_cloak_property_leaves_none():
    ship = ShipClass_Create("Galaxy")
    ship.SetupProperties()
    assert ship.GetCloakingSubsystem() is None


# ── Per-tick Update drive from the game loop ──────────────────────────────────

def test_game_loop_advances_cloak_transition():
    """The game loop's subsystem update pass (engine/core/loop.py) must call
    CloakingSubsystem.Update(dt) each tick alongside Shield/Power, so an
    in-progress cloak actually completes."""
    from engine.appc.sets import SetClass
    from engine.core.loop import GameLoop, TICK_DELTA

    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "cloak_test_set")

    ship = ShipClass_Create("Warbird")
    ship.SetScript("test_script")  # makes iter_ships find it
    cp = CloakingSubsystemProperty("Cloaking Device")
    cp.SetCloakStrength(100.0)
    ship.GetPropertySet().AddToSet("Scene Root", cp)
    ship.SetupProperties()
    pSet.AddObjectToSet(ship, "warbird_1")

    cloak = ship.GetCloakingSubsystem()
    cloak.StartCloaking()
    assert cloak.IsCloaking()

    loop = GameLoop()
    # Advance enough ticks to exceed the transition duration.
    ticks = int(cloak._transition_duration / TICK_DELTA) + 2
    loop.advance(ticks)

    assert cloak.IsCloaked()


# ── SDK CloakShip preprocessor integration ────────────────────────────────────

def test_sdk_cloakship_engages_cloak():
    """AI.Preprocessors.CloakShip(1).CheckCloak() must call StartCloaking on a
    ship that now HAS a cloaking subsystem (the cloak engages)."""
    from AI.Preprocessors import CloakShip
    from engine.appc.ai import PreprocessingAI

    ship = ShipClass_Create("Warbird")
    cp = CloakingSubsystemProperty("Cloaking Device")
    cp.SetCloakStrength(100.0)
    ship.GetPropertySet().AddToSet("Scene Root", cp)
    ship.SetupProperties()

    pp = PreprocessingAI(ship, "CloakPP")
    cs = CloakShip(1)
    cs.pCodeAI = pp

    cloak = ship.GetCloakingSubsystem()
    assert not cloak.IsCloaking()
    cs.CheckCloak()
    assert cloak.IsCloaking()
