"""Plating wear comes from the real hull damage a hit dealt, summed across
the scorch throttle, into the per-instance damage store."""
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


@pytest.fixture
def fake(monkeypatch):
    rec = type("Rec", (), {"wear": [], "decals": []})()
    monkeypatch.setattr(hit_feedback, "_play_audio", lambda *a, **k: None)
    monkeypatch.setattr("engine.appc.hull_hit_smoke.maybe_emit",
                        lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add",
                        lambda *a, **k: rec.decals.append((a, k)))
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: rec.wear.append((a, k)))
    hull_wear.reset()
    hit_feedback._last_decal_emit.clear()
    yield rec
    hull_wear.reset()
    hit_feedback._last_decal_emit.clear()


def _hit(ship, *, absorbed_hull=500.0, weapon_type="torpedo", **kw):
    hit_feedback.dispatch(
        ship=ship, source=None,
        point=TGPoint3(1.0, 2.0, 3.0), normal=TGPoint3(0.0, 1.0, 0.0),
        damage=absorbed_hull, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: 3}, weapon_type=weapon_type, radius=0.2, **kw)


def test_throttled_hits_still_accumulate_wear(fake, monkeypatch):
    from engine.appc import damage_decals
    clock = [0.0]
    monkeypatch.setattr(damage_decals, "current_game_time", lambda: clock[0])
    ship = _Ship()
    _hit(ship)                       # t=0 opens the window: its own 1.0 flushes
    fake.wear.clear()
    for t in (0.05, 0.10, 0.25):     # two inside the window, one past it
        clock[0] = t
        _hit(ship)
    assert len(fake.decals) == 2
    assert len(fake.wear) == 1, "the volley is summed into ONE record"
    args, _kw = fake.wear[0]
    assert args[4] == pytest.approx(3.0)
    assert args[5] == 1


def test_no_wear_when_shields_absorb_everything(fake):
    _hit(_Ship(), absorbed_hull=0.0)
    assert fake.wear == []


def test_no_wear_in_god_mode(fake):
    _hit(_Ship(), persist_decal=False)
    assert fake.wear == []


def test_light_phaser_fire_leaves_no_wear(fake):
    _hit(_Ship(), weapon_type="phaser", absorbed_hull=5.0,
         allow_hull_carve=False)
    assert fake.wear == []


def test_wear_reach_matches_scorch_reach(fake):
    _hit(_Ship())
    assert fake.wear[0][0][3] == pytest.approx(fake.decals[0][0][3])
