"""Native per-frame torpedo and torpedo-light feed (phase 6 follow-up 1b): the
oracle.

Task 1: `_h.torpedoes_debug()` / `dynamic_lights_debug()` read back what
`set_torpedoes` / `set_dynamic_lights` pushed, and `torpedo_scene` is a real
host holding torpedoes of two kinds and a disruptor in flight, a non-zero
render origin and one torpedo in a frame that is not viewed, so a later native
feed can be compared bit for bit against today's Python builders.

Packing (so a compare is bitwise and -0.0 / NaN cannot hide in a float ==):
floats are float32 bits ("<f"), ints "<i", a bool one byte ("<B"), a string
a "<i" utf-8 byte length and then the bytes.
"""
import struct

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "set_torpedoes"),
    reason="native host not built")


def _f(*xs):
    return b"".join(struct.pack("<f", x) for x in xs)


def _i(x):
    return struct.pack("<i", x)


def _s(s):
    b = s.encode("utf-8")
    return _i(len(b)) + b


def _pack_torp_row(r):
    """One `torpedoes_debug()` row (TorpedoDescriptor, struct order) as bytes."""
    (pos, core_tex, core_c, core_a, core_b, glow_tex, glow_c, ga, gb, gc,
     flares_tex, flares_c, nflares, fa, fb, age, tid, is_dis, fwd, shell,
     bolt_core, blen, bwid) = r
    return (_f(*pos) + _s(core_tex) + _f(*core_c, core_a, core_b)
            + _s(glow_tex) + _f(*glow_c, ga, gb, gc)
            + _s(flares_tex) + _f(*flares_c) + _i(nflares) + _f(fa, fb, age)
            + _i(tid) + struct.pack("<B", 1 if is_dis else 0) + _f(*fwd)
            + _f(*shell) + _f(*bolt_core) + _f(blen, bwid))


def _pack_torp_dict(d):
    """The same bytes from a `set_torpedoes` dict (what native must hold)."""
    return _pack_torp_row((
        d["position"], d["core_texture"], d["core_color"], d["core_size_a"],
        d["core_size_b"], d["glow_texture"], d["glow_color"], d["glow_size_a"],
        d["glow_size_b"], d["glow_size_c"], d["flares_texture"],
        d["flares_color"], d["num_flares"], d["flares_size_a"],
        d["flares_size_b"], d["age"], d["id"], d["is_disruptor"], d["forward"],
        d["shell_color"], d["bolt_core_color"], d["bolt_length"],
        d["bolt_width"]))


def _pack_light_row(r):
    """One `dynamic_lights_debug()` row (DynamicLightDescriptor) as bytes."""
    (pa, pb, color, radius, intensity, direction, tx, up, ty, idx, gen) = r
    return (_f(*pa) + _f(*pb) + _f(*color) + _f(radius, intensity)
            + _f(*direction) + _f(tx) + _f(*up) + _f(ty) + _i(idx) + _i(gen))


def _pack_light_dict(d):
    """The same bytes from a `set_dynamic_lights` dict, defaults applied."""
    pos = d["position"]
    iid = d.get("instance_id")
    iid = (iid.index, iid.generation) if iid is not None else (0, 0)
    return _pack_light_row((
        pos, d.get("position_b") or pos, d["color"], d["radius"],
        d["intensity"], d.get("direction") or (0.0, 0.0, 0.0),
        -1.0 if d.get("spot_tan_x") is None else d["spot_tan_x"],
        d.get("up") or (0.0, 1.0, 0.0),
        -1.0 if d.get("spot_tan_y") is None else d["spot_tan_y"], *iid))


def _torps():
    """The pushed torpedoes, one packed `bytes` each."""
    return [_pack_torp_row(r) for r in _h.torpedoes_debug()]


def _lights():
    """The pushed dynamic lights, one packed `bytes` each."""
    return [_pack_light_row(r) for r in _h.dynamic_lights_debug()]


