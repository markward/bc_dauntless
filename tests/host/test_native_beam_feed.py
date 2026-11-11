"""Native per-frame beam descriptor feed (phase 6 follow-ups 1 and 4).

`_h.phaser_beams_debug()` / `tractor_beams_debug()` read back what the feed
pushed, so it is compared bit for bit against the render goldens recorded
from the Python builders before they were deleted (tests/helpers/
render_golden.py). There is no Python copy of the feed any more.
"""
import pytest

from tests.helpers.native_render_feeds import (
    BEAM_FIELDS, BEAM_ROW_LEN, beam_bytes, beam_dict, beam_dict_values,
    drop_from_frames, f32, pack)

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "set_phaser_beams"),
    reason="native host not built")


FULL = {
    "emitter": (1.1, 2.2, 3.3), "target": (4.4, 5.5, 6.6),
    "color": (0.1, 0.2, 0.3, 0.4), "width": 0.7, "u_tiles": 3.3,
    "num_sides": 12, "taper_radius": 0.02, "taper_ratio": 0.3,
    "taper_min_length": 4.4, "taper_max_length": 31.1,
    "perimeter_tile": 2.2, "texture_speed": 1.7, "end_width_scale": 1.25,
}
MINIMAL = {
    "emitter": (0.5, 0.25, 0.125), "target": (7.7, 8.8, 9.9),
    "color": (1.0, 0.9, 0.8, 0.7), "width": 0.3,
}


def packed(d):
    """The descriptor `d` as the native side must hold it: defaults applied,
    float32-rounded, packed bytes (so -0.0 / NaN cannot hide in a float ==)."""
    return pack(BEAM_FIELDS, beam_dict_values(d))


def test_readback_returns_what_set_phaser_beams_pushed():
    _h.set_phaser_beams([FULL, MINIMAL])
    _h.set_tractor_beams([MINIMAL, FULL])
    try:
        assert _beams("phaser") == [packed(FULL), packed(MINIMAL)]
        assert _beams("tractor") == [packed(MINIMAL), packed(FULL)]
        # No end_width_scale given: the native default is 1.0.
        assert beam_dict(_h.phaser_beams_debug()[1])["end_width_scale"] == 1.0
        assert len(_h.phaser_beams_debug()[0]) == BEAM_ROW_LEN == 20
    finally:
        _h.set_phaser_beams([])
        _h.set_tractor_beams([])


# ── The scene: real instances, phasers firing, a tractor towing ─────────────

from tests.host.test_native_k2_differential import (  # noqa: E402,F401
    ON, TICKS, _Scene, _hermetic, host)

def _beams(kind):
    """The pushed descriptors of `kind` ('phaser' | 'tractor') as packed
    bytes, one per beam, so a compare is bitwise."""
    rows = getattr(_h, kind + "_beams_debug")()
    return [beam_bytes(r) for r in rows]


class BeamScene:
    """combat_stress on the real host (native combat on), every ship realised.
    `ships`, `ship_instances`, `scene` (the K2 _Scene) and `advance()`."""

    def __init__(self, scene):
        self.scene = scene
        self.ships = scene.ships
        self.ship_instances = scene.session.ship_instances
        self.player = scene.player

    def advance(self, ticks=1):
        """One frame of `ticks` sim ticks, as the K2 differential runs one:
        render sync, subsystem update, weapons + combat per tick."""
        import App
        from engine.appc.ship_iter import iter_ships
        from engine.core import loop as game_loop
        from engine.core.loop import TICK_DELTA
        from engine import host_loop
        sc = self.scene
        sc.sync_render()
        for _ in range(ticks):
            App.g_kTimerManager._time += TICK_DELTA
            game_loop._update_ship_subsystems()
        for _ in range(ticks):
            sc.tick += 1
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(
                    ships, TICK_DELTA, ship_instances=self.ship_instances,
                    player=self.player, push_render_data=False)
            host_loop._combat_tick_boundary()

    def _open_fire(self):
        sc = self.scene
        # Sensors power up at 1.0 s of game time.
        self.advance(ticks=70)
        # Spread targets so both shield states, hull traces and bubble
        # entries are all exercised.
        for i, g in enumerate(sc.systems):
            g.TurnOn()
            g.SetSingleFire(0)
            foes = sc._foes(g.GetParentShip())
            g.StartFiring(foes[i % len(foes)] if foes else None)
        # Shields: one foe up, one down.
        foes = sc._foes(self.player)
        for i, s in enumerate(foes):
            sh = s.GetShieldSubsystem()
            if sh is not None:
                (sh.TurnOn if i % 2 == 0 else sh.TurnOff)()
        # One tractor tows.
        for s in sc.ships:
            tb = s.GetTractorBeamSystem()
            foes = sc._foes(s)
            if tb is not None and foes:
                tb.TurnOn()
                tb.StartFiring(foes[0], None)
                break


