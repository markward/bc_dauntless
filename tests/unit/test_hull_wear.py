"""Plating wear comes from the real hull damage a hit dealt, into the
per-instance damage store. Projectile and collision wear is sent on every hit
(the store merges co-located hits); only phaser ticks accumulate, in the ship's
BODY frame."""
import gc
import weakref

import pytest

from engine import host_io
from engine.appc import hit_feedback, hull_wear
from engine.appc.math import TGPoint3


@pytest.mark.parametrize("args,expected", [
    (("torpedo", 500.0), 1.0),
    (("torpedo", 1400.0), 1.5),
    (("disruptor", 50.0), 0.25),
    (("collision", 99.0, 1.0), 0.0),
    (("collision", 400.0, 0.0), 0.0),
    (("collision", 250.0, 1.0), 0.5),
    (("torpedo", 0.0), 0.0),
])
def test_wear_for_hit(args, expected):
    assert hull_wear.wear_for_hit(*args) == pytest.approx(expected)


def test_phaser_tick_is_proportional():
    assert hull_wear.wear_for_hit("phaser", 0.28) == pytest.approx(0.28 / 500.0)


class _Hull:
    def GetConditionPercentage(self): return 1.0
    def IsDestroyed(self): return 0


class _Ship:
    def GetHull(self): return _Hull()


class _Pose:
    """Fake instance pose for world_to_body: body = R^T (p - t) / s, R either
    identity or +90 deg about Z."""
    def __init__(self):
        self.t = (0.0, 0.0, 0.0)
        self.s = 0.01
        self.rot_z90 = False

    def to_body(self, iid, p, n):
        d = tuple((p[i] - self.t[i]) / self.s for i in range(3))
        if self.rot_z90:                    # R^T for R = rot_z(+90)
            d = (d[1], -d[0], d[2])
            n = (n[1], -n[0], n[2])
        return d, tuple(n)


@pytest.fixture
def fake(monkeypatch):
    rec = type("Rec", (), {})()
    rec.wear, rec.body_wear, rec.decals = [], [], []
    rec.pose = _Pose()
    monkeypatch.setattr(hit_feedback, "_play_audio", lambda *a, **k: None)
    monkeypatch.setattr("engine.appc.hull_hit_smoke.maybe_emit",
                        lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "world_to_body", rec.pose.to_body)
    monkeypatch.setattr(host_io, "damage_decal_add",
                        lambda *a, **k: rec.decals.append((a, k)))
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: rec.wear.append((a, k)))
    monkeypatch.setattr(host_io, "hull_damage_add_body",
                        lambda *a, **k: rec.body_wear.append((a, k)))
    hull_wear.reset()
    hit_feedback._last_decal_emit.clear()
    yield rec
    hull_wear.reset()
    hit_feedback._last_decal_emit.clear()


@pytest.fixture
def clock(monkeypatch):
    from engine.appc import damage_decals
    c = [0.0]
    monkeypatch.setattr(damage_decals, "current_game_time", lambda: c[0])
    return c


def _hit(ship, *, absorbed_hull=500.0, weapon_type="torpedo",
         point=(1.0, 2.0, 3.0), **kw):
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(*point), normal=TGPoint3(0.0, 1.0, 0.0),
        damage=absorbed_hull, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: 3}, weapon_type=weapon_type, radius=0.2, **kw)


def _phaser(ship, point=(1.0, 2.0, 3.0), absorbed_hull=50.0):
    _hit(ship, weapon_type="phaser", absorbed_hull=absorbed_hull,
         allow_structural_wear=True, point=point)


def _phaser_reach_gu():
    from engine.appc import damage_decals
    return 0.2 * damage_decals.decal_radius_scale(
        damage_decals.weapon_class_for("phaser"))


def test_projectile_wear_is_sent_on_every_hit(fake, clock):
    ship = _Ship()
    for t in (0.0, 0.05, 0.10):      # all three inside one throttle window
        clock[0] = t
        _hit(ship)
    assert len(fake.decals) == 1, "the scorch is throttled"
    assert len(fake.wear) == 3, "wear is not: one send per hit"
    assert sum(a[4] for a, _k in fake.wear) == pytest.approx(3.0)
    assert all(a[5] == 1 for a, _k in fake.wear)
    assert fake.body_wear == []


def test_mixed_phaser_and_torpedo_wear_lands_at_each_hit(fake, clock):
    ship = _Ship()
    _hit(ship, point=(1.0, 2.0, 3.0))                 # torpedo at P1
    clock[0] = 0.05
    _phaser(ship, point=(4.0, 2.0, 3.0))              # phaser tick at P2
    (args, _k), = fake.wear
    assert args[1] == pytest.approx((1.0, 2.0, 3.0)), \
        "torpedo wear lands at the torpedo point"
    assert args[4] == pytest.approx(1.0)
    hull_wear.drain(0.5)
    (bargs, _k), = fake.body_wear
    assert bargs[1] == pytest.approx((400.0, 200.0, 300.0)), \
        "phaser wear lands at the phaser point"
    assert bargs[4] == pytest.approx(0.1)


