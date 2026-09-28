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


def test_collisions_inside_one_system_compare_by_system_position(world):
    """The guard above cannot see a raw compare INSIDE one system: frames
    that differ still never pair, but Ona1 and Ona2 share the "Ona" frame, so
    a consumer that dropped the region anchors (a zero offset between any two
    sets of one frame) would still pass it. This pins both halves.

    Negative: the Ona1 and Ona2 sentinels sit at the SAME local numbers and
    must NOT collide: their regions' anchors put them far apart in the
    system. The Ona2 one is nudged 1 GU along x (still overlapping by raw
    numbers: two radius-1 hulls) and made to close on s1, because at exactly
    identical numbers _respond_pair's concentric skip (degenerate normal)
    would hide a raw compare -- a zero-offset mutation passed this test until
    the nudge. Positive control: two ships at the same SYSTEM position
    (Ona2's placed at Ona1's point shifted by the anchor offset) DO."""
    sets, sentinels, bodies = world
    ona1, ona2 = sets["Ona1"], sets["Ona2"]
    s1, s2 = sentinels["Ona1"], sentinels["Ona2"]
    s2.SetTranslateXYZ(ARRIVAL[0] + 1.0, ARRIVAL[1], ARRIVAL[2])
    s2.SetVelocity(TGPoint3(-3.0, 0.7, 0.0))       # closing on s1's numbers

    off = frames.offset_between(ona1, ona2)         # Ona2-local -> Ona1-local
    assert off != (0.0, 0.0, 0.0)
    far = (ARRIVAL[0] + 40000.0, ARRIVAL[1], ARRIVAL[2])   # clear of both sentinels
    a = ShipClass()
    a.SetName("SysA")
    a.SetTranslateXYZ(*far)
    a.SetRadius(50.0)
    a.SetMass(1000.0)
    a.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    ona1.AddObjectToSet(a, "SysA")
    b = ShipClass()
    b.SetName("SysB")
    b.SetTranslateXYZ(far[0] - off[0] + 60.0, far[1] - off[1], far[2] - off[2])
    b.SetRadius(50.0)
    b.SetMass(1000.0)
    b.SetVelocity(TGPoint3(-1.0, 0.0, 0.0))
    ona2.AddObjectToSet(b, "SysB")

    hits = collisions.resolve_collisions([s1, s2, a, b])
    pairs = [{id(x), id(y)} for x, y, _c, _v in hits]
    assert {id(a), id(b)} in pairs, (
        "two ships at the same SYSTEM position in Ona1/Ona2 did not collide")
    assert {id(s1), id(s2)} not in pairs, (
        "Ona1/Ona2 sentinels at the same LOCAL numbers collided -- a raw "
        "compare inside one system")


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

