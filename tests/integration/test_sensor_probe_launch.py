"""Sensor-model sub-project 4 end to end: the REAL Science Launch Probe path
(SDK ScienceMenuHandlers -> ShipScriptActions.LaunchObject, no emission
recorder) spawns a probe that the player's sensors count and see through; and
E6M4's probe goal registers the launched probe and fires its planet proximity
check (2026-10-07-sensor-probes-design.md).

Harness notes (Task 4, Step 1):
- E6M4's player is a Sovereign (`CreatePlayerShip("Sovereign", ...)`) whose
  hardpoint carries an OEP_PROBE ObjectEmitterProperty ("Probe Launcher") and
  `SetMaxProbes(10)`; the count is seeded to 10 at load.
- `engine/appc/emission.py`'s recording LaunchObject hook is harness-only
  (`tools/mission_harness.install_emission_recorder`); the fixture asserts the
  SDK's own `LaunchObject` is the one that runs, as production leaves it.
- Headless, the Science menu's only ET_LAUNCH_PROBE handler is
  `Bridge.ScienceMenuHandlers.LaunchProbe` (Miguel's
  `ScienceCharacterHandlers.LaunchProbe` replaces it only in the live bridge,
  via `AttachMenuToScience`). The button path is reproduced by sending
  ET_LAUNCH_PROBE to that menu through the event manager, which also runs the
  broadcast handlers (E6M4's `ProbeLaunched`) exactly as a click does.
"""
import App
import MissionLib
import pytest

from engine.appc import sensor_occlusion
from engine.appc.sensor_detection import can_detect, effective_sensor_range
from tests.helpers import headless_mission

E6M4 = "Maelstrom.Episode6.E6M4.E6M4"


def _launch(player):
    """Fire the real launch and let its 0.5 s delayed action run."""
    import Bridge.ScienceMenuHandlers as smh
    seq = smh.MakeLaunchProbeAction(None, player.GetObjID())
    if seq is not None and hasattr(seq, "Play"):
        seq.Play()
    headless_mission.tick(1.0)


def _press_launch_probe():
    """What the Science menu's Launch Probe button does: ET_LAUNCH_PROBE to
    the Science menu through the event manager (instance chain + broadcast)."""
    import Bridge.BridgeUtils as BridgeUtils
    menu = BridgeUtils.GetBridgeMenu("Science")
    assert menu is not None
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_LAUNCH_PROBE)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)


@pytest.fixture
def e6m4_player():
    mission, episode, game, mod = headless_mission.load(E6M4)
    import Actions.ShipScriptActions as ssa
    # The REAL SDK LaunchObject, not engine/appc/emission.py's recorder --
    # checked as the production path leaves it, with no sys.modules surgery.
    assert ssa.LaunchObject.__module__ == "Actions.ShipScriptActions"
    player = MissionLib.GetPlayer()
    assert player is not None
    sensor_occlusion.set_enabled(False)
    return mod, player


