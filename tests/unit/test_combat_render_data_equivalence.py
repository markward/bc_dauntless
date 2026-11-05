"""The combat render builders (torpedoes, torpedo lights, phaser and tractor
beams) must emit exactly the descriptors they always did. No golden records
them, so this keeps the ORIGINAL builders here, verbatim, as the oracle and
compares repr() (so every float bit) over a scene with several torpedo types,
disruptors, firing phaser banks (shield-bubble end, locked-subsystem end) and
a tractor."""
import pytest

import App
from engine import host_loop as hl
from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo, register
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    HullSubsystem, ShieldSubsystem, PhaserSystem, PhaserBank,
    TractorBeam, TractorBeamSystem)
from engine.appc.properties import (
    PhaserProperty, TractorBeamProperty, WeaponSystemProperty)
from tests.helpers.viewed_set import (
    place_in_viewed_set, release_viewed_set, viewed_set)
from tests.helpers.native_on import native_combat_on  # noqa: F401

pytestmark = pytest.mark.usefixtures("native_combat_on")

_frames = hl._frames


# ── the oracle: the builders as they were before the change ────────────────

def _old_torpedoes():
    out = []
    view = _frames.viewing_set()
    if view is None:
        return out
    textures = {}

    def texture(path):
        r = textures.get(path)
        if r is None:
            r = textures[path] = hl._resolve_game_texture(path)
        return r

    for t in projectiles._active:
        p = t.GetTranslate()
        pos = _frames.to_render(view, _frames.containing_set(t), p.x, p.y, p.z)
        if pos is None:
            continue
        out.append({
            "position": pos,
            "core_texture": texture(t._core_texture),
            "core_color": hl._dim_color(hl._color_tuple(t._core_color),
                                        hl.TORPEDO_BRIGHTNESS),
            "core_size_a": t._core_size_a,
            "core_size_b": t._core_size_b,
            "glow_texture": texture(t._glow_texture),
            "glow_color": hl._dim_color(hl._color_tuple(t._glow_color),
                                        hl.TORPEDO_BRIGHTNESS),
            "glow_size_a": t._glow_size_a,
            "glow_size_b": t._glow_size_b,
            "glow_size_c": t._glow_size_c,
            "flares_texture": texture(t._flares_texture),
            "flares_color": hl._dim_color(hl._color_tuple(t._flares_color),
                                          hl.TORPEDO_BRIGHTNESS),
            "num_flares": t._num_flares,
            "flares_size_a": t._flares_size_a,
            "flares_size_b": t._flares_size_b,
            "age": t._age,
            "id": int(t._id),
            "is_disruptor": bool(t._is_disruptor),
            "forward": hl._torpedo_forward(t),
            "shell_color": hl._color_tuple(t._shell_color),
            "bolt_core_color": hl._color_tuple(t._bolt_core_color),
            "bolt_length": float(t._bolt_length),
            "bolt_width": float(t._bolt_width),
        })
    return out


def _old_torpedo_lights():
    out = []
    view = _frames.viewing_set()
    if view is None:
        return out
    for t in projectiles._active:
        if t._is_disruptor:
            continue
        radius = hl._TORPEDO_LIGHT_RADIUS_SCALE * max(
            t._glow_size_a, t._glow_size_b)
        if radius <= 0:
            continue
        t_pos = t.GetTranslate()
        pos = _frames.in_view(view, _frames.containing_set(t),
                              t_pos.x, t_pos.y, t_pos.z)
        if pos is None:
            continue
        fade = hl._camera_distance_fade(pos)
        if fade is None:
            continue
        out.append({
            "position": _frames.view_to_render(pos),
            "color": hl._color_tuple(t._glow_color)[:3],
            "radius": radius,
            "intensity": hl._TORPEDO_LIGHT_INTENSITY * fade,
        })
    return out


def _ships_in_view(ships):
    view = _frames.viewing_set()
    if view is None:
        return
    for ship in ships:
        pSet = _frames.containing_set(ship)
        if _frames.offset_between(view, pSet) is not None:
            yield ship, pSet, view


def _old_phasers(ships, ship_instances=None):
    out = []
    for ship, pSet, view in _ships_in_view(ships):
        sys_ = ship.GetPhaserSystem() if hasattr(ship, "GetPhaserSystem") else None
        if sys_ is None:
            continue
        for i in range(sys_.GetNumWeapons()):
            bank = sys_.GetWeapon(i)
            if bank is None or not bank.IsFiring():
                continue
            for d in hl._beam_pair_in_view(
                    hl._beam_descriptor_pair(ship, bank, ship_instances),
                    view, pSet, bank._target):
                c = d["color"]
                d["color"] = (c[0] * hl.PHASER_BEAM_BRIGHTNESS,
                              c[1] * hl.PHASER_BEAM_BRIGHTNESS,
                              c[2] * hl.PHASER_BEAM_BRIGHTNESS,
                              c[3])
                out.append(d)
    return out