QUAD = {
    "position": (1.1, -2.2, 3.3),
    "core_texture": "C:/tex/core.tga", "core_color": (0.1, 0.2, 0.3, 0.4),
    "core_size_a": 0.7, "core_size_b": 1.3,
    "glow_texture": "glow \u00e9.tga", "glow_color": (0.5, 0.6, 0.7, 0.8),
    "glow_size_a": 2.5, "glow_size_b": 0.25, "glow_size_c": 4.75,
    "flares_texture": "", "flares_color": (0.9, 0.8, 0.7, 0.6),
    "num_flares": 8, "flares_size_a": 0.7, "flares_size_b": 0.4,
    "age": 1.5, "id": 77, "is_disruptor": False,
    "forward": (0.0, 0.0, 1.0),
    "shell_color": (1.0, 1.0, 1.0, 1.0), "bolt_core_color": (1.0, 1.0, 1.0, 1.0),
    "bolt_length": 0.0, "bolt_width": 0.0,
}
BOLT = dict(QUAD, position=(-9.5, 0.125, 8.0), core_texture="", glow_texture="",
            is_disruptor=True, id=-3, forward=(0.6, 0.0, 0.8),
            shell_color=(0.2, 0.9, 0.1, 1.0), bolt_core_color=(1.0, 1.0, 0.5, 0.9),
            bolt_length=3.5, bolt_width=0.3, num_flares=0, age=0.0)


def test_readback_returns_what_set_torpedoes_pushed():
    _h.set_torpedoes([QUAD, BOLT])
    try:
        assert _torps() == [_pack_torp_dict(QUAD), _pack_torp_dict(BOLT)]
        assert len(_h.torpedoes_debug()[0]) == 23
    finally:
        _h.set_torpedoes([])
    assert _torps() == []


POINT = {"position": (1.5, -2.5, 3.5), "color": (1.0, 0.5, 0.25),
         "radius": 12.5, "intensity": 0.75}