def test_launch_spawns_a_counted_listed_probe(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    pSet = player.GetContainingSet()
    before = sensors.GetNumProbes()
    assert before > 0
    sensors.SetNumProbes(before - 1)         # LaunchProbe decrements before the action
    _launch(player)
    probes = sensors.probes()
    assert len(probes) == 1
    probe = probes[0]
    assert probe.GetContainingSet() is pSet
    assert probe.GetName().startswith("Probe ")
    v = probe.GetVelocityTG()
    assert (v.x * v.x + v.y * v.y + v.z * v.z) > 0.0
    assert can_detect(player, probe) is True
    # The probe must actually MOVE at that velocity, not just report it --
    # ShipScriptActions.PushObject only ever calls SetVelocity, and the
    # probe has no AI/helm setpoints, so it only moves if something besides
    # the setpoint ramp integrates a bare SetVelocity (engine.appc.drift).
    speed = (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5
    p0 = probe.GetTranslate()
    headless_mission.tick(2.0)
    p1 = probe.GetTranslate()
    dist = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 + (p1.z - p0.z) ** 2) ** 0.5
    assert dist == pytest.approx(speed * 2.0, rel=0.05)


def test_launch_probe_handler_decrements_the_count(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    before = sensors.GetNumProbes()
    _press_launch_probe()
    headless_mission.tick(1.0)
    assert sensors.GetNumProbes() == before - 1
    assert len(sensors.probes()) == 1


def test_launch_with_no_probes_left_spawns_nothing(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    sensors.SetNumProbes(0)
    _press_launch_probe()
    headless_mission.tick(1.0)
    assert sensors.GetNumProbes() == 0
    assert sensors.probes() == []


def test_launched_probe_sees_a_ship_beyond_player_range(e6m4_player):
    mod, player = e6m4_player
    sensors = player.GetSensorSubsystem()
    sensors.SetNumProbes(sensors.GetNumProbes() - 1)
    _launch(player)
    probe = sensors.probes()[0]
    r = effective_sensor_range(player)
    p = probe.GetWorldLocation()
    q = player.GetWorldLocation()
    # A ship placed on the far side of the probe: beyond player range, 300 GU from the probe.
    dx, dy, dz = p.x - q.x, p.y - q.y, p.z - q.z
    n = (dx * dx + dy * dy + dz * dz) ** 0.5 or 1.0
    from engine.appc.ships import ShipClass_Create
    far = ShipClass_Create("BirdOfPrey")
    far.SetTranslateXYZ(q.x + dx / n * (r + 300.0), q.y + dy / n * (r + 300.0), q.z + dz / n * (r + 300.0))
    probe.SetTranslateXYZ(q.x + dx / n * r, q.y + dy / n * r, q.z + dz / n * r)
    player.GetContainingSet().AddObjectToSet(far, "FarBird")
    assert can_detect(player, far) is True
    probe.GetContainingSet().RemoveObjectFromSet(probe.GetName())
    assert can_detect(player, far) is False


def _warp_to_tezle1(mod):
    """The mission's own way in: Set Course Tezle 1 and Warp. E6M4's
    EnterSet -> TrackPlayer then clears g_bPlayerNotInTezle1, which
    ProbeReachesPlanet requires."""
    player = MissionLib.GetPlayer()
    btn = headless_mission.the_warp_button()
    headless_mission.plot_course(btn, "Systems.Tezle.Tezle1")
    headless_mission.warp_and_wait(btn, player)
    player = MissionLib.GetPlayer()
    assert player.GetContainingSet().GetName() == "Tezle1"
    assert mod.g_bPlayerArriveTezle1 and not mod.g_bPlayerNotInTezle1
    return player


def _tezle_1():
    return App.Planet_GetObject(App.g_kSetManager.GetSet("Tezle1"), "Tezle 1")


def _dist(a, b):
    p, q = a.GetWorldLocation(), b.GetWorldLocation()
    return ((p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2) ** 0.5


def _launch_in_tezle1(mod):
    player = _warp_to_tezle1(mod)
    sensors = player.GetSensorSubsystem()
    _press_launch_probe()
    headless_mission.tick(1.0)
    probes = sensors.probes()
    assert len(probes) == 1
    return player, probes[0]


def test_e6m4_registers_the_probe_and_closes_on_tezle_1(e6m4_player):
    """Drive E6M4's own ProbeLaunched handler with a real launch in Tezle1.

    Only the REGISTRATION half can be proven inside the 300 s game-time
    bound, plus that the probe is genuinely closing on the planet under the
    mission's Intercept AI. Why the reach half cannot pass headlessly in
    300 s: the warp in (no placement linked yet) lands the player ~4670 GU
    from Tezle 1's centre; the inner check is radius + 5 = 2005 GU; the
    probe's Intercept AI caps it at its hull's MaxSpeed of 8 GU/s, so it
    needs ~2665 / 8 = ~333 s. Measured 2026-10-07: closest approach after
    300 s of ticks was 2278.6 GU from the centre (273.6 GU short of the
    2005 GU inner radius), closing at a steady 8.0 GU/s. The proximity half
    is proven separately by
    test_e6m4_inner_check_fires_for_the_registered_probe."""
    mod, player = e6m4_player
    player, probe = _launch_in_tezle1(mod)

    # Registration: E6M4.ProbeLaunched saw the real launch event.
    assert probe.GetName() in mod.g_lProbeNames
    assert mod.g_bProbeExists
    assert probe.GetAI() is not None
    assert not mod.g_bProbeReachedPlanet

    planet = _tezle_1()
    start = _dist(probe, planet)
    closest = start
    for _ in range(299):                     # 299 s of game time, 1 s steps
        headless_mission.tick(1.0)
        closest = min(closest, _dist(probe, planet))
        if mod.g_bProbeReachedPlanet:
            break
    # The probe flies at Tezle 1 under E6M4's AI: >2000 GU closer in 299 s.
    assert start - closest > 2000.0


def test_e6m4_inner_check_fires_for_the_registered_probe(e6m4_player):
    """The reach half: the probe E6M4 registered, once within Tezle 1's
    radius + 5, trips the mission's inner ProximityCheck ->
    InnerPlanetProximity -> ProbeReachesPlanet. The probe is moved along its
    own line to the planet for the last stretch (its flight needs ~333 s,
    over the 300 s test bound -- see the test above)."""
    mod, player = e6m4_player
    player, probe = _launch_in_tezle1(mod)
    assert probe.GetName() in mod.g_lProbeNames

    planet = _tezle_1()
    c, p = planet.GetWorldLocation(), probe.GetWorldLocation()
    dx, dy, dz = p.x - c.x, p.y - c.y, p.z - c.z
    n = (dx * dx + dy * dy + dz * dz) ** 0.5
    inside = planet.GetRadius() + 4.0
    probe.SetTranslateXYZ(c.x + dx / n * inside, c.y + dy / n * inside,
                          c.z + dz / n * inside)
    headless_mission.tick_until(lambda: mod.g_bProbeReachedPlanet, bound_s=10.0)
    assert mod.g_bProbeReachedPlanet
