"""Player Helm "Orbit" altitude scales with the planet (Mark, 2026-10-07, option C).

BC's AI/Player/OrbitPlanet.py circles at (R + 150, R + 190) and arms its
CloseEnough gate at 200 + R. BC planets were R ~ 90; our system maps scale
them ~20x, so the stock numbers put the player inside the atmosphere shell.
engine.orbit_altitude wraps CreateAI and rewrites those two values from
alt = max(150, 0.15 * R).
"""
import logging
import types

import pytest

import App
from engine import orbit_altitude as oa
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem


# ── Pure function ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("radius, expected", [
    (1800.0, (2070.0, 2142.0, 2160.0)),    # alt 270
    (7200.0, (8280.0, 8568.0, 8640.0)),    # alt 1080
    (300.0, (450.0, 490.0, 500.0)),        # floor 150 -- BC's own offsets
])
def test_orbit_distances(radius, expected):
    assert oa.orbit_distances(radius) == pytest.approx(expected)


def test_constants():
    assert oa.ORBIT_K == 0.15
    assert oa.ORBIT_FLOOR_GU == 150.0


# ── Hook on the real SDK module ───────────────────────────────────────────────

def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture
def orbit_mod(monkeypatch):
    """The real SDK AI.Player.OrbitPlanet, its CreateAI restored at teardown
    so the wrap never leaks into other tests."""
    _reset_app_state()
    import AI.Player.OrbitPlanet as mod
    # Start from BC's original even if an earlier test's host bootstrap
    # already wrapped it; teardown puts back whatever was there.
    orig = getattr(mod.CreateAI, "_dauntless_orbit_altitude_orig", None) or mod.CreateAI
    monkeypatch.setattr(mod, "CreateAI", orig)
    yield mod
    _reset_app_state()


def _ship_and_planet(radius, distance):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); ship.SetName("Player")
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ship, "Player")
    planet = Planet_Create(float(radius), "colony.nif")
    planet.SetName("Haven")
    pSet.AddObjectToSet(planet, "Haven")
    ship.SetTranslateXYZ(0.0, float(distance), 0.0)
    return ship, planet


def _circle_script(root):
    return [a for a in root.GetAllAIsInTree()
            if getattr(a, "GetScriptModule", lambda: "")() == "CircleObject"][0] \
        .GetScriptInstance()


def _in_range(root):
    for a in root.GetAllAIsInTree():
        for c in getattr(a, "GetConditions", lambda: [])():
            if c.GetModuleName() == "Conditions.ConditionInRange":
                return c
    raise AssertionError("no ConditionInRange in the tree")


def test_hook_rewrites_circle_distances_and_trigger(orbit_mod):
    assert oa.install(orbit_mod) is True
    ship, planet = _ship_and_planet(1800.0, 5000.0)
    root = orbit_mod.CreateAI(ship, planet)

    circle = _circle_script(root)
    assert (circle.fNearDistance, circle.fFarDistance) == pytest.approx((2070.0, 2142.0))
    assert circle.bUseRoughDistances
    cond = _in_range(root)
    assert cond._instance.fDistance == pytest.approx(2160.0)


def test_unhooked_tree_keeps_bc_values(orbit_mod):
    """Control: the same build without the hook carries BC's stock numbers --
    proves the assertion above is the hook's doing."""
    ship, planet = _ship_and_planet(1800.0, 5000.0)
    root = orbit_mod.CreateAI(ship, planet)
    circle = _circle_script(root)
    assert (circle.fNearDistance, circle.fFarDistance) == pytest.approx((1950.0, 1990.0))
    assert _in_range(root)._instance.fDistance == pytest.approx(2000.0)


def test_new_trigger_takes_effect(orbit_mod):
    """A ship 2100 GU from a R=1800 planet's centre: outside BC's gate (2000)
    but inside ours (2160). The CloseEnough branch must activate and the
    orbit-start event fire -- the new range is live, not just stored."""
    oa.install(orbit_mod)
    ship, planet = _ship_and_planet(1800.0, 2100.0)

    fired = []

    class _Cap:
        def On(self, evt):
            fired.append(evt)
    cap = _Cap()
    wrapper = App.TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(cap)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_AI_ORBITTING, wrapper, "On")

    root = orbit_mod.CreateAI(ship, planet)
    ship.SetAI(root)
    from engine.core.loop import GameLoop
    # The proximity sphere reports inside on its first update, after the
    # first AI decision (FlyToPlanet); the ConditionalAI then re-decides on
    # the AI cadence (up to 4 ticks). Measured: event fires by tick 5.
    GameLoop().advance(30)
    assert _in_range(root).GetStatus() == 1
    assert fired, "ship inside the new trigger but the orbit sequence never started"


def test_install_is_idempotent(orbit_mod):
    assert oa.install(orbit_mod) is True
    wrapped = orbit_mod.CreateAI
    assert oa.install(orbit_mod) is False
    assert orbit_mod.CreateAI is wrapped


def test_unexpected_tree_shape_keeps_values_and_warns_once(caplog):
    """A mod's OrbitPlanet whose tree has no CircleObject leaf: BC's (the
    mod's) values are left alone and exactly one warning is logged."""
    from engine.appc.ai import PlainAI_Create, PriorityListAI_Create
    ship, planet = types.SimpleNamespace(GetName=lambda: "P"), \
        types.SimpleNamespace(GetRadius=lambda: 1800.0, GetName=lambda: "H")
    root = PriorityListAI_Create(None, "Root")
    leaf = PlainAI_Create(None, "Leaf")
    leaf.SetScriptModule("Intercept")
    root.AddAI(leaf, 1)
    fake = types.SimpleNamespace(CreateAI=lambda s, p: root)

    oa.install(fake)
    with caplog.at_level(logging.WARNING, logger="engine.orbit_altitude"):
        out = fake.CreateAI(ship, planet)
    assert out is root
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_missing_create_ai_is_not_installed():
    assert oa.install(types.SimpleNamespace()) is False


def test_bootstrap_installs_the_orbit_hook(monkeypatch):
    """The live host's firing-pipeline bootstrap (where the Helm handlers'
    SDK hooks go in) installs the wrap. Later bootstrap steps may need fuller
    host state, so only their failures are tolerated."""
    from engine import host_loop
    calls = []
    monkeypatch.setattr(oa, "install", lambda module=None: calls.append(module) or True)
    try:
        host_loop._bootstrap_firing_pipeline()
    except Exception:
        pass
    assert calls == [None]