@pytest.fixture
def beam_scene(monkeypatch, host):
    scene = _Scene(monkeypatch, host, ON)
    try:
        bs = BeamScene(scene)
        bs._open_fire()
        for _ in range(30):
            bs.advance()
        yield bs
    finally:
        scene.close()


def _foe_shield_states(scene):
    return {s.GetName(): bool(s.GetShieldSubsystem().IsOn())
            for s in scene._foes(scene.player)
            if s.GetShieldSubsystem() is not None}


def _firing(system):
    """The banks of `system` that are firing, in bank order."""
    return [b for b in system._children if b.__dict__.get("_firing")]


def _phaser_targets_by_shield(bs):
    """{shields_up: count of ships' firing banks aimed at such a target}
    over ships whose native feed draws phasers."""
    seen = {True: 0, False: 0}
    for ship in bs.ships:
        ok, phasers, _tractors = _native_feed([ship], bs.ship_instances)
        if not (ok and phasers):
            continue
        for bank in _firing(ship.GetPhaserSystem()):
            sh = getattr(bank._target, "GetShieldSubsystem",
                         lambda: None)()
            if sh is not None:
                seen[bool(sh.IsOn())] += 1
    return seen


def test_scene_feeds_phaser_and_tractor_pairs(beam_scene):
    before = _foe_shield_states(beam_scene.scene)
    got, seen = None, {True: 0, False: 0}
    for _ in range(60):
        beam_scene.advance()
        ok, *got = _native_feed(beam_scene.ships, beam_scene.ship_instances)
        assert ok
        seen = _phaser_targets_by_shield(beam_scene)
        if got[0] and got[1] and all(seen.values()):
            break
    phasers, tractors = got
    # Every firing bank emits an outer shell + inner core pair.
    assert len(phasers) > 0 and len(phasers) % 2 == 0
    assert len(tractors) > 0 and len(tractors) % 2 == 0
    after = _foe_shield_states(beam_scene.scene)
    assert set(before.values()) == {True, False}, before
    assert set(after.values()) == {True, False}, after
    assert seen[True] > 0 and seen[False] > 0, (
        "phasers must land on a shields-up and a shields-down foe: %r" % seen)


# ── The native feed ─────────────────────────────────────────────────────────

import random  # noqa: E402

from engine.appc import native_combat as nc  # noqa: E402


def _native_feed(ships, ship_instances):
    """native_combat.beam_feed, then what it pushed: (ok, phaser bytes,
    tractor bytes). Both vectors are seeded with a sentinel first, so a
    binding that skipped an assignment reads back the sentinel, never the
    frame pushed before it; the binding's own (n_phasers, n_tractors) must
    equal what it pushed."""
    _h.set_phaser_beams([SENTINEL])
    _h.set_tractor_beams([SENTINEL, SENTINEL])
    returned = []
    feed = _h.combat_beam_feed

    def spy(*a, **k):
        r = feed(*a, **k)
        returned.append(r)
        return r

    _h.combat_beam_feed = spy
    try:
        ok = nc.beam_feed(ships, ship_instances)
    finally:
        _h.combat_beam_feed = feed
    phasers, tractors = _beams("phaser"), _beams("tractor")
    if ok:
        # (n_phasers, n_tractors, {skip reason: count}).
        assert [r[:2] for r in returned] == [
            (len(phasers), len(tractors))], returned
    return ok, phasers, tractors


# Matches no descriptor the feed makes (a width of -1, 3 sides).
SENTINEL = dict(MINIMAL, width=-1.0, num_sides=3)


MANUAL_SEED = 20261106


