"""Headless VFX probe (minor-rocks spec §3/§5): fly the player box through
real clouds, driving the REAL native MinorField step, and count every
response the frame would fire.

Multi1 (54 halos) places real objects through its own SDK region modules;
the clouds below are the REAL `minors.desired_clouds` output for those
objects, not hand-built descs. (The Beol4 tile-field cases went with the
tile clouds themselves: rock-fields, 2026-10-02.)

Multi1's halos are small (radius a few GU) and thin (a 1.1x-3.0x shell), so
even the densest of the 54 meets only ~0.3 expected minors on a straight pass
-- confirmed empirically (scale=1 below produced zero hits in every trial).
Per a controller ruling, the densest halo's `count` is scaled up (xN, see
`_MULTI1_DENSEST_SCALE`) so the flight genuinely meets minors; every other
halo is sent unscaled. This is a probe-only adjustment -- it does not change
`engine/rocks/minors.py` or any shipped dial.
"""
import dataclasses
import math

import App
from engine.rocks import minor_contact as mc
from engine.rocks import minor_dials as md
from engine.rocks import minors
from tests.integration.test_sdk_bridge_load import _fresh_world

# Empirically chosen (see module docstring): scale=1 (the real halo) produced
# zero hits in every trial; scale=20 already clears the caps comfortably with
# margin to spare, so 30 keeps that margin while asserting it is genuinely
# "met", not a one-off.
_MULTI1_DENSEST_SCALE = 30


def _persp16():
    t = 1.0 / math.tan(math.radians(30))
    n, f, a = 0.1, 1e6, 16 / 9
    return [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1,
            0, 0, 2 * f * n / (n - f), 0]


def _view16_at(y):
    # Camera 30 GU behind the player along -y, looking +y.
    return [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, -(y - 30), 1]


def _desc(spec, cid):
    d = {k: getattr(spec, k) for k in (
        "anchor", "point", "velocity", "t0", "shell_inner", "shell_outer",
        "falloff", "count", "r_min", "r_max", "size_exponent", "family",
        "seed", "orbit_rate", "fade_in", "debris")}
    d["id"], d["instance"] = cid, None
    return d


def _desc_point(spec, cid, point):
    """Like `_desc`, but forces a Point anchor at `point` -- used for the
    Multi1 halo case, whose real CloudSpec.anchor is "instance" (renderer
    InstanceId), unavailable in this no-GL probe."""
    d = _desc(spec, cid)
    d["anchor"] = "point"
    d["instance"] = None
    d["point"] = point
    return d


def _fly(field, speed_gups, start, seconds=10.0, muted=False, monkeypatch=None):
    totals = {"puffs": 0, "grits": 0, "flickers": 0}
    calls = {"puff": 0, "grit": 0, "flicker": 0}
    monkeypatch.setattr(mc, "_spawn_puff", lambda p: calls.__setitem__("puff", calls["puff"] + 1))
    monkeypatch.setattr(mc, "_play_grit", lambda p, r: calls.__setitem__("grit", calls["grit"] + 1) or True)
    monkeypatch.setattr(mc, "_flicker", lambda pl, p, s: calls.__setitem__("flicker", calls["flicker"] + 1) or True)
    monkeypatch.setattr(mc, "_shields_up", lambda pl: True)
    monkeypatch.setattr(mc, "_muted", lambda pl: muted)
    dt = 1.0 / 60.0
    for i in range(int(seconds * 60)):
        t = i * dt
        y = start[1] + speed_gups * t
        w = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.01, 0, start[0], y, start[2], 1]
        field.step(t, _view16_at(y), _persp16(), 1080.0,
                   player={"world": w, "center": (0, 0, 0), "half": (60, 320, 40)})
        out = mc.pump(object(), contacts=field.drain_contacts(), now=t)
        for k in totals:
            totals[k] += out[k]
    return totals, calls


def _multi1_field():
    """Real Multi1 (SDK Systems.Multi1.Multi1): 54 halos, one per realised
    rock. Point-anchored (see `_desc_point`); the densest halo's count is
    scaled up (`_MULTI1_DENSEST_SCALE`) so a flight through its centre
    genuinely meets minors -- see module docstring."""
    import _dauntless_host as h
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = {pSet.GetObject("Asteroid %d" % i): i for i in range(1, 55)}
    md.reset()
    specs = minors.desired_clouds(pSet, rock_instances=rocks, fields=[])
    halos = [(k, s) for k, s in specs.items() if k.startswith("halo:")]
    assert len(halos) == 54
    halos.sort(key=lambda ks: ks[1].count, reverse=True)
    densest_key, densest_spec = halos[0]
    densest_name = densest_key.rsplit(":", 1)[-1]
    densest_rock = pSet.GetObject(densest_name)
    loc = densest_rock.GetWorldLocation()
    centre = (loc.x, loc.y, loc.z)

    f = h.MinorField()
    f.set_fragments(0, [(1, 2, 57.142857)])
    for i, (key, spec) in enumerate(halos, start=1):
        rock_name = key.rsplit(":", 1)[-1]
        rock = pSet.GetObject(rock_name)
        rloc = rock.GetWorldLocation()
        if key == densest_key:
            spec = dataclasses.replace(spec, count=spec.count * _MULTI1_DENSEST_SCALE)
        f.add_cloud(_desc_point(spec, i, (rloc.x, rloc.y, rloc.z)), 0.0)
    return f, centre


def test_multi1_flythrough_stays_within_caps(monkeypatch):
    mc.reset()
    f, c = _multi1_field()
    speed = 6.3
    start = (c[0], c[1] - speed * 5.0, c[2])          # crosses the densest halo's centre at t = 5 s
    totals, calls = _fly(f, speed, start, muted=False, monkeypatch=monkeypatch)
    assert totals["puffs"] <= 6 * 10 + 6
    assert totals["grits"] <= 4 * 10 + 4
    assert totals["flickers"] <= 2 * 10 + 2
    assert calls["grit"] > 0                          # it really met minors


def test_flythrough_changes_no_game_state(monkeypatch):
    """No damage, no events: the probe never touches a ship object. Building
    the real Multi1 set (region placements, waypoints) posts its own setup
    events -- those are unrelated SDK world-building, not minor-rocks
    behaviour, so the capture starts only once the field is built and the
    flight (the thing under test) begins."""
    mc.reset()
    f, c = _multi1_field()
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", lambda e: posted.append(e))
    _fly(f, 6.3, (c[0], c[1] - 31.5, c[2]), seconds=10.0, monkeypatch=monkeypatch)
    assert posted == []
