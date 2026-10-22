"""Lights and emitters on a lost structure part go out.

Layered hull damage phase 4 (spec 2026-10-22-layered-damage-p4-finish §2.3).
On an UNRIGGED hull, plating wear that cuts a structure part off sets that
part's bit in the instance's severed mask (native `Instance::severed_parts`,
read through `host_io.instance_severed_parts`) and the part leaves as a chunk.
Everything that shone or emitted from it must stop: the running lights, the
subsystem emitter lights, and the particle emitters of the subsystems inside.

A light is on a lost part when `structure_part_at` labels its REST position
with a part whose bit is set in the mask. The native side is faked here (the
mask and the part labels); every assertion is on what the renderer would be
sent -- the running-light list, the dynamic-light feed -- or on a particle
controller's emitting state.
"""
import pytest

import App
from engine import host_io, host_loop
from engine.appc import light_emitters, particles
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.properties import SubsystemProperty, TGModelPropertySet
from engine.host_loop import _build_emitter_light_render_data
from tests.helpers.viewed_set import release_viewed_set, viewed_set

NACELLE_PART = 2
NACELLE_PT = (2.0, 0.0, 0.0)     # ship units, labelled NACELLE_PART
BODY_PT = (0.0, 0.5, 0.0)        # ship units, labelled 0 (the main body)
OFF_HULL_PT = (9.0, 0.0, 0.0)    # outside every voxel: -1


class _Native:
    """The two native reads, faked: one instance's severed mask and the
    structure-part labels (x > 1.5 GU is the nacelle; beyond 5 GU is off the
    voxels). Records every `structure_part_at` point it is asked about."""

    def __init__(self, iid):
        self.iid = iid
        self.mask = 0
        self.asked = []

    def severed(self, iid):
        return self.mask if iid == self.iid else 0

    def part_at(self, iid, p):
        self.asked.append(tuple(p))
        if iid != self.iid or abs(p[0]) > 5.0:
            return -1
        return NACELLE_PART if p[0] > 1.5 else 0


@pytest.fixture
def native(monkeypatch):
    def make(iid):
        n = _Native(iid)
        monkeypatch.setattr(host_io, "instance_severed_parts", n.severed,
                            raising=False)
        monkeypatch.setattr(host_io, "structure_part_at", n.part_at)
        return n
    return make


# ── running lights ───────────────────────────────────────────────────────────

class _FakeRenderer:
    def __init__(self):
        self.lights = {}
        self.calls = []

    def set_running_lights(self, iid, lights, phase):
        self.lights[iid] = (list(lights), phase)
        self.calls.append(iid)

    def set_running_light_levels(self, levels):
        pass

    def set_running_light_dials(self, *a):
        pass


class _LitShip:
    """An unrigged hull with BlinkingLightProperty lights at `points`."""

    def __init__(self, points, scale=1.0):
        self._pset = TGModelPropertySet()
        for i, xyz in enumerate(points):
            p = App.BlinkingLightProperty_Create("L%d" % i)
            pt = TGPoint3()
            pt.SetXYZ(*xyz)
            p.SetPosition(pt)
            self._pset.AddToSet("Scene Root", p)
        self._scale = scale

    def GetPropertySet(self): return self._pset
    def GetName(self): return "USS Unrigged"
    def GetScale(self): return self._scale
    def GetCloakingSubsystem(self): return None
    def GetPowerSubsystem(self): return None
    def IsDying(self): return 0
    def IsDead(self): return 0


class _Session:
    def __init__(self, mapping):
        self.ship_instances = dict(mapping)
        self.ship_running_lights = {}
        self.ship_running_light_specs = {}
        self.scope_hidden = set()


def _sent(r, iid):
    return [tuple(l[:3]) for l in r.lights[iid][0]]


def test_LightsOnALostPartGoOut(native):
    """The nacelle's running light is dropped the frame its part is severed;
    the body's stays. Unrigged, so only the severed mask can trigger it."""
    n = native(31)
    r = _FakeRenderer()
    ship = _LitShip([NACELLE_PT, BODY_PT])
    s = _Session({ship: 31})
    host_loop._register_running_lights(r, s, ship, 31)
    host_loop._push_running_lights(r, s)
    assert _sent(r, 31) == [pytest.approx(NACELLE_PT), pytest.approx(BODY_PT)]
    assert r.calls == [31]

    n.mask = 1 << NACELLE_PART
    host_loop._push_running_lights(r, s)
    assert _sent(r, 31) == [pytest.approx(BODY_PT)]
    assert r.calls == [31, 31]

    host_loop._push_running_lights(r, s)    # mask unchanged: nothing resent
    assert r.calls == [31, 31]


def test_running_lights_on_an_intact_part_stay_lit(native):
    """A severed bit for some OTHER part, or a light off the voxels (-1),
    leaves the light lit."""
    n = native(32)
    r = _FakeRenderer()
    ship = _LitShip([NACELLE_PT, OFF_HULL_PT])
    s = _Session({ship: 32})
    host_loop._register_running_lights(r, s, ship, 32)
    n.mask = 1 << 5
    host_loop._push_running_lights(r, s)
    assert _sent(r, 32) == [pytest.approx(NACELLE_PT),
                            pytest.approx(OFF_HULL_PT)]


