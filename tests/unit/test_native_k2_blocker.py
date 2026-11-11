"""K2 phasers stop on the first object in their path: native equals Python.

Spec docs/superpowers/specs/2026-11-11-beam-blocking-design.md §5 (the K2
kernel's BLOCK state; k2_beams.h, THE BLOCKER). Each test builds the same
seeded scene twice -- native combat on (the K2 kernel walks `cb.phasers` and
asks Python only what it cannot answer) and off (host_loop's Python step) --
runs the whole combat step for a number of ticks, and compares with `==`:

- the ordered (destination, firing object, damage.hex()) of every captured
  ET_WEAPON_HIT, and every hit's presentation (hit_feedback.present: its
  ship, point and shield point by .hex(), and whether the shield point IS
  the point -- a blocker met at its bubble with no mesh normal), and
- every ship's hull condition and shield faces (by .hex()).

Headless the native mesh trace never hits, so the blockers are shielded
ships with a seeded hull box (they block at their bubble) and planets with
no renderer instance (they block at their sphere).
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_next"),
    reason="native K2 bindings not built")

from engine import host_loop  # noqa: E402
from engine.appc import beam_blockers  # noqa: E402
from engine.appc import hit_feedback  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import object_lifetime, ship_death  # noqa: E402
from engine.appc import passive_state  # noqa: E402
from engine.appc.objects import DamageableObject  # noqa: E402
from engine.appc.planet import Planet  # noqa: E402
from engine.appc.ships import ShipClass, ShipClass_Create  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    HullSubsystem, PhaserBank, PhaserSystem, ShieldSubsystem)
from tests.helpers.beams import prime_lit_banks  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0
HULL = 1000.0
SHIELD = 1000.0
DAMAGE = 100.0
TICKS = 45

_events = []
_presents = []


def _on_hit(obj, event):
    dest, firing = event.GetDestination(), event.GetFiringObject()
    _events.append((None if dest is None else dest.GetName(),
                    None if firing is None else firing.GetName(),
                    float(event.GetDamage()).hex()))
    obj.CallNextHandler(event)


def _hx3(p):
    return None if p is None else tuple(float(c).hex() for c in (p.x, p.y, p.z))


@pytest.fixture(autouse=True)
def _switch(monkeypatch):
    nc.reset()
    passive_state.reset()
    present = hit_feedback.present

    def present_spy(**kw):
        sp, point = kw.get("shield_point"), kw.get("point")
        _presents.append((kw["ship"].GetName(), _hx3(point), _hx3(sp),
                          sp is not None and sp is point))
        return present(**kw)
    monkeypatch.setattr(hit_feedback, "present", present_spy)
    yield
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    beam_blockers.end_step()
    nc.reset()
    passive_state.reset()


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


class _ShieldedProp(DamageableObject):
    """A non-ShipClass object with a real GetShields: the case the native
    blocker cannot answer (beam_block.h, NeedPython), so the kernel ASKs."""

    def GetShields(self):
        return None

    def GetPhaserSystem(self):
        return None


class _CloakedByScript(ShipClass):
    """A mod's ship class whose IsHidden is its own: the mirror's `_hidden`
    says visible, the Python says hidden (THE BLOCKER, CLASS OVERRIDES)."""

    def IsHidden(self):
        return 1


class Scene:
    """One set, ships added in step order, ET_WEAPON_HIT captured."""

    def __init__(self, native, tag):
        nc.reset()
        passive_state.reset()
        if native:
            nc.configure(ON)
            assert nc.enabled()
        self.native = native
        self.tag = tag
        self.set = App.SetClass_Create()
        App.g_kSetManager.AddSet(self.set, tag)
        self.ships = []
        self.shooters = []
        self.planet_instances = {}
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_WEAPON_HIT, self.set, __name__ + "._on_hit")

    def add(self, name, at, shielded=False, box=4.0, hull=HULL,
            shield=SHIELD):
        """A ship with a hull and full shields (so no pulse reaches a
        subsystem: a death's timing is not what these tests compare, unless
        a test sets `shield` to 0). `shielded`: a hull box too, so a beam
        meets its shield bubble."""
        ship = ShipClass_Create(name)
        ship.SetTranslateXYZ(*at)
        ship.SetRadius(5.0)
        ship._hull = HullSubsystem("Hull")
        ship._hull.SetMaxCondition(hull)
        ship._hull.SetCondition(hull)
        ss = ShieldSubsystem("Shield Generator")
        for f in range(ShieldSubsystem.NUM_SHIELDS):
            ss.SetMaxShields(f, shield)
        ship.SetShieldSubsystem(ss)
        if shielded:
            ship._shield_hull_box = ((0.0, 0.0, 0.0), (box, box, box))
        self.set.AddObjectToSet(ship, name)
        self.ships.append(ship)
        return ship

    def arm(self, shooter, target, banks=1):
        sys_ = PhaserSystem("Phasers")
        sys_._max_condition = 100.0
        sys_._condition = 100.0
        sys_._disabled_percentage = 0.75
        sys_.TurnOn()
        for i in range(banks):
            sys_.AddChildSubsystem(_bank("Bank%d" % i))
        shooter.SetPhaserSystem(sys_)
        self.shooters.append((shooter, sys_, target))

    def fire(self):
        for shooter, sys_, target in self.shooters:
            shooter.SetTarget(target)
            sys_.StartFiring(target=target)
            assert prime_lit_banks(sys_) > 0

    def run(self, ticks=TICKS):
        _events.clear()
        _presents.clear()
        self.fire()
        for _ in range(ticks):
            host_loop._advance_combat(
                list(self.ships), dt=DT, ship_instances=None,
                planet_instances=self.planet_instances)
            host_loop._combat_tick_boundary()
        self.counts = nc.counts()
        events = list(_events)
        totals = []
        for s in self.ships:
            hull = getattr(s, "_hull", None)
            row = [s.GetName(),
                   None if hull is None else float(hull.GetCondition()).hex()]
            shields = s.GetShields() if isinstance(s.GetShields(),
                                                   ShieldSubsystem) else None
            if shields is not None:
                row.append(tuple(
                    float(shields.GetCurShields(f)).hex()
                    for f in range(ShieldSubsystem.NUM_SHIELDS)))
            totals.append(tuple(row))
        return events, (totals, list(_presents))

    def close(self):
        App.g_kEventManager.RemoveBroadcastHandler(
            App.ET_WEAPON_HIT, self.set, __name__ + "._on_hit")
        App.g_kSetManager.DeleteSet(self.tag)
        _events.clear()


def _fresh_arm():
    """The same start for each arm: both RNGs seeded (App.g_kSystemWrapper's
    own, which the death cascade's blasts draw, and the module `random`) and
    no dying ship or timed object left over from an earlier arm or test."""
    App.g_kSystemWrapper.SetRandomSeed(0)
    random.seed(0)
    ship_death.reset()
    object_lifetime.reset()


def _both(build, ticks=TICKS):
    """(python events, python totals, native events, native totals, native
    counts) for the scene `build(scene)` makes."""
    out = []
    for native in (False, True):
        _fresh_arm()
        s = Scene(native, "k2_blocker_%s" % ("nat" if native else "py"))
        try:
            build(s)
            events, totals = s.run(ticks)
            out.append((events, totals, s.counts))
        finally:
            s.close()
    (pe, pt, _pc), (ne, nt, nc_counts) = out
    return pe, pt, ne, nt, nc_counts


def _native_ran(counts):
    assert counts.get("k2_records", 0) > 0, counts
    assert counts.get("k2_python_steps", 0) == 0, counts


def _shooter_blocker_target(s, blocker_at=(0.0, 50.0, 0.0)):
    shooter = s.add("Shooter", (0.0, 0.0, 0.0))
    blocker = s.add("Blocker", blocker_at, shielded=True)
    target = s.add("Target", (0.0, 100.0, 0.0))
    s.arm(shooter, target)
    return shooter, blocker, target


def test_shielded_blocker_native_equals_python():
    pe, pt, ne, nt, counts = _both(_shooter_blocker_target)
    assert pe, "the Python step landed no hit"
    assert {e[0] for e in pe} == {"Blocker"}, pe
    assert any(float.fromhex(e[2]) > 0.0 for e in pe), pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] == 0, counts
    assert counts["k2_blocked"]["ship"] > 0, counts


def test_planet_blocker_native_equals_python():
    def build(s):
        _shooter_blocker_target(s, blocker_at=(500.0, 500.0, 0.0))
        planet = Planet()
        planet.SetTranslateXYZ(0.0, 50.0, 0.0)
        planet.SetRadius(10.0)
        s.set.AddObjectToSet(planet, "Rock")

    pe, pt, ne, nt, counts = _both(build)
    assert pe == [], pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] == 0, counts
    assert counts["k2_blocked"]["planet"] > 0, counts


def test_hidden_planet_never_blocks_native_equals_python():
    """Spec section 4.1: a hidden planet in the line never blocks. The
    feeder carries planet.IsHidden() in the planet row (_k2_planet_rows),
    so the kernel skips it without an ASK and the target takes the hits."""
    def build(s):
        _shooter_blocker_target(s, blocker_at=(500.0, 500.0, 0.0))
        planet = Planet()
        planet.SetTranslateXYZ(0.0, 50.0, 0.0)
        planet.SetRadius(10.0)
        planet.SetHidden(1)
        s.set.AddObjectToSet(planet, "Rock")

    pe, pt, ne, nt, counts = _both(build)
    assert pe and {e[0] for e in pe} == {"Target"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] == 0, counts
    assert counts["k2_blocked"] == {"ship": 0, "planet": 0}, counts


def test_two_banks_one_blocker_native_equals_python():
    def build(s):
        left = s.add("Left", (-10.0, 0.0, 0.0))
        right = s.add("Right", (10.0, 0.0, 0.0))
        s.add("Blocker", (0.0, 50.0, 0.0), shielded=True, box=8.0)
        target = s.add("Target", (0.0, 100.0, 0.0))
        s.arm(left, target)
        s.arm(right, target)

    pe, pt, ne, nt, counts = _both(build)
    assert {e[1] for e in pe} == {"Left", "Right"}, pe
    assert {e[0] for e in pe} == {"Blocker"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_blocked"]["ship"] > 0, counts


def test_blocker_ask_path():
    def build(s):
        _shooter_blocker_target(s)
        prop = _ShieldedProp()
        prop.SetTranslateXYZ(300.0, 0.0, 0.0)
        prop.SetRadius(5.0)
        s.set.AddObjectToSet(prop, "Prop")
        s.ships.append(prop)

    pe, pt, ne, nt, counts = _both(build)
    assert pe and {e[0] for e in pe} == {"Blocker"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] > 0, counts
    assert counts["k2_blocked"]["ship"] > 0, counts


def test_overridden_is_hidden_candidate_asks():
    """A shielded ship in the line whose class says IsHidden() while its
    mirrored `_hidden` is False: the Python skips it, so the native walk
    must not decide it from the mirror -- it ASKs, and the target takes the
    hits in both arms."""
    def build(s):
        _shooter_blocker_target(s)
        blocker = s.ships[1]
        blocker.__class__ = _CloakedByScript
        nc.reclassify(blocker)

    pe, pt, ne, nt, counts = _both(build)
    assert pe and {e[0] for e in pe} == {"Target"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] > 0, counts
    assert counts["k2_blocked"] == {"ship": 0, "planet": 0}, counts


def test_no_blocker_records_unchanged():
    """Ruling P2: with the would-be blocker far off the line, nothing is in
    the way: native equals Python, no blocker ASK, the target takes the
    hits."""
    pe, pt, ne, nt, counts = _both(
        lambda s: _shooter_blocker_target(s, blocker_at=(500.0, 500.0, 0.0)))
    assert pe and {e[0] for e in pe} == {"Target"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
    assert counts["k2_ask_queries"]["blocker"] == 0, counts
    assert counts["k2_blocked"] == {"ship": 0, "planet": 0}, counts


def test_unshielded_pair_native_equals_python():
    """No shields, so every pulse reaches the hull and the subsystems and
    the death cascade draws App.g_kSystemWrapper's RNG: the two arms agree
    only because _both seeds the RNGs and clears the death registries
    before each (an unseeded harness drew different numbers in the native
    arm, the old "native 20 vs Python 9" reading)."""
    def build(s):
        shooter = s.add("Shooter", (0.0, 0.0, 0.0), hull=100000.0,
                        shield=0.0)
        target = s.add("Target", (0.0, 100.0, 0.0), hull=100000.0,
                       shield=0.0)
        s.arm(shooter, target)

    pe, pt, ne, nt, counts = _both(build, ticks=200)
    assert pe and {e[0] for e in pe} == {"Target"}, pe
    assert ne == pe
    assert nt == pt
    _native_ran(counts)
