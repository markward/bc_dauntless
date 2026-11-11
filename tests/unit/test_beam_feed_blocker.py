"""The drawn phaser beam ends where the damage lands (spec
docs/superpowers/specs/2026-11-11-beam-blocking-design.md §2 goal 3, §7
case 11).

The scene is Task 2's (tests/integration/test_beam_blocking_python.py):
shooter at the origin, blocker 50 GU up +Y, target 100 GU up +Y, in the
viewed set. The native combat switch is off, so the Python phaser step runs
and `host_loop._phaser_contact` (spied) receives the contact it lands; then
the native beam feed (native_combat.beam_feed, no Python copy) draws the
same bank. Headless the native mesh trace never hits, so the blocker is a
shielded ship with a seeded hull box: it blocks at its shield bubble, as in
tests/unit/test_native_k2_blocker.py.

The feed's readback (`phaser_beams_debug`) holds float32, so the damage
contact is rounded through float32 (native_render_feeds.f32) before the
1e-6 compare.
"""
import pytest

import App  # noqa: F401
from engine import host_loop
from engine.appc import beam_blockers
from engine.appc import native_combat as nc
from engine.appc.planet import Planet
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import (
    HullSubsystem, PhaserBank, PhaserSystem, ShieldSubsystem)
from engine.systems import frames
from tests.helpers import native_render_feeds
from tests.helpers.beams import prime_lit_banks
from tests.helpers.native_on import native_combat_on  # noqa: F401  (fixture)
from tests.helpers.native_render_feeds import beam_dict, f32
from tests.helpers.viewed_set import viewed  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("native_combat_on")

DT = 1.0 / 60.0
HULL = 1000.0
SHIELD = 1000.0
DAMAGE = 100.0
TOL = 1e-6


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


class _HiddenByScript(ShipClass):
    """A mod's ship class whose IsHidden is its own (the mirror's `_hidden`
    says visible): only Python may decide it as a blocker candidate."""

    def IsHidden(self):
        return 1


class Scene:
    pass


@pytest.fixture
def scene(viewed, monkeypatch):
    # The Python phaser step (the mirror stays live: the feed reads it).
    monkeypatch.setattr(nc, "_switch", False)
    frames.reset_render_origin()
    s = Scene()
    s.set = viewed
    s.contacts = []
    real = host_loop._phaser_contact

    def spy(*a, **k):
        # (ship, sys_, bank, target, dist, dt, flush_dwell, level,
        #  impact_point, impact_normal, bubble_entry, ship_instances)
        s.contacts.append((a[2], a[3], a[8], a[10]))
        return real(*a, **k)

    monkeypatch.setattr(host_loop, "_phaser_contact", spy)

    def add(name, at, shielded=False, box=4.0):
        ship = ShipClass_Create(name)
        ship.SetTranslateXYZ(*at)
        ship.SetRadius(5.0)
        ship._hull = HullSubsystem("Hull")
        ship._hull.SetMaxCondition(HULL)
        ship._hull.SetCondition(HULL)
        ss = ShieldSubsystem("Shield Generator")
        for f in range(ShieldSubsystem.NUM_SHIELDS):
            ss.SetMaxShields(f, SHIELD)
        ship.SetShieldSubsystem(ss)
        if shielded:
            ship._shield_hull_box = ((0.0, 0.0, 0.0), (box, box, box))
        s.set.AddObjectToSet(ship, name)
        return ship

    s.shooter = add("Shooter", (0.0, 0.0, 0.0))
    s.blocker = add("Blocker", (0.0, 50.0, 0.0), shielded=True)
    s.target = add("Target", (0.0, 100.0, 0.0))
    s.ships = [s.shooter, s.blocker, s.target]
    s.planet_instances = {}
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    s.bank = _bank("Bank0")
    sys_.AddChildSubsystem(s.bank)
    s.shooter.SetPhaserSystem(sys_)
    s.sys = sys_

    def fire():
        s.shooter.SetTarget(s.target)
        sys_.StartFiring(target=s.target)
        assert prime_lit_banks(sys_) > 0

    def step():
        host_loop._advance_combat(
            list(s.ships), dt=DT, ship_instances=None,
            planet_instances=s.planet_instances)
        host_loop._combat_tick_boundary()

    def feed():
        """The feed over the step's ships: the phaser dicts drawn."""
        nc.reset_beam_feed_counts()
        assert nc.beam_feed(list(s.ships), None,
                            planet_instances=s.planet_instances) is True
        return [beam_dict(r) for r in nc._h.phaser_beams_debug()]

    s.fire, s.step, s.feed = fire, step, feed
    try:
        yield s
    finally:
        beam_blockers.end_step()
        native_render_feeds.clear()


