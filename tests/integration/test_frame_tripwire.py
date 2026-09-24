"""The frame tripwire (system-frames spec Sec 6): the integration gate every
converted consumer must pass.

Setup mirrors the final review's measured scenario: Ona1/Ona2/Ona3 (one
system), XiEntrades4 (a different system) and an unmapped Starbase12. A
"sentinel" ship sits at IDENTICAL local numbers -- XiEntrades4's real arrival
point (0, 5236, 1.5) -- in every one of the five sets, and each mapped
region additionally carries a body at ITS OWN region's real mapped
position (Ona1's real planet, etc.). A consumer that compares RAW numbers
(the retired Plan-1 same-set-identity stopgap's failure mode) would treat
every sentinel as co-located and would let Ona 1's planet strike the XiEntrades4
ship, exactly as it once did after a live warp. A consumer that compares by
FRAME never does -- except within the one real system where region anchors
genuinely put two objects close together.
"""
import pytest

import App
from engine.appc import (
    collisions, damage_eligibility, explosion_lights, hit_vfx, projectiles,
    splash_damage,
)
from engine.appc.lens_flare import LensFlare_Create, aggregate_lens_flares_for_renderer
from engine.appc.math import TGPoint3
from engine.appc.planet import Planet_Create, Sun
from engine.appc.projectiles import Torpedo, register
from engine.appc.sets import SetClass_Create
from engine.appc.ships import ShipClass
from engine.systems import frames, map as system_map
import engine.host_loop as host_loop
from tests.helpers import bc_assets
from tests.helpers.bc_assets import require_game_asset
from tests.helpers.mapped_regions import load_region

ARRIVAL = (0.0, 5236.0, 1.5)   # the measured XiEntrades4 arrival point


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        projectiles._active.clear()
        explosion_lights.reset()
        hit_vfx._active.clear()
        host_loop._note_camera_eye(None)
    _clear()
    yield
    _clear()


def _plain_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def _sentinel(pSet, name):
    """A ship at the shared ARRIVAL numbers, closing -- "a pair at rest is
    not a contact" (test_cross_set_interaction_gate.py)."""
    s = ShipClass()
    s.SetName(name)
    s.SetTranslateXYZ(*ARRIVAL)
    s.SetRadius(1.0)
    s.SetMass(1000.0)
    s.SetVelocity(TGPoint3(-1.0, 0.7, 0.0))
    pSet.AddObjectToSet(s, name)
    return s


def _region_body_info(system, region):
    """(local_xyz, radius_gu) of `region`'s own mapped body -- e.g. Ona1's
    real planet, at the real local position a same-region object sits at."""
    m = system_map.load(system)
    r = next(rr for rr in m.regions if rr.set_name == region)
    body = next(b for b in m.bodies if b.name == r.body_names[0])
    local = tuple(p - a for p, a in zip(body.position_gu, r.anchor_gu))
    return local, body.radius_gu


REGIONS = {
    "Ona1": ("Ona", "Ona1"),
    "Ona2": ("Ona", "Ona2"),
    "Ona3": ("Ona", "Ona3"),
    "XiEntrades4": ("XiEntrades", "XiEntrades4"),
}


@pytest.fixture
def world():
    """sets, sentinels, bodies -- keyed by set name -- for Ona1/Ona2/Ona3,
    XiEntrades4 and Starbase12."""
    sets = {name: load_region(system, region)
            for name, (system, region) in REGIONS.items()}
    sets["Starbase12"] = _plain_set("Starbase12")

    sentinels = {name: _sentinel(pSet, name + "Sentinel")
                for name, pSet in sets.items()}

    bodies = {}
    for name, (system, region) in REGIONS.items():
        (x, y, z), radius = _region_body_info(system, region)
        p = Planet_Create(radius, "")
        p.SetTranslateXYZ(x, y, z)
        sets[name].AddObjectToSet(p, name + "Body")
        bodies[name] = p

    return sets, sentinels, bodies


# ── (a) collisions: nothing pairs across frames ──────────────────────────────

def test_collisions_never_pair_across_frames(world):
    sets, sentinels, bodies = world
    hits = collisions.resolve_collisions(list(collisions.iter_collidables()))
    for a_obj, b_obj, _c, _v in hits:
        assert frames.same_frame(a_obj, b_obj), (
            "a collision paired two objects in different frames")
    xi_sentinel = sentinels["XiEntrades4"]
    ona1_body = bodies["Ona1"]
    struck_pairs = [{id(a_obj), id(b_obj)} for a_obj, b_obj, _c, _v in hits]
    assert {id(xi_sentinel), id(ona1_body)} not in struck_pairs, (
        "the XiEntrades4 ship was struck by Ona 1's planet")


# ── (b) splash: reaches nothing outside the dying ship's frame ──────────────