def test_pending_phaser_wear_is_body_frame(fake, clock):
    ship = _Ship()
    _phaser(ship)                     # t=0: opens the window, flushes itself
    fake.body_wear.clear()
    clock[0] = 0.05
    _phaser(ship)                     # held: body (100, 200, 300)
    assert fake.body_wear == []
    fake.pose.t = (50.0, -20.0, 7.0)  # the ship moves and turns
    fake.pose.rot_z90 = True
    hull_wear.drain(0.5)
    (args, _k), = fake.body_wear
    assert args[0] == 3
    assert args[1] == pytest.approx((100.0, 200.0, 300.0))
    assert args[2] == pytest.approx((0.0, 1.0, 0.0))
    assert args[3] == pytest.approx(_phaser_reach_gu())
    assert args[4] == pytest.approx(0.1)
    assert args[5] == 1
    assert fake.wear == [], "never re-converted through the current pose"


def test_phaser_tick_far_from_pending_flushes_early(fake, clock):
    ship = _Ship()
    _phaser(ship)
    fake.body_wear.clear()
    r = _phaser_reach_gu()
    clock[0] = 0.05
    _phaser(ship, point=(1.0, 2.0, 3.0))                  # pending at A
    clock[0] = 0.06
    _phaser(ship, point=(1.0 + 0.4 * r, 2.0, 3.0))        # within 0.5 r: held
    assert fake.body_wear == []
    clock[0] = 0.07
    _phaser(ship, point=(1.0 + 3.0 * r, 2.0, 3.0))        # beyond: A flushes
    (args, _k), = fake.body_wear
    assert args[1] == pytest.approx((100.0, 200.0, 300.0))
    assert args[4] == pytest.approx(0.2), "both ticks held at A"
    hull_wear.drain(0.5)
    assert len(fake.body_wear) == 2
    assert fake.body_wear[1][0][1] == pytest.approx(
        (100.0 * (1.0 + 3.0 * r), 200.0, 300.0))
    assert fake.body_wear[1][0][4] == pytest.approx(0.1)


def test_pending_phaser_wear_flushes_when_the_window_elapses(fake, clock):
    ship = _Ship()
    _phaser(ship)
    fake.body_wear.clear()
    clock[0] = 0.05
    _phaser(ship)
    hull_wear.drain(0.1)
    assert fake.body_wear == [], "window not yet elapsed"
    hull_wear.drain(0.3)
    (args, _kw), = fake.body_wear
    assert args[4] == pytest.approx(0.1)
    hull_wear.drain(1.0)
    assert len(fake.body_wear) == 1, "sent once"


def test_phaser_wear_flushes_on_the_scorch_emit(fake, clock):
    ship = _Ship()
    _phaser(ship)
    (args, _kw), = fake.body_wear
    assert args[4] == pytest.approx(0.1), "the emitting tick sends its own wear"


def test_stale_instance_drops_phaser_wear(fake, clock, monkeypatch):
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    _phaser(_Ship())
    hull_wear.drain(1.0)
    assert fake.body_wear == []


def test_pending_entry_pins_its_ship_until_sent(fake, clock):
    """The id-reuse guard: a pending entry holds its ship, so id(ship) can
    never be recycled onto a new ship while wear is pending."""
    ship = _Ship()
    _phaser(ship)
    clock[0] = 0.05
    _phaser(ship)                       # pending
    ref = weakref.ref(ship)
    del ship
    gc.collect()
    assert ref() is not None, "pending wear keeps its ship alive"
    hull_wear.drain(0.5)
    gc.collect()
    assert ref() is None, "sent: the ship is released"


def test_a_failing_wear_path_keeps_the_decal_and_severance(fake, monkeypatch):
    from engine.appc import damage_eligibility, part_severance

    def _boom(*a, **k):
        raise RuntimeError("wear binding failed")
    monkeypatch.setattr(host_io, "hull_damage_add", _boom)
    monkeypatch.setattr(damage_eligibility, "is_eligible", lambda s: True)
    severance = []
    monkeypatch.setattr(part_severance, "record_hit",
                        lambda *a, **k: severance.append(a))
    _hit(_Ship())
    assert len(fake.decals) == 1, "the scorch still lands"
    assert len(severance) == 1, "the part attribution still lands"


def test_no_wear_when_shields_absorb_everything(fake):
    _hit(_Ship(), absorbed_hull=0.0)
    assert fake.wear == [] and fake.body_wear == []


def test_no_wear_in_god_mode(fake):
    _hit(_Ship(), persist_decal=False)
    assert fake.wear == [] and fake.body_wear == []


def test_light_phaser_fire_leaves_no_wear(fake):
    _hit(_Ship(), weapon_type="phaser", absorbed_hull=5.0,
         allow_structural_wear=False)
    hull_wear.drain(1.0)
    assert fake.wear == [] and fake.body_wear == []


def test_wear_reach_matches_scorch_reach(fake):
    _hit(_Ship())
    assert fake.wear[0][0][3] == pytest.approx(fake.decals[0][0][3])


def test_wear_reaching_the_store_asks_for_severed_parts(fake, clock, monkeypatch):
    """Projectile wear and a flushed phaser entry both hand the ship to
    hull_breakup.after_wear AFTER the wear is in the store (the native part
    check reads the store)."""
    from engine.appc import hull_breakup
    asked = []
    monkeypatch.setattr(
        hull_breakup, "after_wear",
        lambda ship, iid, *a, **k: asked.append(
            (ship, iid, len(fake.wear), len(fake.body_wear))))
    ship = _Ship()
    _hit(ship)
    assert asked == [(ship, 3, 1, 0)]
    clock[0] = 0.05
    _phaser(ship)                     # opens the phaser window: sent at once
    assert asked[1] == (ship, 3, 1, 1)
    clock[0] = 0.06
    _phaser(ship)                     # held in the body frame
    assert len(asked) == 2
    hull_wear.drain(0.5)
    assert asked[2] == (ship, 3, 1, 2)
