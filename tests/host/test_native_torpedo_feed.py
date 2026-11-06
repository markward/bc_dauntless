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
    projectiles in view), `far` (the one that is not) and `advance()`.

    `extended` adds what the 300-frame equality test must cover (the plan's
    Review Focus): `eye` (a fixed camera eye in view coordinates, at the
    player's start) with a photon in its fade band and one beyond its cull
    distance, both crawling so they stay there; a crowd of photons above the
    ship ring (many more torpedo lights than _LIGHT_BUDGET_TORPEDOES, so the
    budget spills and, until half of them expire, the cap is reached); real
    subsystem emitter lights on the first ships with baked emitters (their
    real instance ids) and one explosion light; and photons with a short
    lifetime that expire mid-run (`expiring`)."""

    def __init__(self, scene, extended=False):
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
        self.eye = None
        self.expiring = []
        if not extended:
            return
        import math
        from engine.appc import explosion_lights
        # The eye: fixed, in view coordinates (the player's set is viewed).
        self.eye = base
        fs, cull = host_loop.DYN_LIGHT_FADE_START_GU, host_loop.DYN_LIGHT_CULL_GU
        mid = 0.5 * (fs + cull)
        # Straight above and below the ship ring (it lies in z = 0, radius
        # ~20 GU), crawling: 0.05 GU/s moves 0.25 GU in 300 frames.
        self.band = torp("Photon", (base[0], base[1], base[2] + mid),
                         (0.0, 0.0, 0.05), (1, 0.5, 0.1), (1, 0.4, 0),
                         (1, 1, 0.5), 8, (0.2, 1.2, 3.0, 0.3, 0.6, 0.7, 0.4),
                         self.scene.set)
        self.culled = torp("Quantum", (base[0], base[1], base[2] - 1.4 * cull),
                           (0.0, 0.0, -0.05), (0.3, 0.5, 1), (0.2, 0.4, 1),
                           (0.8, 0.9, 1), 6,
                           (0.3, 1.0, 2.0, 0.5, 0.25, 0.5, 0.3), self.scene.set)
        # The crowd: 60 photons on a ring 8 GU across, 15 GU above the ships.
        self.crowd = []
        for i in range(60):
            a = 2.0 * math.pi * i / 60
            t = torp("Photon", (base[0] + 8.0 * math.cos(a),
                                base[1] + 8.0 * math.sin(a), base[2] + 15.0),
                     (0.01 * math.cos(a), 0.01 * math.sin(a), 0.0),
                     (1, 0.5, 0.1), (1, 0.4, 0.05 * (i % 7)), (1, 1, 0.5), 8,
                     (0.2, 1.2, 3.0 + 0.01 * i, 0.3, 0.6, 0.7, 0.4),
                     self.scene.set)
            self.crowd.append(t)
            if i % 2:
                t.SetLifetime(2.0 + 0.01 * i)     # expire around frame 125
                self.expiring.append(t)
        # Real emitter lights: _build_ship_emitter_cache for the first ships
        # that have baked emitters, keyed by their real instance id.
        for ship in self.ships:
            iid = self.ship_instances.get(ship)
            entries = host_loop._build_ship_emitter_cache(ship)
            if iid is not None and entries:
                self.ship_emitters[iid] = entries
            if len(self.ship_emitters) == 3:
                break
        # One fireball light, born long ago in a long life (so it burns all
        # run), below the ring.
        explosion_lights.register_at(
            (base[0], base[1], base[2] - 30.0), self.scene.set,
            size_gu=4.0, life_s=1000.0)
        explosion_lights._active[-1]["age"] = 50.0
        # A homing photon: a `_target_ship`, so K3 steers its velocity (and
        # its drawn `forward`) every tick. Launched 40 GU above the ring at
        # 2 GU/s, sideways to its target, with guidance for the whole run.
        foe = next(s for s in self.ships if s.GetName() == "Enemy-1")
        self.homing = torp("Quantum", (base[0], base[1], base[2] + 40.0),
                           (2.0, 0.0, 0.0), (0.3, 0.5, 1), (0.2, 0.4, 1),
                           (0.8, 0.9, 1), 6,
                           (0.3, 1.0, 2.0, 0.5, 0.25, 0.5, 0.3),
                           self.scene.set)
        self.homing._target_ship = foe
        self.homing.SetGuidanceLifetime(100.0)
        self.viewed += [self.band, self.culled, self.homing] + self.crowd

    @staticmethod
    def _rest_mount(ship, mount):
        """`mount` (body frame) in world space with no part transform: the
        ship's location plus its rotation times the mount."""
        from engine.appc.math import TGPoint3
        o = TGPoint3(*mount)
        o.MultMatrixLeft(ship.GetWorldRotation())
        p = ship.GetWorldLocation()
        return (p.x + o.x, p.y + o.y, p.z + o.z)

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
        from engine.appc import explosion_lights, projectiles
        from engine.systems import frames
        explosion_lights.reset()
        projectiles._active.clear()
        host_loop._note_camera_eye(None)
        frames.reset_render_origin()


def _first_torpedo_id(monkeypatch):
    """Number this scene's torpedoes from 1: `projectiles._next_id` is a
    process-wide counter, so a torpedo's drawn `id` would otherwise depend
    on the tests run before (the render goldens record it)."""
    from engine.appc import projectiles
    monkeypatch.setattr(projectiles, "_next_id", 1)


def _scene_fixture(monkeypatch, host, extended):
    _first_torpedo_id(monkeypatch)
    scene = _Scene(monkeypatch, host, ON)
    ts = None
    try:
        ts = TorpedoScene(scene, extended=extended)
        for _ in range(3):
            ts.advance()
        yield ts
    finally:
        if ts is not None:
            ts.close()
        scene.close()


@pytest.fixture
def torpedo_scene(monkeypatch, host):
    yield from _scene_fixture(monkeypatch, host, False)


@pytest.fixture
def busy_torpedo_scene(monkeypatch, host):
    yield from _scene_fixture(monkeypatch, host, True)


def test_scene_feeds_torpedoes_a_disruptor_and_lights(torpedo_scene):
    import struct as st
    ts = torpedo_scene
    torps, lights = _python_feed(ts)
    rows = _h.torpedoes_debug()
    # Two torpedoes and a bolt are in view; the fourth is in another frame.
    assert len(torps) == 3, len(torps)
    assert len({r[1] for r in rows if r[1]}) == 2     # two kinds (core texture)
    assert sum(1 for r in rows if r[17]) == 1         # one disruptor
    # Lights: a torpedo glow for each non-disruptor torpedo in view (no
    # camera eye, no emitters, no explosions): exactly two, none at the bolt.
    assert len(lights) == 2, len(lights)
    # The render origin is non-zero and every pushed position is in render
    # space: the set-local point minus the origin, row for row (the rows are
    # the viewed torpedoes, in _active order).
    from engine.systems import frames
    o = frames.render_origin()
    assert o == (12.5, -30.25, 4.0)

    def f32(x):
        return st.unpack("<f", st.pack("<f", x))[0]

    for row, t in zip(rows, ts.viewed):
        p = t.GetTranslate()
        assert row[0] == (f32(p.x - o[0]), f32(p.y - o[1]), f32(p.z - o[2]))
    bolt_pos = rows[2][0]
    light_pos = [r[0] for r in _h.dynamic_lights_debug()]
    assert light_pos == [rows[0][0], rows[1][0]]
    assert bolt_pos not in light_pos



# ── Task 3: the native feed, frame by frame, against the Python builders ────

from engine.appc import native_combat as nc  # noqa: E402

# Match nothing a builder makes: a negative core size / a negative radius.
SENTINEL_T = dict(QUAD, core_size_a=-1.0, id=-99)
SENTINEL_L = dict(POINT, radius=-1.0)


def _native_feed(scene, want=None, want_torp_lights=None):
    """native_combat.torpedo_feed, then what it pushed: (ok, torpedo bytes,
    light bytes). Both vectors are seeded with sentinels first, so a binding
    that skipped an assignment reads back the sentinel, never the Python
    frame pushed before it. With `want` (the _python_feed pair) the
    bindings' own counts must equal its lengths, and the torpedo-light count
    the Python builder's (`want_torp_lights`)."""
    _h.set_torpedoes([SENTINEL_T])
    _h.set_dynamic_lights([SENTINEL_L, SENTINEL_L])
    returned = {"feed": [], "lights": []}
    feed, budgeted = _h.combat_torpedo_feed, _h.set_dynamic_lights_budgeted

    def feed_spy(*a, **k):
        r = feed(*a, **k)
        returned["feed"].append(r)
        return r

    def budgeted_spy(*a, **k):
        r = budgeted(*a, **k)
        returned["lights"].append(r)
        return r

    _h.combat_torpedo_feed = feed_spy
    _h.set_dynamic_lights_budgeted = budgeted_spy
    try:
        ok = nc.torpedo_feed(scene.ship_instances, scene.ship_emitters,
                             scene.player)
    finally:
        _h.combat_torpedo_feed = feed
        _h.set_dynamic_lights_budgeted = budgeted
    if ok and want is not None:
        assert returned["feed"] == [(len(want[0]), want_torp_lights)], returned
        assert returned["lights"] == [len(want[1])], returned
    return ok, _torps(), _lights()


class _Coverage:
    """Spies on the Python light blend while armed, so each compared frame
    says what it held: the three light groups' sizes, torpedo lights in the
    fade band (0 < intensity < the knob), torpedoes culled by the camera
    distance, and disruptors."""

    def __init__(self, monkeypatch):
        from engine import host_loop
        self.armed = False
        self.groups = None
        self.counts = dict.fromkeys(
            ("frames", "eye", "no_eye", "disruptors", "torpedo_lights",
             "fade_band", "culled", "explosion_lights", "emitter_lights",
             "spill", "capped", "expired", "dirty", "steered"), 0)
        blend = host_loop._budgeted_dynamic_lights

        def blend_spy(explosions, torpedoes, emitters):
            if self.armed:
                self.groups = (list(explosions), list(torpedoes),
                               list(emitters))
            return blend(explosions, torpedoes, emitters)

        monkeypatch.setattr(host_loop, "_budgeted_dynamic_lights", blend_spy)

    def python_feed(self, scene):
        from engine import host_loop
        self.groups = None
        self.armed = True
        try:
            got = _python_feed(scene)
        finally:
            self.armed = False
        exp, torp, emit = self.groups
        c = self.counts
        c["frames"] += 1
        c["eye" if host_loop._last_camera_eye is not None else "no_eye"] += 1
        rows = _h.torpedoes_debug()
        c["disruptors"] += sum(1 for r in rows if r[17])
        c["torpedo_lights"] += len(torp)
        knob = host_loop._TORPEDO_LIGHT_INTENSITY
        c["fade_band"] += sum(1 for d in torp if 0 < d["intensity"] < knob)
        # Every in-view non-disruptor torpedo here has a glow radius > 0, so
        # one with no light was culled by the camera distance.
        c["culled"] += sum(1 for r in rows if not r[17]) - len(torp)
        c["explosion_lights"] += len(exp)
        c["emitter_lights"] += len(emit)
        if len(torp) > host_loop._LIGHT_BUDGET_TORPEDOES:
            c["spill"] += 1
        if len(got[1]) == host_loop._LIGHT_CAP:
            c["capped"] += 1
        return got, len(torp)


def test_native_torpedo_feed_equals_python_every_frame(busy_torpedo_scene,
                                                       monkeypatch):
    from engine import host_loop
    from engine.appc import projectiles
    ts = busy_torpedo_scene
    cov = _Coverage(monkeypatch)
    nc.reset_torpedo_feed_counts()
    before = None
    last_fwd = None
    for k in range(300):
        ts.advance()
        # The homing torpedo's drawn forward turned this tick (K3 steered it).
        if ts.homing in projectiles._active:
            fwd = host_loop._torpedo_forward(ts.homing)
            if last_fwd is not None and fwd != last_fwd:
                cov.counts["steered"] += 1
            last_fwd = fwd
        # The camera eye on for 40 frames, off for 20.
        host_loop._note_camera_eye(ts.eye if k % 60 < 40 else None)
        # A reorder the rows cannot follow, after the step: the table is
        # dirty at render time.
        if k in (150, 151, 220):
            projectiles._active.reverse()
            assert nc._k3_dirty
            cov.counts["dirty"] += 1
        want, n_torp_lights = cov.python_feed(ts)
        if before is not None and len(want[0]) < before:
            cov.counts["expired"] += 1
        before = len(want[0])
        ok, torps, lights = _native_feed(ts, want, n_torp_lights)
        assert ok, "frame %d: the native feed fell back" % k
        assert torps == want[0], "frame %d: torpedoes differ" % k
        assert lights == want[1], "frame %d: lights differ" % k
    c = cov.counts
    print("\ntorpedo feed coverage over %d frames: %r" % (c["frames"], c))
    assert c["frames"] == 300, c
    assert nc.torpedo_feed_counts()["native"] == 300
    assert nc.torpedo_feed_fallbacks == 0
    for case in c:
        assert c[case] > 0, "no frame had %s: %r" % (case, c)
    assert c["spill"] > c["capped"], "premise: spill frames below the cap"
    assert all(t not in projectiles._active for t in ts.expiring)


def test_a_throw_leaves_no_partial_feed_and_python_fills_the_frame(
        torpedo_scene):
    from engine import host_loop
    from engine.appc import projectiles
    ts = torpedo_scene
    # A torpedo with no model, registered LAST: the rows before it have been
    # built into the native locals when its missing record throws, so a
    # partial build really is discarded.
    here = ts.player.GetWorldLocation()
    bare = TorpedoScene._launch(projectiles.Torpedo(), "Bare",
                                (here.x, here.y, here.z + 30.0),
                                (0.0, 0.0, 0.0), ts.scene.set)
    assert bare.__dict__.get("_vis_native") is None
    assert projectiles._active[-1] is bare
    _h.set_torpedoes([SENTINEL_T])
    _h.set_dynamic_lights([SENTINEL_L])
    sentinel = (_torps(), _lights())
    try:
        assert nc.torpedo_feed(ts.ship_instances, ts.ship_emitters,
                               ts.player) is False
        assert nc.torpedo_feed_fallbacks == 1
        assert nc.torpedo_feed_counts()["fallbacks"]["no_visual"] == 1
        # Neither vector was touched: no partial frame, and no torpedo light
        # list is left pending for a later blend.
        assert (_torps(), _lights()) == sentinel
        with pytest.raises(ValueError):
            _h.set_dynamic_lights_budgeted([], [], (64, 10, 10, 40))
        # host_loop's frame: the native feed falls back, Python fills it.
        host_loop._push_combat_render_data(
            ts.ships, ship_instances=ts.ship_instances,
            ship_emitters=ts.ship_emitters, player=ts.player)
        assert nc.torpedo_feed_fallbacks == 2
        pushed = (_torps(), _lights())
        want = _python_feed(ts)
        assert len(want[0]) == 4, "premise: the bare torpedo draws in Python"
        assert pushed == want
    finally:
        _h.set_torpedoes([])
        _h.set_dynamic_lights([])


def test_torpedo_feed_counts_reach_the_profiler_report(torpedo_scene,
                                                       monkeypatch):
    from engine import host_io
    from engine.core import frame_profiler as fp
    ts = torpedo_scene
    nc.reset_torpedo_feed_counts()
    args = (ts.ship_instances, ts.ship_emitters, ts.player)
    assert nc.torpedo_feed(*args) is True
    assert nc.torpedo_feed(*args) is True
    monkeypatch.setattr(nc, "_switch", False)
    assert nc.torpedo_feed(*args) is False
    monkeypatch.setattr(nc, "_switch", True)
    monkeypatch.setattr(nc, "_beam_frames", lambda: {})   # no set framed
    assert nc.torpedo_feed(*args) is False
    c = nc.torpedo_feed_counts()
    assert c == {"native": 2,
                 "fallbacks": {"no_visual": 0, "dirty": 0, "unanswerable": 1},
                 "stand_downs": {"off": 1, "audit": 0, "no_host": 0,
                                 "plain_active": 0}}, c
    monkeypatch.setattr(host_io, "profiler_scopes", lambda: [])
    monkeypatch.setattr(
        host_io, "profiler_frame",
        lambda: {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False})
    fp.set_enabled(True, native=False)
    try:
        fp.begin_frame(); fp.mark("p"); fp.end_frame()
        lines = [ln for ln in fp.report_lines() if "torpedo feed" in ln]
    finally:
        fp.set_enabled(False)
    assert lines == ["  torpedo feed: native 2, fallbacks 1 (no_visual 0, "
                     "dirty 0, unanswerable 1), stand-downs off 1, audit 0, "
                     "no_host 0, plain_active 0"]
    nc.reset()
    assert nc.torpedo_feed_counts()["native"] == 0


def test_a_pending_torpedo_light_list_is_blended_once(torpedo_scene):
    """The pair: one feed, one blend. A second blend raises, and so does a
    blend after a plain Python light push (set_dynamic_lights invalidates
    the pending list), so a stale torpedo-light list can never be drawn."""
    ts = torpedo_scene
    caps = (64, 10, 10, 40)
    args = (ts.ship_instances, ts.ship_emitters, ts.player)
    try:
        assert nc.torpedo_feed(*args) is True
        with pytest.raises(ValueError):
            _h.set_dynamic_lights_budgeted([], [], caps)
        # A feed straight from the binding, so nothing blends it ...
        _h.combat_torpedo_feed({
            "view": -1, "origin": (0.0, 0.0, 0.0), "frames": {},
            "brightness": 0.25, "light_radius_scale": 50.0,
            "light_intensity": 1.0, "fade_start": 74.0, "cull": 85.0,
            "eye": None, "expected_rows": -1})
        # ... then any Python push of the lights.
        _h.set_dynamic_lights([POINT])
        with pytest.raises(ValueError):
            _h.set_dynamic_lights_budgeted([], [], caps)
        assert _lights() == [_pack_light_dict(POINT)]
    finally:
        _h.set_torpedoes([])
        _h.set_dynamic_lights([])


def test_the_knobs_are_read_per_call(busy_torpedo_scene, monkeypatch):
    """Two frames, every per-frame knob changed between them: native still
    equals Python, and the second frame differs from the first."""
    from engine import host_loop
    ts = busy_torpedo_scene
    host_loop._note_camera_eye(ts.eye)
    frames = []
    for knobs in ({}, {"TORPEDO_BRIGHTNESS": 0.7,
                       "_TORPEDO_LIGHT_RADIUS_SCALE": 20.0,
                       "_TORPEDO_LIGHT_INTENSITY": 2.5,
                       "DYN_LIGHT_FADE_START_GU": 10.0,
                       "DYN_LIGHT_CULL_GU": 30.0,
                       "_LIGHT_BUDGET_TORPEDOES": 3,
                       "_LIGHT_CAP": 40}):
        for name, value in knobs.items():
            monkeypatch.setattr(host_loop, name, value)
        ts.advance()
        want = _python_feed(ts)
        n_torp_lights = len(host_loop._build_dynamic_light_render_data())
        ok, torps, lights = _native_feed(ts, want, n_torp_lights)
        assert ok
        assert (torps, lights) == want
        frames.append((want, n_torp_lights))
    (t0, l0), n0 = frames[0]
    (t1, l1), n1 = frames[1]
    assert t0 != t1 and l0 != l1
    assert n1 < n0                       # the shorter cull drops lights
    assert len(l1) <= 40
    assert nc.torpedo_feed_fallbacks == 0


# ── Render goldens (phase 6 follow-up 4, Task 1) ────────────────────────────
#
# The same scenes as the equality tests above, checked against goldens
# recorded from the Python builders (tests/helpers/render_golden.py): under
# UPDATE_RENDER_GOLDEN=1 the frames are the Python builders' and are
# recorded; otherwise they are the native feeds' and are checked.

from tests.helpers import render_golden  # noqa: E402
from tests.host.test_native_beam_feed import (  # noqa: E402
    _record_or_check, golden_beam_frame)


def _golden_lights(scene):
    """The pushed dynamic lights packed as `_lights()` packs them, but an
    attached light's instance id (index, generation) -- which depends on the
    instances the host made before this scene -- given as the name of the
    scene's ship it is (an unattached light: "")."""
    names = {(iid.index, iid.generation): ship.GetName()
             for ship, iid in scene.ship_instances.items()}
    out = []
    for r in _h.dynamic_lights_debug():
        iid = (r[9], r[10])
        if iid == (0, 0):
            name = ""
        else:
            assert iid in names, "a light on no scene ship's instance: %r" % (
                iid,)
            name = names[iid]
        out.append(_pack_light_row(r[:9] + (0, 0)) + _s(name))
    return out


def golden_torpedo_frame(scene):
    """This frame's torpedoes and lights as a render_golden frame: the
    Python builders' while recording, else the native feed's (a feed that
    fell back leaves its sentinels, so the frame differs from the golden)."""
    if render_golden.recording():
        render_golden.require_python_builders()
        torps, _lights_ = _python_feed(scene)
        source = "python"
    else:
        _ok, torps, _lights_ = _native_feed(scene)
        source = "native"
    return render_golden.frame(torps=torps, lights=_golden_lights(scene),
                               source=source)


def test_torpedo_scene_matches_the_golden(busy_torpedo_scene):
    """test_native_torpedo_feed_equals_python_every_frame's 300 frames: the
    camera eye on 40 frames, off 20, and the reorders at 150, 151 and 220
    that leave the torpedo table dirty at render time."""
    from engine import host_loop
    from engine.appc import projectiles
    ts = busy_torpedo_scene
    frames = []
    for k in range(300):
        ts.advance()
        host_loop._note_camera_eye(ts.eye if k % 60 < 40 else None)
        if k in (150, 151, 220):
            projectiles._active.reverse()
        frames.append(golden_torpedo_frame(ts))
    assert all(t not in projectiles._active for t in ts.expiring)
    assert sum(len(f["lights"]) for f in frames) > 0
    _record_or_check("torpedo_scene", frames)


def test_torpedo_knobs_match_the_golden(busy_torpedo_scene, monkeypatch):
    """test_the_knobs_are_read_per_call's two frames: every per-frame knob
    changed between them."""
    from engine import host_loop
    ts = busy_torpedo_scene
    host_loop._note_camera_eye(ts.eye)
    frames = []
    for knobs in ({}, KNOBS):
        for name, value in knobs.items():
            monkeypatch.setattr(host_loop, name, value)
        ts.advance()
        frames.append(golden_torpedo_frame(ts))
    assert frames[0] != frames[1]
    _record_or_check("torpedo_knobs", frames)


KNOBS = {"TORPEDO_BRIGHTNESS": 0.7, "_TORPEDO_LIGHT_RADIUS_SCALE": 20.0,
         "_TORPEDO_LIGHT_INTENSITY": 2.5, "DYN_LIGHT_FADE_START_GU": 10.0,
         "DYN_LIGHT_CULL_GU": 30.0, "_LIGHT_BUDGET_TORPEDOES": 3,
         "_LIGHT_CAP": 40}


# ── The edge cases: what today's native feeds hand back to Python ───────────
#
# One scene, 60 frames: torpedo_scene's projectiles plus beam_scene's opening
# volley, then three cases, each in its own stretch of frames:
#
#   NON_SHIP (frames 10-29): a ship's phasers and tractor lit at a plain
#     DamageableObject (App.DamageableObject_Create on a model name that is
#     not a stock asteroid: a DamageableObject, not a ShipClass), through the
#     real StartFiring. Stopped, and the object removed, at frame 30.
#   LATE_BUMP (frame 40): from frame 30 a rigged Bird of Prey (Enemy-4) has
#     one of its real parts (from parts_for_ship) hinged by force_part_pose,
#     and a Fed ship's phasers are locked on a subsystem whose mount rides
#     that part (articulation._live_part resolves to it), so the drawn aim
#     point is the posed mount; at frame 40 the part generation is bumped
#     after the frame's ticks, before the feeds.
#   BARE (frames 50-59): a torpedo registered without CreateTorpedoModel /
#     CreateDisruptorModel.
#
# Today's native feeds hand exactly those frames back to Python, so they
# differ from the golden (EXPECTED_NATIVE_DIFFS); phase 6 follow-up 4 Task 2
# answers them natively and makes the expectation "no differing frames".

NON_SHIP = range(10, 30)
LATE_BUMP = 40
POSE_AT = 30
BARE_FROM = 50
EDGE_FRAMES = 60
BOP, BOP_FIRER = "Enemy-4", "Friend-1"
EXPECTED_NATIVE_DIFFS = (list(NON_SHIP) + [LATE_BUMP]
                         + list(range(BARE_FROM, EDGE_FRAMES)))


@pytest.fixture
def edge_scene(monkeypatch, host):
    _first_torpedo_id(monkeypatch)
    scene = _Scene(monkeypatch, host, ON)
    ts = None
    try:
        ts = TorpedoScene(scene)
        ts._open_fire()
        for _ in range(30):
            ts.advance()
        yield ts
    finally:
        if ts is not None:
            ts.close()
        scene.close()


def _lit_at(system, target):
    return [b for b in system._children
            if b.__dict__.get("_firing") and b._target is target]


def test_edge_cases_match_the_golden(edge_scene):
    import App
    from engine.appc import articulation, part_pose, projectiles
    from engine.appc.objects import DamageableObject
    from engine.appc.ships import ShipClass
    from engine.appc.ship_iter import iter_ships
    from engine.appc import part_severance, physical_parents
    from engine.appc import subsystems as ss
    ts = edge_scene
    sc = ts.scene
    shooter = next(s for s in ts.ships if s is not ts.player
                   and s.GetTractorBeamSystem() is not None
                   and s.GetPhaserSystem() is not None)
    posed, poser = sc.ship(BOP), sc.ship(BOP_FIRER)
    parts = [p.GetName() for p in articulation.parts_for_ship(posed)]
    assert parts, "premise: the Bird of Prey is rigged"
    leaf = articulation.leaf_for(posed)
    # The first mounted subsystem whose mount rides a rigged part.
    mounts = [(s, tuple(p))
              for s, p in part_severance._mounted_subsystems(posed)
              if p is not None]
    locked, mount, part = next(
        (s, p, physical_parents.part_for_property(
            leaf, physical_parents.property_of(s), p))
        for s, p in mounts
        if physical_parents.part_for_property(
            leaf, physical_parents.property_of(s), p) in parts)
    probe = bare = None
    seen = {"non_ship_phaser": 0, "non_ship_tractor": 0, "posed_lock": 0,
            "bare": 0}
    frames = []
    for k in range(EDGE_FRAMES):
        if k == NON_SHIP.start:
            probe = App.DamageableObject_Create("RenderGoldenProbe")
            assert type(probe) is DamageableObject
            assert not isinstance(probe, ShipClass)
            p = shooter.GetWorldLocation()
            f = shooter.GetWorldRotation().GetCol(1)
            sc.set.AddObjectToSet(probe, "RenderGoldenProbe")
            probe.SetTranslateXYZ(p.x + 5.0 * f.x, p.y + 5.0 * f.y,
                                  p.z + 5.0 * f.z)
            tb, ph = shooter.GetTractorBeamSystem(), shooter.GetPhaserSystem()
            tb.TurnOn()
            tb.StartFiring(probe, None)
            ph.TurnOn()
            ph.SetSingleFire(0)
            ph.StartFiring(probe)
        elif k == NON_SHIP.stop:
            shooter.GetTractorBeamSystem().StopFiring()
            shooter.GetPhaserSystem().StopFiring()
            sc.set.RemoveObjectFromSet("RenderGoldenProbe")
        if k == POSE_AT:
            articulation.force_part_pose(
                posed, part,
                part_pose.hinge_pose((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 15.0))
            assert articulation._live_part(
                posed, None, mount, True,
                physical_parents.property_of(locked)) == part, \
                "premise: the locked mount rides the posed part"
            sc.face(poser, posed)
            poser.SetTarget(posed)
            poser.SetTargetSubsystem(locked)
            ph = poser.GetPhaserSystem()
            ph.TurnOn()
            ph.SetSingleFire(0)
            ph.StartFiring(posed)
        if k == BARE_FROM:
            here = ts.player.GetWorldLocation()
            bare = TorpedoScene._launch(projectiles.Torpedo(), "Bare",
                                        (here.x, here.y, here.z + 30.0),
                                        (0.0, 0.0, 0.0), sc.set)
            assert bare.__dict__.get("_vis_native") is None
        ts.advance()
        if k in NON_SHIP:
            seen["non_ship_phaser"] += bool(
                _lit_at(shooter.GetPhaserSystem(), probe))
            seen["non_ship_tractor"] += bool(
                _lit_at(shooter.GetTractorBeamSystem(), probe))
        if k == LATE_BUMP:
            assert not posed.IsDead()
            assert _lit_at(poser.GetPhaserSystem(), posed), \
                "premise: the firer's phasers are lit at the posed ship"
            assert poser.GetTargetSubsystem() is locked
            assert part in articulation.posed_part_names(posed)
            # The drawn aim point is the POSED mount, not the rest point.
            at = ss._subsystem_world_position(locked, None)
            rest = TorpedoScene._rest_mount(posed, mount)
            assert (at.x, at.y, at.z) != rest, \
                "premise: the pose moves the locked mount"
            seen["posed_lock"] += 1
            nc.bump_part_gen()
        if k >= BARE_FROM:
            seen["bare"] += bare in projectiles._active
        f = golden_beam_frame(list(iter_ships()), ts.ship_instances)
        f.update((key, v) for key, v in golden_torpedo_frame(ts).items()
                 if key in ("torps", "lights"))
        frames.append(f)
    assert seen == {"non_ship_phaser": len(NON_SHIP),
                    "non_ship_tractor": len(NON_SHIP), "posed_lock": 1,
                    "bare": EDGE_FRAMES - BARE_FROM}, seen
    if render_golden.recording():
        render_golden.record("edge_cases", frames)
    # Task 2: == [] (the native feeds answer every case).
    assert render_golden.differing_frames("edge_cases", frames) == \
        EXPECTED_NATIVE_DIFFS