def test_an_unsevered_ship_never_asks_for_part_labels(native):
    """The per-frame cost gate: with an empty mask no light is labelled."""
    n = native(33)
    r = _FakeRenderer()
    ship = _LitShip([NACELLE_PT, BODY_PT])
    s = _Session({ship: 33})
    host_loop._register_running_lights(r, s, ship, 33)
    for _ in range(3):
        host_loop._push_running_lights(r, s)
    assert n.asked == []
    assert r.calls == [33]


def test_the_rest_position_is_scaled_into_game_units(native):
    """`structure_part_at` takes body-frame GAME UNITS and divides by the
    instance's model->GU scale, which includes the ship's GetScale(); authored
    light positions are unscaled ship units, so a SetScale(2) hull must be
    asked about the doubled point."""
    n = native(34)
    r = _FakeRenderer()
    ship = _LitShip([(1.0, 0.0, 0.0)], scale=2.0)   # 2.0 GU: on the nacelle
    s = _Session({ship: 34})
    host_loop._register_running_lights(r, s, ship, 34)
    n.mask = 1 << NACELLE_PART
    host_loop._push_running_lights(r, s)
    assert n.asked == [pytest.approx((2.0, 0.0, 0.0))]
    assert _sent(r, 34) == []


# ── subsystem emitter lights ─────────────────────────────────────────────────

@pytest.fixture
def _viewed():
    viewed_set()
    yield
    release_viewed_set()


def _prop(position):
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, "point")
    p.SetLightEmitterPosition(0, *position)
    p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
    p.SetLightEmitterLength(0, 0.0)
    p.SetLightEmitterRadius(0, 0.2)
    p.SetLightEmitterColor(0, 1.0, 1.0, 1.0)
    p.SetLightEmitterIntensity(0, 1.0)
    return p


class _HealthySub:
    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self): return self._prop
    def IsDestroyed(self): return False
    def IsDisabled(self): return False


class _EmitterShip:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetContainingSet(self): return viewed_set()
    def GetScale(self): return 1.0


def _emitter_lights(ship, iid, *positions):
    entries = []
    for pos in positions:
        prop = _prop(pos)
        spec = light_emitters.baked_emitters(prop)[0]
        entries.append((_HealthySub(prop), False, False, 0.0, spec,
                        light_emitters.emitter_spec_to_struct(spec)))
    return _build_emitter_light_render_data({ship: iid}, {iid: entries})


def test_emitter_lights_on_a_lost_part_go_out(native, _viewed):
    n = native(41)
    ship = _EmitterShip()
    assert len(_emitter_lights(ship, 41, NACELLE_PT, BODY_PT)) == 2
    n.mask = 1 << NACELLE_PART
    (d,) = _emitter_lights(ship, 41, NACELLE_PT, BODY_PT)
    assert d["position"] == pytest.approx(BODY_PT)


def test_emitter_lights_read_the_mask_once_per_ship(native, _viewed,
                                                    monkeypatch):
    n = native(42)
    reads = []

    def counted(iid):
        reads.append(iid)
        return n.severed(iid)
    monkeypatch.setattr(host_io, "instance_severed_parts", counted,
                        raising=False)
    _emitter_lights(_EmitterShip(), 42, NACELLE_PT, BODY_PT, BODY_PT)
    assert reads == [42]


# ── particle emitters on subsystems inside the chunk ─────────────────────────

class _Sub:
    def __init__(self, pos, name):
        self._pos = TGPoint3(*pos)
        self.name = name
        self.condition = 100.0

    def GetPosition(self): return self._pos
    def GetName(self): return self.name
    def SetCondition(self, v): self.condition = v
    def IsDestroyed(self): return self.condition <= 0.0


class _BreakShip:
    def __init__(self, subs):
        self._subs = list(subs)
        self._loc = TGPoint3(0, 0, 0)
        self._rot = TGMatrix3()
        self._articulation_poses = {}

    def GetRadius(self): return 3.5
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0, 0, 0)
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0
    def GetHull(self): return None
    def _iter_subsystems(self): return iter(self._subs)


@pytest.fixture
def _breakup(monkeypatch):
    from engine.appc import debris_chunk as dc, damage_geometry as dg
    from engine.appc import hull_breakup

    class _R:
        def set_world_transform(self, *a): pass
        def destroy_instance(self, *a): pass
    dc.clear(_R()); dg.reset(); hull_breakup.reset(); particles.reset()
    monkeypatch.setattr(dc, "spawn", lambda *a, **k: ("chunk", a[0]))
    yield hull_breakup
    dc.clear(_R()); dg.reset(); hull_breakup.reset(); particles.reset()


