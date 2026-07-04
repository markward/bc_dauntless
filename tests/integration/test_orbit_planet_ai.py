"""AI.Player.OrbitPlanet fires ET_AI_ORBITTING when the orbit AI starts (Layer 4a).

The tree's FIRST step (PlainAI "RunScript" -> StartingOrbit) fires the event as
soon as the CloseEnough branch activates — NOT after a stable orbit is achieved.
CloseEnough is a ConditionalAI gated on ConditionInRange(200 + planet radius),
so in range the Sequence runs (event fires, then CircleObject); out of range the
lower-priority FlyToPlanet (Intercept) branch runs and no event fires.
Event shape: source=ship, destination=planet — E1M2.OrbitingHaven listens as an
instance handler ON the planet, so destination must be the planet.
"""
import pytest

import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ImpulseEngineSubsystem
from engine.appc.planet import Planet_Create
from engine.core.loop import GameLoop


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


class _Capture:
    def __init__(self):
        self.events = []

    def OnOrbitting(self, event):
        self.events.append(event)


def _ship_and_planet(distance):
    """A named ship and a radius-200 planet 'Haven' in one set, `distance`
    GU apart. CloseEnough threshold = 200 + 200 = 400 GU."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = ShipClass(); ship.SetName("Player")
    ship._hull = HullSubsystem("H"); ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(120.0)
    pSet.AddObjectToSet(ship, "Player")

    haven = Planet_Create(200.0, "colony.nif")
    haven.SetName("Haven")
    pSet.AddObjectToSet(haven, "Haven")

    ship.SetTranslateXYZ(0.0, float(distance), 0.0)
    return pSet, ship, haven


def _capture_orbitting():
    cap = _Capture()
    wrapper = App.TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(cap)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_AI_ORBITTING, wrapper, "OnOrbitting")
    return cap


def test_orbit_ai_start_fires_et_ai_orbitting_when_in_range():
    pSet, ship, haven = _ship_and_planet(distance=300.0)   # inside 400
    cap = _capture_orbitting()

    import AI.Player.OrbitPlanet
    ship.SetAI(AI.Player.OrbitPlanet.CreateAI(ship, haven))

    GameLoop().advance(3)

    assert cap.events, "orbit AI started in range but ET_AI_ORBITTING never fired"
    evt = cap.events[0]
    assert evt.GetSource() is ship
    assert evt.GetDestination() is haven


def test_orbit_ai_out_of_range_fires_only_on_arrival():
    """Faithful gating: far from the planet, CloseEnough (ConditionInRange) is
    DORMANT so the AI's first decision picks the FlyToPlanet branch and no
    orbit-start event fires. Once motion runs, Intercept in-system-warps the
    ship to ~295 GU of the target (its default warp distance, inside the 400 GU
    gate) and the event fires on arrival — a distant click means "fly there,
    then orbit", never "instantly orbiting"."""
    pSet, ship, haven = _ship_and_planet(distance=5000.0)  # outside 400
    cap = _capture_orbitting()

    import AI.Player.OrbitPlanet
    root = AI.Player.OrbitPlanet.CreateAI(ship, haven)
    ship.SetAI(root)

    # AI decision only (no motion): the gate must hold.
    from engine.appc.ai_driver import tick_ai
    tick_ai(root, 0.0)
    assert cap.events == []

    # Full loop (AI + motion): Intercept closes the distance; event on arrival.
    GameLoop().advance(5)
    assert cap.events
    assert cap.events[0].GetSource() is ship
    assert cap.events[0].GetDestination() is haven


def test_orbit_ai_sequence_advances_into_circle_object_without_raising():
    """After StartingOrbit reports DONE the Sequence advances to the real SDK
    CircleObject leaf. tick_all_ai does not swallow exceptions, so a crash in
    CircleObject.Update (or the AvoidObstacles preprocessor) would kill the
    live loop every tick — prove a sustained run stays clean."""
    pSet, ship, haven = _ship_and_planet(distance=300.0)
    cap = _capture_orbitting()

    import AI.Player.OrbitPlanet
    ship.SetAI(AI.Player.OrbitPlanet.CreateAI(ship, haven))

    GameLoop().advance(60)   # 1 s of game time; well past the RunScript step

    assert cap.events         # started...
    assert ship.GetAI() is not None   # ...and the tree is still installed