def _manual_aim_beat(scene, k, rng):
    """Manual Aim on, moved, off: a scripted beat on top of the op stream,
    `k` ticks into the run."""
    if k in (20, 160):
        scene.op(rng, "manual_on")
    elif k % 7 == 0 and k < 240:
        scene.op(rng, "manual_move")
    elif k == 250:
        scene.op(rng, "manual_off")


from tests.host.test_render_space_feeds import far_scene  # noqa: E402,F401
from tests.helpers.native_on import native_combat_on  # noqa: E402,F401


@pytest.fixture
def regions():
    """A clean set manager, game and render origin around a test that builds
    its own sets (test_render_space_feeds' _isolate, which is autouse there
    and so is not imported here)."""
    import App
    from engine import host_loop
    from engine.core.game import _set_current_game
    from engine.systems import frames

    def clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        _set_current_game(None)
        host_loop._note_camera_eye(None)
        frames.reset_render_origin()

    clear()
    try:
        yield clear
    finally:
        clear()


def _tow(shooter_set, sname, sxyz, target_set, tname, txyz):
    """A tractor lit from `shooter_set` at a target that then moves to
    `target_set` (test_render_feeds_by_frame's _tractor_pair, named)."""
    from unittest.mock import patch
    from tests.unit.test_tractor_beam_render_data import (
        _ship_with_tractor, _target)
    ship, parent = _ship_with_tractor()
    target = _target()
    shooter_set.AddObjectToSet(ship, sname)
    shooter_set.AddObjectToSet(target, tname)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, None)
    assert parent.IsFiring()
    if target_set is not shooter_set:
        shooter_set.RemoveObjectFromSet(tname)
        target_set.AddObjectToSet(target, tname)
    ship.SetTranslateXYZ(*sxyz)
    target.SetTranslateXYZ(*txyz)
    return ship, target


def _regions_ships(far_scene):
    """The across-regions scene: far_scene's player 450,000 GU out in an
    unmapped set, viewed from Ona1 at a non-zero render origin, and three
    tows (Ona1 -> Ona2, Ona2 -> Ona1, Ona1 -> the far set). The ships."""
    import App
    from engine.systems import frames
    from tests.helpers.mapped_regions import load_region
    far, player = far_scene
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    assert frames.viewing_set() is ona1
    off = frames.offset_between(ona1, ona2)
    assert off is not None and off != (0.0, 0.0, 0.0)
    assert frames.offset_between(ona1, far) is None
    frames.set_render_origin((12.5, -30.25, 4.0))
    a, _ = _tow(ona1, "A", (0.0, 0.0, 0.0), ona2, "At", (0.0, 50.0, 0.0))
    b, _ = _tow(ona2, "B", (3.0, 1.0, 0.0), ona1, "Bt", (1.0, 40.0, 2.0))
    c, _ = _tow(ona1, "C", (5.0, 0.0, 0.0), far, "Ct", (0.0, 50.0, 0.0))
    return [player, a, b, c]


def test_a_skipped_ship_drops_only_its_own_beams(beam_scene, monkeypatch):
    import App
    from engine import host_loop
    from engine.appc.sets import SetClass_Create
    bs = beam_scene
    # A firing ship moved to a set of its own frame: none of its beams is
    # drawn, nor any beam at it; the native feed must look that set's frame
    # up -- and it is left out of the frames table, so the feed skips
    # exactly those items (counted "frames") and draws every other: the
    # frame it draws with the set in the table.
    # The LAST firing shooter, so ships before it in list order have drawn
    # pairs into the native build when it is skipped.
    shooter = [s for s in bs.ships if s is not bs.player
               and s.GetPhaserSystem() is not None
               and _firing(s.GetPhaserSystem())][-1]
    before = bs.ships[:bs.ships.index(shooter)]
    elsewhere = SetClass_Create()
    App.g_kSetManager.AddSet(elsewhere, "Elsewhere")
    name = shooter.GetName()
    shooter.GetContainingSet().RemoveObjectFromSet(name)
    elsewhere.AddObjectToSet(shooter, name)
    ships = [s for s in bs.ships if s.GetContainingSet() is not None]
    ok, *drawn = _native_feed([s for s in before if s in ships],
                              bs.ship_instances)
    assert ok and drawn[0], "premise: a ship before the shooter draws phasers"
    nc.reset_beam_feed_counts()
    ok, *want = _native_feed(ships, bs.ship_instances)
    assert ok and want[0], "premise: other ships' phasers still draw"
    assert not any(nc.beam_feed_counts()["skips"].values())
    want = tuple(want)
    drop_from_frames(monkeypatch, elsewhere)
    nc.reset_beam_feed_counts()
    try:
        ok, phasers, tractors = _native_feed(ships, bs.ship_instances)
        assert ok
        assert (phasers, tractors) == want
        skips = nc.beam_feed_counts()["skips"]
        assert skips["frames"] >= 1, skips
        assert sum(skips.values()) == skips["frames"], skips
        # host_loop's frame is the native feed's.
        _h.set_phaser_beams([FULL])
        _h.set_tractor_beams([MINIMAL, FULL])
        host_loop._push_combat_render_data(
            ships, ship_instances=bs.ship_instances, player=bs.player)
        assert (_beams("phaser"), _beams("tractor")) == want
        assert nc.beam_feed_counts()["native"] == 2
    finally:
        _h.set_phaser_beams([])
        _h.set_tractor_beams([])