def _controller(emit_from, emit_pos=None):
    c = particles.AnimTSParticleController_Create()
    c.SetEmitFromObject(emit_from)
    if emit_pos is not None:
        c.SetEmitPositionAndDirection(TGPoint3(*emit_pos),
                                      TGPoint3(0.0, 0.0, 1.0))
    particles.register(c)
    return c


def test_particle_emitters_inside_a_lost_part_stop(native, _breakup,
                                                   monkeypatch):
    """Both legs of `part_severance._silence_emitters_on`: a controller
    emitting FROM a subsystem inside the chunk, and one emitting from the
    SHIP at a body point (MODEL units, as `world_to_body` returns) on the
    lost part. Controllers on the body keep emitting."""
    native(51)
    nacelle = _Sub(NACELLE_PT, "Port Warp")
    bridge = _Sub(BODY_PT, "Bridge")
    ship = _BreakShip([nacelle, bridge])
    from_nacelle = _controller(nacelle)
    from_bridge = _controller(bridge)
    smoke_on_nacelle = _controller(ship, (200.0, 0.0, 0.0))   # 2.0 ship units
    smoke_on_body = _controller(ship, (0.0, 50.0, 0.0))
    monkeypatch.setattr(host_io, "hull_split_parts", lambda iid: [{
        "parts": [NACELLE_PART], "instance_id": 61, "voxels": 600,
        "total_voxels": 4000, "centroid": (2.0, 0.0, 0.0),
        "bounds_min": (1.5, -0.5, -0.5), "bounds_max": (2.5, 0.5, 0.5),
        "radius_gu": 0.75}])
    _breakup.after_wear(ship, 51, now=10.0)
    assert nacelle.IsDestroyed() and not bridge.IsDestroyed()
    assert not from_nacelle.is_emitting()
    assert not smoke_on_nacelle.is_emitting()
    assert from_bridge.is_emitting()
    assert smoke_on_body.is_emitting()


# ── label cache (per-frame cost after a severance) ───────────────────────────

def test_emitter_lights_are_labelled_once_per_severed_mask(native, _viewed):
    """After a severance every frame asks which part each emitter light sits
    on. The label depends only on (instance, rest position), so it is cached
    per (iid, severed mask): N frames cost one `structure_part_at` per light,
    and a NEW severance (the mask changes) relabels once more."""
    n = native(43)
    ship = _EmitterShip()
    n.mask = 1 << NACELLE_PART
    for _ in range(5):
        (d,) = _emitter_lights(ship, 43, NACELLE_PT, BODY_PT)
        assert d["position"] == pytest.approx(BODY_PT)
    assert len(n.asked) == 2, n.asked

    n.mask = (1 << NACELLE_PART) | (1 << 5)
    for _ in range(5):
        _emitter_lights(ship, 43, NACELLE_PT, BODY_PT)
    assert len(n.asked) == 4, n.asked


def test_label_cache_is_dropped_with_the_instance(native, _viewed):
    """A recycled iid must not inherit a destroyed hull's labels: forgetting
    the instance (teardown) and `reset()` (mission swap) both empty it."""
    from engine.appc import hull_breakup
    n = native(44)
    ship = _EmitterShip()
    n.mask = 1 << NACELLE_PART
    _emitter_lights(ship, 44, NACELLE_PT)
    hull_breakup.forget_instance(44)
    _emitter_lights(ship, 44, NACELLE_PT)
    assert len(n.asked) == 2
    hull_breakup.reset()
    _emitter_lights(ship, 44, NACELLE_PT)
    assert len(n.asked) == 3


def test_mission_session_teardown_forgets_part_labels(native, _viewed):
    """`MissionSession.teardown` destroys every ship instance; their cached
    labels go with them."""
    from engine.appc import hull_breakup
    n = native(45)
    ship = _EmitterShip()
    n.mask = 1 << NACELLE_PART
    _emitter_lights(ship, 45, NACELLE_PT)
    assert 45 in hull_breakup._part_labels

    class _R:
        def destroy_instance(self, iid): pass
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_instances[ship] = 45
    sess.teardown(_R())
    assert 45 not in hull_breakup._part_labels


def test_a_failed_label_lookup_is_not_cached(native, monkeypatch):
    """`part_at_rest_point` swallows a failing `structure_part_at` and answers
    -1. That -1 is not a label: caching it would keep a light on a lost part
    lit for as long as the mask holds. Only real lookups are cached; a failed
    one is asked again next frame."""
    from engine.appc import hull_breakup
    n = native(45)
    n.mask = 1 << NACELLE_PART
    failures = [RuntimeError("binding hiccup")]

    def flaky(iid, p):
        if failures:
            raise failures.pop()
        return n.part_at(iid, p)
    monkeypatch.setattr(host_io, "structure_part_at", flaky)
    ship = _EmitterShip()
    assert hull_breakup.on_severed_part(ship, 45, NACELLE_PT) is False
    assert hull_breakup.on_severed_part(ship, 45, NACELLE_PT) is True, \
        "the failed lookup's -1 was cached"
    assert hull_breakup.on_severed_part(ship, 45, NACELLE_PT) is True
    assert len(n.asked) == 1, "a real label is still looked up once"