SEGMENT = dict(POINT, position_b=(4.0, 5.0, 6.0))
CONE = dict(POINT, direction=(0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
            spot_tan_x=0.5, spot_tan_y=0.25)
ATTACHED = dict(POINT, instance_id=_h.InstanceId() if _h else None)


def test_readback_returns_what_set_dynamic_lights_pushed():
    _h.set_dynamic_lights([POINT, SEGMENT, CONE, ATTACHED])
    try:
        assert _lights() == [_pack_light_dict(d)
                             for d in (POINT, SEGMENT, CONE, ATTACHED)]
        # No position_b: a point light is a degenerate segment; no cone: -1.
        row = _h.dynamic_lights_debug()[0]
        assert row[0] == row[1] and row[6] == -1.0
        assert len(row) == 11
    finally:
        _h.set_dynamic_lights([])
    assert _lights() == []


# ── The scene: real host, torpedoes and a disruptor in flight ───────────────

from tests.host.test_native_k2_differential import (  # noqa: E402,F401
    ON, _Scene, _hermetic, host)
from tests.host.test_native_beam_feed import BeamScene  # noqa: E402


def _python_feed(scene):
    """Today's builders for both feeds, pushed through host_io exactly as
    `_push_combat_render_data` does; returns (_torps(), _lights())."""
    from engine import host_io, host_loop
    host_io.set_torpedoes(host_loop._build_torpedo_render_data())
    host_io.set_dynamic_lights(host_loop._budgeted_dynamic_lights(
        host_loop._build_explosion_light_render_data(),
        host_loop._build_dynamic_light_render_data(),
        host_loop._build_emitter_light_render_data(
            scene.ship_instances, scene.ship_emitters, player=scene.player)))
    return _torps(), _lights()


class TorpedoScene(BeamScene):
    """combat_stress on the real host, plus hand-made projectiles: photon and
    quantum torpedoes and a disruptor bolt in the viewed set (a non-zero
    render origin), and a photon in a second set that is not viewed.
    `ships`, `ship_instances`, `player`, `ship_emitters`, `viewed` (the
    projectiles in view), `far` (the one that is not) and `advance()`."""

    def __init__(self, scene):
        super().__init__(scene)
        from engine import host_loop
        from engine.systems import frames
        from engine.appc import projectiles
        import App
        from engine.appc.sets import SetClass_Create
        self.ship_emitters = {}
        frames.set_render_origin((12.5, -30.25, 4.0))
        host_loop._note_camera_eye(None)
        here = self.player.GetWorldLocation()
        base = (here.x, here.y, here.z)

        def col(r, g, b):
            c = App.TGColorA()
            c.SetRGBA(r, g, b, 1.0)
            return c

        def torp(name, at, vel, core, glow, flares, nflares, sizes, dest):
            t = projectiles.Torpedo()
            t.CreateTorpedoModel(
                "data/Textures/Tactical/%sCore.tga" % name, col(*core),
                sizes[0], sizes[1],
                "data/Textures/Tactical/%sGlow.tga" % name, col(*glow),
                sizes[2], sizes[3], sizes[4],
                "data/Textures/Tactical/%sFlares.tga" % name, col(*flares),
                nflares, sizes[5], sizes[6])
            return self._launch(t, name, at, vel, dest)

        photon = torp("Photon", (base[0] + 60, base[1] + 40, base[2] + 10),
                      (3.0, 4.0, 0.5), (1, 0.5, 0.1), (1, 0.4, 0), (1, 1, 0.5),
                      8, (0.2, 1.2, 3.0, 0.3, 0.6, 0.7, 0.4), self.scene.set)
        quantum = torp("Quantum", (base[0] - 15, base[1] + 25, base[2] + 3),
                       (-1.0, 2.0, 0.0), (0.3, 0.5, 1), (0.2, 0.4, 1),
                       (0.8, 0.9, 1), 6, (0.3, 1.0, 2.0, 0.5, 0.25, 0.5, 0.3),
                       self.scene.set)
        bolt = projectiles.Torpedo()
        bolt.CreateDisruptorModel(col(0.2, 0.9, 0.1), col(1, 1, 0.5), 3.5, 0.3)
        bolt = self._launch(bolt, "Bolt", (base[0], base[1] - 30, base[2]),
                            (0.0, 6.0, 0.8), self.scene.set)
        elsewhere = SetClass_Create()
        App.g_kSetManager.AddSet(elsewhere, "TorpFar")
        far = torp("Photon", (7.0, 8.0, 9.0), (1.0, 0.0, 0.0),
                   (1, 0.5, 0.1), (1, 0.4, 0), (1, 1, 0.5), 8,
                   (0.2, 1.2, 3.0, 0.3, 0.6, 0.7, 0.4), elsewhere)
        self.viewed = [photon, quantum, bolt]
        self.far = far
        self.far_set = elsewhere

    @staticmethod
    def _launch(t, name, at, vel, kset):
        from engine.appc import projectiles
        from engine.appc.math import TGPoint3
        t.SetTranslateXYZ(*at)
        t._velocity = TGPoint3(*vel)
        t.SetLifetime(1e6)
        kset.AddObjectToSet(t, "torp-" + name + str(len(projectiles._active)))
        projectiles.register(t, None)
        return t

    def advance(self, ticks=1):
        """One frame: the beam scene's, then every projectile steps (as
        `cb.projectiles` does)."""
        from engine.appc import projectiles
        from engine.core.loop import TICK_DELTA
        from engine.appc.ship_iter import iter_ships
        super().advance(ticks)
        for _ in range(ticks):
            projectiles.update_all(TICK_DELTA, list(iter_ships()),
                                   ship_instances=self.ship_instances)

    def close(self):
        from engine import host_loop
        from engine.appc import projectiles
        from engine.systems import frames
        projectiles._active.clear()
        host_loop._note_camera_eye(None)
        frames.reset_render_origin()


@pytest.fixture
def torpedo_scene(monkeypatch, host):
    scene = _Scene(monkeypatch, host, ON)
    ts = None
    try:
        ts = TorpedoScene(scene)
        for _ in range(3):
            ts.advance()
        yield ts
    finally:
        if ts is not None:
            ts.close()
        scene.close()


def test_scene_feeds_torpedoes_a_disruptor_and_lights(torpedo_scene):
    import struct as st
    ts = torpedo_scene
    torps, lights = _python_feed(ts)
    rows = _h.torpedoes_debug()
    # Two torpedoes and a bolt are in view; the fourth is in another frame.
    assert len(torps) == 3, len(torps)
    assert len({r[1] for r in rows if r[1]}) == 2     # two kinds (core texture)
    assert sum(1 for r in rows if r[17]) == 1         # one disruptor
    # Lights: a torpedo glow for each non-disruptor torpedo in view.
    assert len(lights) >= 2, len(lights)
    # The render origin is non-zero and the pushed positions are in render
    # space: the first torpedo (set-local x ~ player + 20) minus the origin.
    from engine.systems import frames
    assert frames.render_origin() == (12.5, -30.25, 4.0)
    p = ts.viewed[0].GetTranslate()
    assert rows[0][0][0] == st.unpack("<f", st.pack("<f", p.x - 12.5))[0]