def _render(p):
    """A set-local point in render space (the viewed set is the scene's)."""
    o = frames.render_origin()
    return (p.x - o[0], p.y - o[1], p.z - o[2])


def _assert_ends_at(beams, want):
    assert len(beams) == 2, beams           # outer shell, inner core
    for d in beams:
        for got, w in zip(d["target"], want):
            assert got == pytest.approx(f32(w), abs=TOL), (d["target"], want)


def test_feed_end_matches_damage_contact(scene):
    scene.fire()
    scene.step()
    assert scene.contacts, "the Python step landed no contact"
    bank, target, impact, bubble = scene.contacts[-1]
    assert bank is scene.bank
    assert target is scene.blocker, "premise: the blocker took the contact"
    assert bubble is not None, "premise: met at the blocker's bubble"
    assert scene.bank.IsFiring()
    beams = scene.feed()
    want = _render(bubble if bubble is not None else impact)
    _assert_ends_at(beams, want)
    assert want[1] < 50.0          # short of the blocker's centre
    assert nc.beam_feed_counts()["skips"]["blocker"] == 0


def test_feed_ends_on_planet_where_the_step_stopped(scene, monkeypatch):
    """A planet (no renderer instance: its sphere) between: the Python step
    stops the bank there with no contact; the drawn beam ends on the point
    first_blocker returned."""
    planet = Planet()
    planet.SetTranslateXYZ(0.0, 30.0, 0.0)
    planet.SetRadius(10.0)
    scene.set.AddObjectToSet(planet, "Rock")
    stops = []
    real = beam_blockers.first_blocker

    def spy(*a, **k):
        b = real(*a, **k)
        stops.append(b)
        return b

    monkeypatch.setattr(beam_blockers, "first_blocker", spy)
    scene.fire()
    scene.step()
    assert stops and stops[-1] is not None and stops[-1].kind == "planet"
    assert not scene.contacts
    beams = scene.feed()
    _assert_ends_at(beams, _render(stops[-1].point))


def test_feed_passes_through_a_hidden_planet(scene):
    """Spec section 4.1: a hidden planet in front of the blocker never
    blocks. The step lands its contact on the blocker, and the drawn beam
    ends there too (the planet row's hidden flag), with no "blocker" skip."""
    planet = Planet()
    planet.SetTranslateXYZ(0.0, 30.0, 0.0)
    planet.SetRadius(10.0)
    planet.SetHidden(1)
    scene.set.AddObjectToSet(planet, "Rock")
    scene.fire()
    scene.step()
    assert scene.contacts, "the Python step landed no contact"
    _bank_, target, impact, bubble = scene.contacts[-1]
    assert target is scene.blocker, "premise: the hidden planet let it by"
    beams = scene.feed()
    _assert_ends_at(beams, _render(bubble if bubble is not None else impact))
    assert nc.beam_feed_counts()["skips"]["blocker"] == 0


def test_candidate_only_python_may_decide_keeps_the_target_end(scene):
    """The blocker's class overrides IsHidden (the mirror cannot know it):
    the feed has no Python fallback, so the beam is drawn to its target's
    endpoint and one "blocker" skip is counted."""
    scene.blocker.__class__ = _HiddenByScript
    nc.reclassify(scene.blocker)
    scene.fire()
    beams = scene.feed()
    _assert_ends_at(beams, _render(scene.target.GetWorldLocation()))
    assert nc.beam_feed_counts()["skips"]["blocker"] == 1


def test_push_passes_planet_instances_to_the_feed(monkeypatch):
    seen = {}

    def fake_feed(ships, ship_instances, **kw):
        seen.update(kw)
        return True

    monkeypatch.setattr(nc, "beam_feed", fake_feed)
    monkeypatch.setattr(nc, "torpedo_feed", lambda *a, **k: True)
    pi = {}
    host_loop._push_combat_render_data([], ship_instances=None,
                                       planet_instances=pi)
    assert seen.get("planet_instances") is pi