def test_a_patched_getter_is_not_honoured(beam_scene, monkeypatch):
    """Spec Part A: the feed reads the mirror, so a getter patched on the
    class draws exactly what the unpatched frame drew."""
    from engine.appc import weapon_subsystems as ws
    bs = beam_scene
    ok, *want = _native_feed(bs.ships, bs.ship_instances)
    assert ok and want[0], "premise: phasers draw"
    outer = [beam_dict(r)["width"] for r in _h.phaser_beams_debug()[0::2]]
    assert outer and all(w != f32(9.0 * 3.0) for w in outer), \
        "premise: no mirrored width is the patch's"
    monkeypatch.setattr(ws.PhaserBank, "GetPhaserWidth", lambda self: 9.0)
    bank = _firing(next(s for s in bs.ships if s.GetPhaserSystem() is not None
                        and _firing(s.GetPhaserSystem())).GetPhaserSystem())[0]
    assert bank.GetPhaserWidth() == 9.0, "premise: the patch is live"
    ok, phasers, tractors = _native_feed(bs.ships, bs.ship_instances)
    assert ok
    assert not any(nc.beam_feed_counts()["skips"].values())
    # The mirrored widths, not the patched getter's.
    assert [phasers, tractors] == want


# ── Counters: did the native feed run every frame? ──────────────────────────

def test_the_feed_counts_native_frames_and_skips(beam_scene, monkeypatch):
    import types
    from engine.core.tracked_instances import TrackedInstances
    bs = beam_scene
    zero = dict.fromkeys(nc._BEAM_SKIPS, 0)
    assert nc.beam_feed_counts() == {"native": 0, "skips": zero}
    assert type(bs.ship_instances) is TrackedInstances
    ok, *want = _native_feed(bs.ships, bs.ship_instances)
    assert ok is True
    assert want[0], "premise: phasers draw"
    want = tuple(want)
    # A ship with no row: skipped in each walk, every other pair drawn. As
    # a blocker candidate it needs Python, so every drawn phaser pair keeps
    # its target's end, counted "blocker" (beam_feed.h, BeamSkip): the pairs
    # are those of the call before, which had no row-less candidate -- so
    # this frame equals it only while nothing blocked there either.
    ok, phasers, tractors = _native_feed(
        bs.ships + [types.SimpleNamespace()], bs.ship_instances)
    assert ok and (phasers, tractors) == want
    pairs = len(want[0]) // 2
    # A plain dict, not the session's TrackedInstances: native, the same.
    ok, phasers, tractors = _native_feed(
        bs.ships, dict(bs.ship_instances.items()))
    assert ok and (phasers, tractors) == want
    # ... and back to the TrackedInstances: its table is sent again.
    ok, phasers, tractors = _native_feed(bs.ships, bs.ship_instances)
    assert ok and (phasers, tractors) == want
    # The switch off: native too.
    monkeypatch.setattr(nc, "_switch", False)
    ok, phasers, tractors = _native_feed(bs.ships, bs.ship_instances)
    assert ok and (phasers, tractors) == want
    assert nc.beam_feed_counts() == {
        "native": 5, "skips": dict(zero, ship_row=2, blocker=pairs)}
    nc.reset()
    assert nc.beam_feed_counts() == {"native": 0, "skips": zero}