def _old_tractors(ships, ship_instances=None):
    out = []
    for ship, pSet, view in _ships_in_view(ships):
        sys_ = (ship.GetTractorBeamSystem()
                if hasattr(ship, "GetTractorBeamSystem") else None)
        if sys_ is None:
            continue
        for i in range(sys_.GetNumWeapons()):
            bank = sys_.GetWeapon(i)
            if bank is None or not bank.IsFiring():
                continue
            for d in hl._beam_pair_in_view(
                    hl._beam_descriptor_pair(ship, bank, ship_instances),
                    view, pSet, bank._target):
                d["end_width_scale"] = hl.TRACTOR_BEAM_END_WIDTH_SCALE
                c = d["color"]
                d["color"] = (c[0] * hl.TRACTOR_BEAM_BRIGHTNESS,
                              c[1] * hl.TRACTOR_BEAM_BRIGHTNESS,
                              c[2] * hl.TRACTOR_BEAM_BRIGHTNESS,
                              c[3])
                out.append(d)
    return out


# ── the scene ──────────────────────────────────────────────────────────────

def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


def _photon(at, vel, core=(1.0, 0.99, 0.39), glow=(1.0, 0.25, 0.0)):
    t = Torpedo()
    gc = _color(*glow)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga", _color(*core), 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga", gc, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", gc, 8, 0.7, 0.4)
    t._velocity = App.TGPoint3(*vel)
    t._id = len(projectiles._active) + 100
    t._age = 0.37 * len(projectiles._active)
    place_in_viewed_set(t)
    t.SetTranslateXYZ(*at)
    register(t)
    return t


def _disruptor(at, vel):
    t = Torpedo()
    t.CreateDisruptorModel(_color(0.17, 1.0, 0.17), _color(0.64, 1.0, 0.64),
                           2.0, 0.2)
    t._velocity = App.TGPoint3(*vel)
    t._id = len(projectiles._active) + 100
    place_in_viewed_set(t)
    t.SetTranslateXYZ(*at)
    register(t)
    return t


def _shielded(name, at):
    s = ShipClass_Create(name)
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(100000.0)
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 100000.0)
    s.SetShieldSubsystem(ss)
    s._shield_hull_box = ((0.0, 0.0, 0.0), (232.0, 322.0, 70.0))
    s._radius = 400.0
    place_in_viewed_set(s)
    s.SetTranslateXYZ(*at)
    return s


def _phaser_bank(name, color, firing, target):
    b = PhaserBank(name)
    p = PhaserProperty(name)
    p.SetMaxCharge(5.0)
    p.SetMainRadius(0.1 + 0.01 * len(name))
    p.SetNumSides(8)
    p.SetOuterShellColor(_color(*color))
    p.SetInnerCoreColor(_color(color[2], color[0], color[1]))
    b.SetProperty(p)
    b._target = target
    b._firing = firing
    return b


def _phaser_ship(name, at, banks):
    s = _shielded(name, at)
    sysm = PhaserSystem("Phasers")
    sysm.SetProperty(WeaponSystemProperty("Phasers"))
    sysm._parent_ship = s
    s._phaser_system = sysm
    for b in banks:
        sysm.AddChildSubsystem(b)
    return s


def _tractor_ship(name, at, target, firing=True):
    s = _shielded(name, at)
    em = TractorBeam("Aft Tractor")
    prop = TractorBeamProperty("Aft Tractor")
    prop.SetNumSides(12)
    prop.SetMainRadius(0.075)
    prop.SetOuterShellColor(_color(0.4, 0.4, 1.0))
    prop.SetInnerCoreColor(_color(0.4, 0.4, 1.0))
    em.SetProperty(prop)
    em._target = target
    em._firing = firing
    sysm = TractorBeamSystem("Tractors")
    sysm.SetProperty(WeaponSystemProperty("Tractors"))
    sysm._parent_ship = s
    s._tractor_beam_system = sysm
    sysm.AddChildSubsystem(em)
    return s


@pytest.fixture
def scene():
    projectiles._active.clear()
    viewed_set()
    _photon((10, 20, 30), (3, 4, 0))
    _photon((-5, 7, 9), (0, 0, 0), core=(0.2, 0.9, 0.4), glow=(0.1, 0.3, 1.0))
    _disruptor((1, 2, 3), (0, 5, 0))
    _disruptor((4, 5, 6), (0, 0, 0))
    _photon((50, 0, 0), (1, 1, 1), core=(1, 1, 1), glow=(1, 0, 1))
    tgt = _shielded("TargetA", (0.0, 600.0, 0.0))
    tgt2 = _shielded("TargetB", (900.0, 0.0, 0.0))
    a = _phaser_ship("A", (0.0, 0.0, 0.0), [
        _phaser_bank("p1", (1.0, 0.5, 0.1), True, tgt),
        _phaser_bank("idle", (0.3, 0.3, 0.3), False, tgt),
        _phaser_bank("p2", (0.9, 0.2, 0.2), True, tgt2),
    ])
    c = _phaser_ship("C", (100.0, 0.0, 0.0), [
        _phaser_bank("q1", (0.2, 0.8, 0.3), True, tgt)])
    # Locked subsystem target on C.
    c.SetTargetSubsystem(tgt.GetHull())
    quiet = _phaser_ship("Quiet", (200.0, 0.0, 0.0), [
        _phaser_bank("z", (1, 1, 1), False, tgt)])
    tr = _tractor_ship("T", (0.0, -300.0, 0.0), tgt2)
    tr_idle = _tractor_ship("T2", (0.0, -500.0, 0.0), tgt, firing=False)
    ships = [a, tgt, c, quiet, tr, tgt2, tr_idle]
    yield ships
    projectiles._active.clear()
    release_viewed_set()


