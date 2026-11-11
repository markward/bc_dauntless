"""A phaser pulse lands on the first object in the beam's path (Python step).

Spec: docs/superpowers/specs/2026-11-11-beam-blocking-design.md section 5.
Shooter at the origin, blocker 50 GU up +Y, target 100 GU up +Y. The native
combat switch is off, so the Python phaser step runs; the mesh trace is faked
(``host_io.ray_trace_mesh``) so each test says what is hit.
"""
import pytest

import App
from engine import host_io, host_loop
from engine.appc import beam_blockers, combat
from engine.appc import native_combat as nc
from engine.appc.planet import Planet
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, PhaserBank, PhaserSystem
from tests.helpers.beams import prime_lit_banks

DT = 1.0 / 60.0
HULL = 1000.0
DAMAGE = 100.0

_events = []


def _on_hit(obj, event):
    _events.append(event)
    obj.CallNextHandler(event)


def _bank(name):
    b = PhaserBank(name)
    b._max_charge = 5.0
    b._charge_level = 5.0
    b._min_firing_charge = 3.0
    b._max_damage = DAMAGE
    b._max_damage_distance = 1000.0
    b._max_condition = 100.0
    b._condition = 100.0
    b._disabled_percentage = 0.25
    return b


class Scene:
    pass


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr(nc, "_switch", False)
    _events.clear()
    s = Scene()
    s.set = App.SetClass_Create()
    App.g_kSetManager.AddSet(s.set, "beam_blocking_py")
    s.hits = {}
    s.instances = {}
    s.planet_instances = {}

    def fake_trace(iid, o, d, max_dist):
        t = s.hits.get(iid)
        if t is None or t > max_dist:
            return None
        return ((o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t),
                (0.0, -1.0, 0.0), t)

    monkeypatch.setattr(host_io, "ray_trace_mesh", fake_trace)
    # The fake instance ids are not native ones: the hit-visual conversion
    # takes its stale-id path (no anchor, no sparks).
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)

    def add(name, at, instance=False):
        ship = ShipClass_Create(name)
        ship.SetTranslateXYZ(*at)
        ship.SetRadius(5.0)
        ship._hull = HullSubsystem("Hull")
        ship._hull.SetMaxCondition(HULL)
        ship._hull.SetCondition(HULL)
        s.set.AddObjectToSet(ship, name)
        if instance:
            s.instances[ship] = len(s.instances) + 1
        return ship

    s.add = add
    s.shooter = add("Shooter", (0.0, 0.0, 0.0))
    s.blocker = add("Blocker", (0.0, 50.0, 0.0), instance=True)
    s.target = add("Target", (0.0, 100.0, 0.0))
    s.hits[s.instances[s.blocker]] = 48.0
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    s.banks = [_bank("Bank0")]
    sys_.AddChildSubsystem(s.banks[0])
    s.shooter.SetPhaserSystem(sys_)
    s.sys = sys_

    def fire():
        s.shooter.SetTarget(s.target)
        sys_.StartFiring(target=s.target)
        prime_lit_banks(sys_)

    s.fire = fire

    def step():
        host_loop._advance_combat(
            [s.shooter, s.blocker, s.target], dt=DT,
            ship_instances=s.instances, planet_instances=s.planet_instances)
        host_loop._combat_tick_boundary()

    s.step = step
    s.hull = lambda ship: ship._hull.GetCondition()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_WEAPON_HIT, s.set, __name__ + "._on_hit")
    try:
        yield s
    finally:
        App.g_kEventManager.RemoveBroadcastHandler(
            App.ET_WEAPON_HIT, s.set, __name__ + "._on_hit")
        beam_blockers.end_step()
        App.g_kSetManager.DeleteSet("beam_blocking_py")


def test_blocker_takes_pulse_target_takes_none(scene):
    scene.fire()
    scene.step()
    assert scene.hull(scene.blocker) < HULL
    assert scene.hull(scene.target) == HULL
    assert _events
    for e in _events:
        assert e.GetDestination() is scene.blocker
        assert e.GetFiringObject() is scene.shooter