# ── Render goldens (phase 6 follow-up 4) ────────────────────────────────────
#
# Recorded from the Python builders before they were deleted (Task 1), so
# each golden is what Python drew for the scene; the native feed's frames are
# checked against it bit for bit. UPDATE_RENDER_GOLDEN=1 fails (the builders
# are gone); UPDATE_RENDER_GOLDEN=native re-records from the native feed, and
# only on Mark's recorded ruling (tests/helpers/render_golden.py).

from tests.helpers import render_golden  # noqa: E402


def golden_beam_frame(ships, ship_instances):
    """This frame's beams, from the native feed, as a render_golden frame
    (a feed that pushed nothing leaves its sentinels, so the frame differs
    from the golden)."""
    _ok, phasers, tractors = _native_feed(ships, ship_instances)
    return render_golden.frame(phasers=phasers, tractors=tractors,
                               source="native")


def _record_or_check(scene_name, frames):
    """Check `frames` against the golden. While UPDATE_RENDER_GOLDEN
    records, render_golden.record runs first: "1" refuses, "native" (Mark's
    recorded ruling only) writes the golden and skips."""
    if render_golden.recording():
        render_golden.record(scene_name, frames)
    render_golden.check(scene_name, frames)


def test_beam_scene_matches_the_golden(beam_scene):
    """300 frames: the K2 differential's seeded op stream, its posed beat and
    the Manual Aim beat. The recording (Task 1) had pairs ending on the
    shield bubble and on the hull mesh trace, tractor pairs, Manual Aim pairs
    and a lock on the posed ship in it; the scene side of that is asserted
    here (a bank firing at a target whose shields block, which ends on the
    bubble, and at one whose shields do not, which ends on the hull trace),
    the endpoints by the golden. These premises run while re-recording too,
    so a re-record cannot quietly lose a case."""
    from engine.appc import combat
    from engine.appc.ship_iter import iter_ships
    from tests.host.test_native_k2_differential import (
        OPS, POSE_FROM, POSE_TO, POSED)
    bs = beam_scene
    sc = bs.scene
    start = sc.tick
    assert start < POSE_FROM, start
    manual = random.Random(MANUAL_SEED)
    frames = []
    seen = {"manual_aim": 0, "posed_lock": 0, "shields_up_hit": 0,
            "shields_down_hit": 0}
    nc.reset_beam_feed_counts()

    def frame(scene):
        _manual_aim_beat(scene, scene.tick - start, manual)
        ships = list(iter_ships())
        for ship in ships:
            sys_ = ship.GetPhaserSystem()
            if sys_ is None or not _firing(sys_):
                continue
            if ship.is_using_target_offset():
                seen["manual_aim"] += 1
            for bank in _firing(sys_):
                if bank._target is not None and \
                        bank._target in bs.ship_instances:
                    seen["shields_up_hit" if combat.shields_block(bank._target)
                         else "shields_down_hit"] += 1
            lock = ship.__dict__.get("_target_subsystem")
            if (POSE_FROM <= scene.tick < POSE_TO and lock is not None
                    and lock.GetParentShip() is scene.ship(POSED)):
                seen["posed_lock"] += 1
        frames.append(golden_beam_frame(ships, bs.ship_instances))

    sc.run(OPS, 1, ticks=start + 300, before_tick=frame)
    assert len(frames) == 300
    assert sum(len(f["phasers"]) for f in frames) > 0
    assert sum(1 for f in frames if f["tractors"]) > 0
    assert all(seen.values()), seen
    assert nc.beam_feed_counts()["native"] == 300
    assert not any(nc.beam_feed_counts()["skips"].values())
    _record_or_check("beam_scene", frames)


