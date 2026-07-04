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
    orbit-start event fires. Once motion runs, Intercept turns the ship onto
    the target (the in-system warp's facing gate), cruises the warp transit to
    ~295 GU of the target (Intercept's default drop distance, inside the
    400 GU gate), and the event fires on arrival — a distant click means
    "turn, fly there, then orbit", never "instantly orbiting"."""
    pSet, ship, haven = _ship_and_planet(distance=5000.0)  # outside 400
    cap = _capture_orbitting()

    import AI.Player.OrbitPlanet
    root = AI.Player.OrbitPlanet.CreateAI(ship, haven)
    ship.SetAI(root)

    # AI decision only (no motion): the gate must hold.
    from engine.appc.ai_driver import tick_ai
    tick_ai(root, 0.0)
    assert cap.events == []

    # Full loop (AI + motion): the ship starts facing +Y, the planet is at
    # -Y — a 180° turn precedes the warp, then the transit flies ~4700 GU.
    # 300 ticks = 5 s covers both comfortably at this rig's fallback rates.
    GameLoop().advance(300)
    assert cap.events
    assert cap.events[0].GetSource() is ship
    assert cap.events[0].GetDestination() is haven


def test_orbit_ai_flies_player_while_player_control_runs():
    """Layer 4b core regression: the idle _PlayerControl used to zero the
    player's velocity every frame and skip translation, freezing the ship in
    place (rotating but never moving) the moment a helm AI was installed.
    Run the real loop AND the per-frame player-control pass together — the
    ship must genuinely move under the orbit AI, with a live velocity."""
    from engine.host_loop import _PlayerControl, _NO_INPUT

    pSet, ship, haven = _ship_and_planet(distance=350.0)   # inside 400 gate
    import AI.Player.OrbitPlanet
    ship.SetAI(AI.Player.OrbitPlanet.CreateAI(ship, haven))

    pc = _PlayerControl()
    loop = GameLoop()
    start = ship.GetTranslate()
    p0 = (start.x, start.y, start.z)
    for _ in range(120):                                   # 2 s of game time
        loop.tick()
        pc.apply(ship, 1.0 / 60.0, _NO_INPUT)              # per-frame input pass

    p = ship.GetTranslate()
    moved = ((p.x - p0[0]) ** 2 + (p.y - p0[1]) ** 2 + (p.z - p0[2]) ** 2) ** 0.5
    assert moved > 1.0, "player ship never translated under the orbit AI"
    v = ship.GetVelocity()
    speed = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5
    assert speed > 0.0, "player velocity was zeroed by the idle player control"
    assert ship.GetAI() is not None


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