def test_line_clears_next_pulse_hits_target(scene):
    scene.fire()
    scene.step()
    assert scene.hull(scene.target) == HULL
    scene.blocker.SetTranslateXYZ(40.0, 50.0, 0.0)
    prime_lit_banks(scene.sys)
    scene.step()
    assert scene.hull(scene.target) < HULL


def test_planet_blocks_silently(scene):
    planet = Planet()
    planet.SetTranslateXYZ(0.0, 50.0, 0.0)
    planet.SetRadius(10.0)
    scene.set.AddObjectToSet(planet, "Rock")
    scene.blocker.SetTranslateXYZ(500.0, 500.0, 0.0)
    scene.fire()
    scene.step()
    assert scene.hull(scene.target) == HULL
    assert scene.hull(scene.blocker) == HULL
    assert not _events


def test_dead_blocker_stops_blocking_same_step(scene, monkeypatch):
    """A ship's death lands over its throes, so the pulse that empties the
    hull is followed by IsDead() only later in real play; here the first
    pulse's hit marks the blocker dead at once (the state a kill leaves),
    and the second bank's pulse, later in the SAME step, must reach the
    target."""
    scene.sys.AddChildSubsystem(_bank("Bank1"))
    real = combat.apply_hit

    def kill_on_hit(ship, *a, **k):
        real(ship, *a, **k)
        if ship is scene.blocker:
            ship.SetDead()

    monkeypatch.setattr(combat, "apply_hit", kill_on_hit)
    scene.blocker._hull.SetCondition(1.0)
    scene.fire()
    assert scene.sys.GetWeapon(0).IsFiring() and scene.sys.GetWeapon(1).IsFiring()
    scene.step()
    assert scene.blocker.IsDead()
    assert scene.hull(scene.target) < HULL


def test_friendly_fire_counts_pulses_not_frames(scene, monkeypatch):
    import MissionLib
    from engine.core.game import Mission
    mission = Mission()
    mission.GetFriendlyGroup().AddName(scene.blocker.GetName())
    monkeypatch.setattr(MissionLib, "GetMission", lambda: mission)
    monkeypatch.setattr(MissionLib, "GetPlayer", lambda: scene.shooter)
    util = App.g_kUtopiaModule
    util.SetFriendlyFireWarningPoints(50.0)
    util.SetFriendlyFireTolerance(1.0e9)
    reports = []
    monkeypatch.setattr(MissionLib, "FriendlyFireWarningHandler",
                        lambda o, e: reports.append(e), raising=False)
    MissionLib.SetupFriendlyFire()
    try:
        scene.fire()
        for _ in range(60):
            scene.step()
        pulses = [e for e in _events if e.GetDamage() > 0]
        assert all(e.GetDestination() is scene.blocker for e in _events)
        assert reports, "ET_FRIENDLY_FIRE_REPORT was never dispatched"
        assert all(r.GetSource() is scene.blocker for r in reports)
        assert 1 <= len(pulses) < 60
        assert util.GetCurrentFriendlyFire() == pytest.approx(
            sum(e.GetDamage() for e in _events))
    finally:
        MissionLib.ShutdownFriendlyFire()


@pytest.mark.parametrize("patched", [False, True])
def test_no_blocker_unchanged(scene, monkeypatch, patched):
    """With nothing in the way the target takes the same pulse as with
    first_blocker patched to always answer None. The pulse is checked
    against its own arithmetic, so the two runs need no shared state."""
    from engine.appc.weapon_subsystems import BEAM_DWELL_FLUSH_S
    if patched:
        monkeypatch.setattr(beam_blockers, "first_blocker",
                            lambda *a, **k: None)
    else:
        scene.blocker.SetTranslateXYZ(500.0, 500.0, 0.0)
    scene.fire()
    scene.step()
    expect = host_loop._phaser_damage_for_tick(
        max_damage=DAMAGE, max_damage_distance=1000.0, dist=100.0,
        dt=BEAM_DWELL_FLUSH_S + 0.1 + DT) * host_loop.PHASER_INTENSITY_SCALE[
            scene.sys.GetPowerLevel()]
    assert HULL - scene.hull(scene.target) == pytest.approx(expect)
    assert scene.hull(scene.blocker) == HULL