def test_splash_touches_no_ship_outside_its_frame(world, monkeypatch):
    sets, sentinels, bodies = world
    struck = []
    import engine.appc.combat as combat
    monkeypatch.setattr(
        combat, "apply_hit",
        lambda ship, *a, **k: struck.append(ship))

    # A same-frame victim close to the Ona1 sentinel, to prove splash still
    # reaches its own frame (a paired same-frame control).
    victim = ShipClass()
    victim.SetName("OnaVictim")
    victim.SetTranslateXYZ(ARRIVAL[0] + 5.0, ARRIVAL[1], ARRIVAL[2])
    victim.SetRadius(1.0)
    sets["Ona1"].AddObjectToSet(victim, "OnaVictim")

    dying = sentinels["Ona1"]
    dying.SetSplashDamage(5000.0, 50.0)
    splash_damage.apply(dying)

    assert victim in struck, "splash never reached its own frame"
    for ship in struck:
        assert frames.same_frame(ship, dying), (
            "splash reached a ship outside the dying ship's frame")
    for name in ("Ona2", "Ona3", "XiEntrades4", "Starbase12"):
        assert sentinels[name] not in struck


# ── (c) torpedoes: hit nothing outside their own frame ──────────────────────

def test_torpedo_hits_nothing_outside_ona_frame(world):
    """No Ona1 ship is offered as a target here on purpose: a torpedo hits at
    most one ship per tick (it stops at the first match), so a legitimate
    same-frame hit would mask a cross-frame one -- this isolates the
    cross-frame check cleanly."""
    sets, sentinels, bodies = world
    src = ShipClass()
    src.SetName("TorpSrc")
    src.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    sets["Ona1"].AddObjectToSet(src, "TorpSrc")

    t = Torpedo()
    t.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    t._velocity = TGPoint3(0.0, 6.0, 0.0)       # lands exactly on ARRIVAL this tick
    t._ttl = 30.0
    t._source_ship = src
    t._damage = 100.0
    register(t)
    assert t.GetContainingSet() is sets["Ona1"]

    other_frame_ships = [sentinels[name] for name in
                         ("Ona2", "Ona3", "XiEntrades4", "Starbase12")]
    hits = projectiles.update_all(1.0, other_frame_ships)
    assert hits == [], "a torpedo in Ona1 hit a ship outside its own frame"


# ── (d) damage eligibility: a cross-frame ship never outranks a same-frame
#        ship of equal size ─────────────────────────────────────────────────

def test_damage_eligibility_never_ranks_cross_frame_above_same_frame(world):
    sets, sentinels, bodies = world
    player = sentinels["XiEntrades4"]

    wingman = ShipClass()
    wingman.SetName("Wingman")
    wingman.SetTranslateXYZ(ARRIVAL[0] + 50.0, ARRIVAL[1], ARRIVAL[2])
    wingman.SetRadius(1.0)                       # same radius as every sentinel
    sets["XiEntrades4"].AddObjectToSet(wingman, "Wingman")

    cross_frame = sentinels["Ona1"]              # radius 1.0 too -- equal size

    eligible = damage_eligibility.select_eligible(
        player, [player, wingman, cross_frame], max_count=2)
    assert id(wingman) in eligible, "a same-frame ship of equal size lost out"
    assert id(cross_frame) not in eligible, (
        "a cross-frame ship outranked a same-frame ship of equal size")


# ── (e) render feeds: XiEntrades4 viewed carries nothing from Ona/Starbase12 ─

def _viewed_torpedo(pSet, name):
    t = Torpedo()
    c = App.TGColorA()
    c.SetRGBA(1.0, 0.25, 0.0, 1.0)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga", c, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga", c, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", c, 8, 0.7, 0.4,
    )
    t.SetTranslateXYZ(*ARRIVAL)
    pSet.AddObjectToSet(t, name)
    register(t)
    return t