def test_torpedo_feed_identical(scene):
    new = hl._build_torpedo_render_data()
    assert len(new) == 5
    assert repr(new) == repr(_old_torpedoes())
    # A second frame (cache warm) still matches, after the torpedoes move.
    for t in projectiles._active:
        t._age += 0.5
        t.SetTranslateXYZ(t.GetTranslate().x + 1.0, 2.0, 3.0)
    assert repr(hl._build_torpedo_render_data()) == repr(_old_torpedoes())


def test_torpedo_feed_follows_brightness_knob(scene, monkeypatch):
    hl._build_torpedo_render_data()
    monkeypatch.setattr(hl, "TORPEDO_BRIGHTNESS", 0.3)
    assert repr(hl._build_torpedo_render_data()) == repr(_old_torpedoes())


def test_torpedo_feed_follows_a_remodel(scene):
    hl._build_torpedo_render_data()
    t = projectiles._active[0]
    t.CreateDisruptorModel(_color(1, 0, 0), _color(0, 0, 1), 1.5, 0.1)
    assert repr(hl._build_torpedo_render_data()) == repr(_old_torpedoes())
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga", _color(0, 1, 0), 0.5, 0.6,
        "data/Textures/Tactical/TorpedoGlow.tga", _color(0, 0, 1), 1.0, 1.0, 1.0,
        "data/Textures/Tactical/TorpedoFlares.tga", _color(1, 1, 0), 3, 0.2, 0.1)
    assert repr(hl._build_torpedo_render_data()) == repr(_old_torpedoes())
    assert repr(hl._build_dynamic_light_render_data()) == \
        repr(_old_torpedo_lights())


def test_torpedo_lights_identical(scene):
    new = hl._build_dynamic_light_render_data()
    assert new
    assert repr(new) == repr(_old_torpedo_lights())


def test_beams_identical(scene):
    ph = hl._build_phaser_beam_render_data(scene)
    tr = hl._build_tractor_beam_render_data(scene)
    assert len(ph) == 6 and len(tr) == 2
    assert repr(ph) == repr(_old_phasers(scene))
    assert repr(tr) == repr(_old_tractors(scene))


def test_beams_follow_firing_state(scene):
    a = scene[0]
    a.GetPhaserSystem().GetWeapon(1)._firing = True      # idle bank lights
    a.GetPhaserSystem().GetWeapon(0)._firing = False
    assert repr(hl._build_phaser_beam_render_data(scene)) == \
        repr(_old_phasers(scene))


# ── firing ships outside the viewed set, and in another region ─────────────

def _region_scene():
    """A viewed REAL region (Ona1) with a firing ship, a firing ship in the
    same system's other region (Ona2: another anchor, same frame), and a
    firing ship in a plain set (another frame: out of view)."""
    from engine.appc.sets import SetClass_Create
    from tests.helpers.mapped_regions import load_region
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "ElsewhereFrame")

    def ship(pSet, name, at, banks):
        s = _phaser_ship(name, at, banks)    # born in the "Viewed" test set
        s.GetContainingSet().RemoveObjectFromSet("obj_%d" % id(s))
        pSet.AddObjectToSet(s, name)
        s.SetTranslateXYZ(*at)
        return s

    tgt = ship(ona1, "RTarget", (0.0, 600.0, 0.0), [])
    here = ship(ona1, "Here", (0.0, 0.0, 0.0), [
        _phaser_bank("h1", (1.0, 0.5, 0.1), True, tgt)])
    cross = ship(ona2, "Cross", (50.0, 10.0, 0.0), [
        _phaser_bank("c1", (0.2, 0.8, 0.3), True, tgt)])
    away = ship(other, "Away", (5.0, 5.0, 5.0), [
        _phaser_bank("a1", (0.9, 0.2, 0.2), True, tgt)])
    App.g_kSetManager.MakeRenderedSet("Ona1")
    return [here, tgt, cross, away]


def test_beams_identical_for_out_of_view_and_cross_region_firing_ships():
    projectiles._active.clear()
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    try:
        ships = _region_scene()
        ph = hl._build_phaser_beam_render_data(ships)
        old = _old_phasers(ships)
        assert ph, "the in-view ship fires"
        assert repr(ph) == repr(old)
        # Only ships whose set shares the viewed frame draw: Here + Cross.
        assert len(old) == 4          # two banks' descriptor pairs
        assert repr(hl._build_phaser_beam_render_data(ships)) == repr(old)
    finally:
        App.g_kSetManager.ClearRenderedSet()
        App.g_kSetManager._sets.clear()