def test_torpedo_hits_only_its_own_frame(world):
    """Two torpedoes, one call: a POSITIVE control (aimed at a dedicated Ona1
    victim, well clear of the shared ARRIVAL numbers) that MUST hit, proving
    update_all is actually landing hits in this scenario -- `hits == []`
    from a torpedo that hits nothing would otherwise pass just as well if
    update_all had stopped detecting hits at all. And a torpedo landing
    exactly on the shared ARRIVAL point, which every OTHER set's sentinel
    also sits at (in ITS OWN frame) -- named `ships_that_must_not_be_hit`
    because Ona2/Ona3 are NOT "other frames" (they share the "Ona" system
    frame with Ona1, just at a real anchor offset -- only XiEntrades4 and
    Starbase12 are genuinely different frames).

    No Ona1 ship sits at the shared ARRIVAL point for the negative
    torpedo to reach: a torpedo hits at most one ship per tick (it stops at
    the first match in ship_cache order), so a legitimate same-frame hit at
    that exact point would mask whether a cross-region/cross-frame one would
    ALSO have matched -- the positive control below uses its OWN, separate
    victim and point specifically so it cannot mask this check."""
    sets, sentinels, bodies = world
    src = ShipClass()
    src.SetName("TorpSrc")
    src.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    sets["Ona1"].AddObjectToSet(src, "TorpSrc")

    # Positive control: a dedicated Ona1 victim far from the shared ARRIVAL
    # numbers, so it cannot be confused with any of the sentinels below.
    victim = ShipClass()
    victim.SetName("OnaTorpVictim")
    victim.SetTranslateXYZ(ARRIVAL[0] + 20.0, ARRIVAL[1] - 6.0, ARRIVAL[2])
    victim.SetRadius(1.0)
    sets["Ona1"].AddObjectToSet(victim, "OnaTorpVictim")
    torp_positive = Torpedo()
    torp_positive.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    torp_positive._velocity = TGPoint3(20.0, 0.0, 0.0)   # lands exactly on victim
    torp_positive._ttl = 30.0
    torp_positive._source_ship = src
    torp_positive._damage = 100.0
    register(torp_positive)

    # Negative check: lands exactly on the shared ARRIVAL point this tick.
    torp_negative = Torpedo()
    torp_negative.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    torp_negative._velocity = TGPoint3(0.0, 6.0, 0.0)
    torp_negative._ttl = 30.0
    torp_negative._source_ship = src
    torp_negative._damage = 100.0
    register(torp_negative)
    assert torp_negative.GetContainingSet() is sets["Ona1"]

    ships_that_must_not_be_hit = [sentinels[name] for name in
                                  ("Ona2", "Ona3", "XiEntrades4", "Starbase12")]
    hits = projectiles.update_all(1.0, [victim] + ships_that_must_not_be_hit)
    hit_by_torpedo = {id(torp): ship for torp, ship, _pt, _n in hits}
    assert hit_by_torpedo.get(id(torp_positive)) is victim, (
        "the same-frame positive control never hit -- update_all landed no "
        "hits at all here, which would make the negative result below vacuous")
    assert id(torp_negative) not in hit_by_torpedo, (
        "a torpedo in Ona1 hit a ship outside its own frame")


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

def test_positional_sound_registers_under_ona_and_stops_off_frame(world):
    pytest.importorskip("_dauntless_host")
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

def test_a_setless_object_is_not_struck_by_a_torpedo_that_would_hit_it(world):
    """The moving-torpedo setup from test (c): a torpedo landing exactly on
    `loose`'s position, from a real in-frame source, WOULD hit it if a
    setless object had any frame at all -- a stationary torpedo (zero
    velocity) proves nothing, since it cannot hit anything regardless of
    frames (confirmed: it also misses a real same-frame target)."""
    sets, sentinels, bodies = world
    loose = ShipClass()
    loose.SetName("Loose")
    loose.SetTranslateXYZ(*ARRIVAL)
    loose.SetRadius(1.0)
    assert loose.GetContainingSet() is None

    src = ShipClass()
    src.SetName("TorpSrc2")
    src.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    sets["Ona1"].AddObjectToSet(src, "TorpSrc2")
    t = Torpedo()
    t.SetTranslateXYZ(ARRIVAL[0], ARRIVAL[1] - 6.0, ARRIVAL[2])
    t._velocity = TGPoint3(0.0, 6.0, 0.0)       # lands exactly on loose's position
    t._ttl = 30.0
    t._source_ship = src
    t._damage = 100.0
    register(t)

    torp_hits = projectiles.update_all(1.0, [loose])
    assert torp_hits == [], "a torpedo struck a setless object"


def test_a_setless_object_does_not_interact_in_collisions_or_eligibility(world):
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

    # Discriminating: `loose` sits at the exact same numbers as the
    # XiEntrades4 player, so a bug that gave it a real (zero) offset to
    # every frame would make it read as the CLOSEST possible ship -- the
    # maximum proximity score -- and outrank a same-frame wingman of equal
    # size that is genuinely 50 GU away. `isinstance(eligible, frozenset)`
    # alone (the previous version of this test) cannot tell the difference;
    # this checks the CONTENT.
    player = sentinels["XiEntrades4"]
    wingman = ShipClass()
    wingman.SetName("Wingman2")
    wingman.SetTranslateXYZ(ARRIVAL[0] + 50.0, ARRIVAL[1], ARRIVAL[2])
    wingman.SetRadius(1.0)
    sets["XiEntrades4"].AddObjectToSet(wingman, "Wingman2")

    eligible = damage_eligibility.select_eligible(
        player, [player, wingman, loose], max_count=2)
    assert id(wingman) in eligible, "a same-frame ship of equal size lost out"
    assert id(loose) not in eligible, (
        "a setless ship outranked a same-frame ship of equal size")