def test_render_feeds_exclude_ona_and_starbase_when_xientrades4_viewed(world):
    sets, sentinels, bodies = world
    xi4 = sets["XiEntrades4"]
    App.g_kSetManager.MakeRenderedSet("XiEntrades4")
    assert frames.viewing_set() is xi4

    # -- planets: Ona bodies (radius 1800) never appear; XiEntrades4's (2400)
    #    does.
    planets = host_loop._aggregate_planets(list(sets.values()), view=xi4)
    radii = {e["radius"] for e in planets}
    assert bodies["XiEntrades4"].GetRadius() in radii
    assert bodies["Ona1"].GetRadius() not in radii

    # -- torpedoes and their lights.
    torps = {name: _viewed_torpedo(pSet, name + "Torp")
            for name, pSet in sets.items()}
    torp_out = host_loop._build_torpedo_render_data()
    ids_present = {e["id"] for e in torp_out}
    assert int(torps["XiEntrades4"]._id) in ids_present
    for name in ("Ona1", "Ona2", "Ona3", "Starbase12"):
        assert int(torps[name]._id) not in ids_present

    light_out = host_loop._build_dynamic_light_render_data()
    assert len(light_out) == len(ids_present)   # one light per visible torpedo

    # -- explosion lights.
    for name, pSet in sets.items():
        explosion_lights.register(sentinels[name], size_gu=10.0, count=1,
                                  spacing_s=1.0, life_s=100.0)
    explosion_lights.advance(1.0 / 60.0)
    exp_out = host_loop._build_explosion_light_render_data()
    assert len(exp_out) == 1, "an explosion light from Ona/Starbase12 leaked in"

    # -- lens flares.
    require_game_asset("data/textures/rays.tga")
    suns = {}
    for i, (name, pSet) in enumerate(sets.items()):
        sun = Sun(radius=100.0 + i, model_path="data/Textures/SunBase.tga")
        sun.SetWorldLocation(ARRIVAL)
        pSet.AddObjectToSet(sun, name + "Sun")
        flare = LensFlare_Create(pSet)
        flare.SetSource(sun, 6)
        flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
        flare.Build()
        suns[name] = sun
    flare_out = aggregate_lens_flares_for_renderer(
        bc_assets.GAME_ROOT, list(sets.values()), view=xi4)
    flare_radii = {e["source_radius"] for e in flare_out}
    assert suns["XiEntrades4"].GetRadius() in flare_radii
    for name in ("Ona1", "Ona2", "Ona3", "Starbase12"):
        assert suns[name].GetRadius() not in flare_radii


# ── (f) audio: registers under the emitter's frame, stopped off-frame ───────

_dauntless_host = pytest.importorskip("_dauntless_host")


def test_positional_sound_registers_under_ona_and_stops_off_frame(world):
    import os
    import struct
    os.environ.setdefault("OPEN_STBC_AUDIO", "0")
    from engine.audio import scene_scope
    from engine.audio.tg_sound import (
        TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
    )

    sets, sentinels, bodies = world
    scene_scope.reset_for_tests()
    init_audio_for_tests()
    try:
        def _wav():
            data = struct.pack("<h", 0) * 8
            return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
                    + b"fmt " + struct.pack("<I", 16)
                    + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
                    + b"data" + struct.pack("<I", len(data)) + data)

        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wav_path = f"{d}/x.wav"
            with open(wav_path, "wb") as f:
                f.write(_wav())
            TGSoundManager.instance().LoadSound(wav_path, "SpaceSfx", TGSound.LS_3D)
            snd = TGSoundManager.instance().GetSound("SpaceSfx")
            snd.SetLooping(True)
            handle = snd.Play(attach_node=sentinels["Ona1"].GetNode())
            assert handle is not None and handle._pid

            ona_key = frames.frame_of(sets["Ona1"]).key
            assert scene_scope._by_frame[ona_key] == [handle]

            scene_scope.set_active_frame(frames.frame_of(sets["XiEntrades4"]).key)
            assert not handle._pid, (
                "a sound registered under Ona was not stopped by an "
                "XiEntrades4 scene change")
    finally:
        shutdown_audio_for_tests()
        scene_scope.reset_for_tests()


# ── Review Focus 1: a setless object interacts with nothing anywhere ────────

def test_a_setless_object_interacts_with_nothing_anywhere(world):
    sets, sentinels, bodies = world
    loose = ShipClass()
    loose.SetName("Loose")
    loose.SetTranslateXYZ(*ARRIVAL)
    loose.SetRadius(1.0)
    loose.SetMass(1000.0)
    loose.SetVelocity(TGPoint3(-1.0, 0.7, 0.0))
    assert loose.GetContainingSet() is None

    collidables = list(collisions.iter_collidables()) + [loose]
    hits = collisions.resolve_collisions(collidables)
    for a_obj, b_obj, _c, _v in hits:
        assert a_obj is not loose and b_obj is not loose

    all_ships = list(sentinels.values()) + [loose]
    src = ShipClass()
    src.SetName("TorpSrc2")
    src.SetTranslateXYZ(*ARRIVAL)
    sets["Ona1"].AddObjectToSet(src, "TorpSrc2")
    t = Torpedo()
    t.SetTranslateXYZ(*ARRIVAL)
    t._velocity = TGPoint3(0.0, 0.0, 0.0)
    t._ttl = 30.0
    t._source_ship = src
    t._damage = 100.0
    register(t)
    torp_hits = projectiles.update_all(1.0, all_ships)
    for _torp, hit_ship, _pt, _n in torp_hits:
        assert hit_ship is not loose

    eligible = damage_eligibility.select_eligible(loose, all_ships)   # must not raise
    assert isinstance(eligible, frozenset)