def _python_drawn_ends(ships, ship_instances):
    """Each firing phaser bank's end as the damage step's Python reference
    picks its contact (host_loop._phaser_step_bank, beam_blockers): the
    target's bubble entry or hull point, unless beam_blockers.first_blocker
    finds something nearer -- then its bubble entry, else its point. In the
    feed's order (ship, firing bank), RENDER space; and how many were
    blocked, by tier. Every ship in one set (the scene's premise)."""
    from engine import host_loop
    from engine.appc import beam_blockers, combat
    from engine.appc.math import TGPoint3
    from engine.systems import frames
    view = frames.viewing_set()
    ends, tiers = [], {}
    for ship in ships:
        sys_ = ship.GetPhaserSystem()
        if sys_ is None:
            continue
        for bank in _firing(sys_):
            target = bank._target
            if target is None:
                continue
            assert frames.containing_set(target) is \
                frames.containing_set(ship), "premise: one set"
            target_pos, _sub = host_loop._phaser_aim_point(ship, target)
            emitter = bank._strip_emit_position(target_pos)
            dx = target_pos.x - emitter.x
            dy = target_pos.y - emitter.y
            dz = target_pos.z - emitter.z
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            assert dist > 1e-6
            aim = TGPoint3(dx / dist, dy / dist, dz / dist)
            impact, _n = combat._resolve_hit_point(
                ship_instances=ship_instances, ship=target,
                ray_origin=emitter, ray_direction=aim, max_dist=dist * 1.5,
                fallback_point=target_pos)
            bubble = (combat.shield_bubble_entry(target, emitter, aim,
                                                 dist * 1.5)
                      if combat.shields_block(target) else None)
            b = beam_blockers.first_blocker(
                ship, target, emitter, aim,
                beam_blockers.contact_distance(emitter, impact, bubble),
                ships, {}, ship_instances)
            if b is None:
                end = bubble if bubble is not None else impact
            else:
                end = b.bubble if b.bubble is not None else b.point
                tiers[b.tier] = tiers.get(b.tier, 0) + 1
            ends.append(frames.to_render(view, frames.containing_set(target),
                                         end.x, end.y, end.z))
    return ends, tiers


def test_drawn_phaser_ends_where_the_damage_step_lands(beam_scene):
    """Spec 2026-11-11-beam-blocking §7 case 11, on REAL hull meshes: every
    frame of the golden scene, each drawn phaser pair (outer and inner) ends
    where the Python reference puts the damage contact, the blocker's when
    a ship is in the way."""
    from engine.appc.ship_iter import iter_ships
    from tests.host.test_native_k2_differential import OPS
    bs = beam_scene
    sc = bs.scene
    start = sc.tick
    manual = random.Random(MANUAL_SEED)
    blocked = {}
    checked = [0]

    def frame(scene):
        _manual_aim_beat(scene, scene.tick - start, manual)
        ships = list(iter_ships())
        ends, tiers = _python_drawn_ends(ships, bs.ship_instances)
        assert nc.beam_feed(ships, bs.ship_instances) is True
        drawn = [beam_dict(r) for r in _h.phaser_beams_debug()]
        assert len(drawn) == 2 * len(ends)
        for i, want in enumerate(ends):
            for d in drawn[2 * i:2 * i + 2]:
                assert d["target"] == pytest.approx(
                    tuple(f32(c) for c in want), abs=1e-6), (
                    scene.tick, i, d["target"], want)
        checked[0] += len(ends)
        for k, n in tiers.items():
            blocked[k] = blocked.get(k, 0) + n

    nc.reset_beam_feed_counts()
    sc.run(OPS, 1, ticks=start + 300, before_tick=frame)
    assert checked[0] > 0
    # Seeded: blockers met at a shield bubble AND on a real hull mesh.
    assert blocked.get("mesh", 0) > 0 and blocked.get("bubble", 0) > 0, \
        blocked
    assert not any(nc.beam_feed_counts()["skips"].values())


def test_beam_regions_match_the_golden(native_combat_on, regions, far_scene):
    """far_scene's player 450,000 GU out in an unmapped set (another frame),
    viewed instead from Ona1 at a non-zero render origin: one tow split from
    Ona1 to Ona2, one from Ona2 back to Ona1, one into the far set. The two
    pairs in the viewed frame draw; the one in another frame does not.
    (native_combat_on: the K2 differential's autouse _hermetic, imported
    here, resets the switch off.)"""
    ships = _regions_ships(far_scene)
    nc.reset_beam_feed_counts()
    frames = [golden_beam_frame(ships, None)]
    assert len(frames[0]["tractors"]) == 4
    assert not any(nc.beam_feed_counts()["skips"].values())
    _record_or_check("beam_regions", frames)
