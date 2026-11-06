"""Native per-frame beam descriptor feed (phase 6 follow-up 1): the oracle.

Task 1: `_h.phaser_beams_debug()` / `tractor_beams_debug()` read back what
`set_phaser_beams` / `set_tractor_beams` pushed, so a later native feed can be
compared bit for bit against today's Python builders.
"""
import struct

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "set_phaser_beams"),
    reason="native host not built")


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


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
    return struct.pack(
        PACK, *d["emitter"], *d["target"], *d["color"], d["width"],
        d.get("u_tiles", 1.0), d.get("num_sides", 6),
        d.get("taper_radius", 0.01), d.get("taper_ratio", 0.25),
        d.get("taper_min_length", 5.0), d.get("taper_max_length", 30.0),
        d.get("perimeter_tile", 1.0), d.get("texture_speed", 0.0),
        d.get("end_width_scale", 1.0))


PACK = "<12f i 7f"


def test_readback_returns_what_set_phaser_beams_pushed():
    _h.set_phaser_beams([FULL, MINIMAL])
    _h.set_tractor_beams([MINIMAL, FULL])
    try:
        assert _beams("phaser") == [packed(FULL), packed(MINIMAL)]
        assert _beams("tractor") == [packed(MINIMAL), packed(FULL)]
        # No end_width_scale given: the native default is 1.0.
        assert struct.unpack(PACK, _beams("phaser")[1])[-1] == 1.0
        assert len(_h.phaser_beams_debug()[0]) == 20
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
    return [struct.pack(PACK, *r) for r in rows]


def _python_feed(ships, ship_instances):
    """Today's Python builders for both beam kinds (sharing one _ViewMemo),
    pushed through host_io; returns (_beams('phaser'), _beams('tractor'))."""
    from engine import host_io, host_loop
    memo = host_loop._ViewMemo()
    host_io.set_phaser_beams(host_loop._build_phaser_beam_render_data(
        ships, ship_instances=ship_instances, memo=memo))
    host_io.set_tractor_beams(host_loop._build_tractor_beam_render_data(
        ships, ship_instances=ship_instances, memo=memo))
    return _beams("phaser"), _beams("tractor")


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


def _phaser_targets_by_shield(bs):
    """{shields_up: count of ships' firing banks aimed at such a target}
    over ships whose builder output is non-empty."""
    from engine import host_loop
    seen = {True: 0, False: 0}
    for ship in bs.ships:
        if not host_loop._build_phaser_beam_render_data(
                [ship], ship_instances=bs.ship_instances):
            continue
        for bank in host_loop._firing_banks(ship.GetPhaserSystem()):
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
        got = _python_feed(beam_scene.ships, beam_scene.ship_instances)
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


# ── Task 4: the native feed, frame by frame, against the Python builders ────

import random  # noqa: E402

from engine.appc import native_combat as nc  # noqa: E402


def _native_feed(ships, ship_instances, want=None):
    """native_combat.beam_feed, then what it pushed: (ok, phaser bytes,
    tractor bytes). Both vectors are seeded with a sentinel first, so a
    binding that skipped an assignment reads back the sentinel, never the
    Python frame pushed before it. With `want` (the _python_feed pair), the
    binding's own (n_phasers, n_tractors) must equal its lengths."""
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
    if ok and want is not None:
        assert returned == [(len(want[0]), len(want[1]))], returned
    return ok, _beams("phaser"), _beams("tractor")


# Matches no descriptor a builder makes (a width of -1, 3 sides).
SENTINEL = dict(MINIMAL, width=-1.0, num_sides=3)


class _Coverage:
    """Spies on the Python builders' endpoint and pair helpers while armed,
    so each compared frame says which beam cases it held: a pair ended on
    the shield bubble, one ended on the hull mesh trace, a tractor pair, a
    Manual Aim pair, and a lock on the posed ship."""

    def __init__(self, monkeypatch):
        from engine import host_loop
        from engine.appc import combat
        self.armed = False
        self.frame = set()
        self.counts = dict.fromkeys(
            ("bubble", "hull_trace", "tractor", "manual_aim", "posed_lock",
             "frames", "phaser_beams", "tractor_beams"), 0)
        bubble = combat.shield_bubble_entry
        resolve = combat._resolve_hit_point
        pair = host_loop._beam_descriptor_pair

        def bubble_spy(*a, **k):
            r = bubble(*a, **k)
            if self.armed and r is not None:
                self.frame.add("bubble")
            return r

        def resolve_spy(*a, **k):
            r = resolve(*a, **k)
            if self.armed and r[1] is not None:
                self.frame.add("hull_trace")
            return r

        def pair_spy(ship, bank, ship_instances):
            r = pair(ship, bank, ship_instances)
            if self.armed and r:
                tractor = bank.GetParentSubsystem() is \
                    ship.GetTractorBeamSystem()
                if tractor:
                    self.frame.add("tractor")
                elif ship.is_using_target_offset():
                    self.frame.add("manual_aim")
                lock = ship.__dict__.get("_target_subsystem")
                if (not tractor and lock is not None
                        and self.posed is not None
                        and lock.GetParentShip() is self.posed):
                    self.frame.add("posed_lock")
            return r

        self.posed = None
        monkeypatch.setattr(combat, "shield_bubble_entry", bubble_spy)
        monkeypatch.setattr(combat, "_resolve_hit_point", resolve_spy)
        monkeypatch.setattr(host_loop, "_beam_descriptor_pair", pair_spy)

    def python_feed(self, ships, ship_instances):
        self.frame = set()
        self.armed = True
        try:
            got = _python_feed(ships, ship_instances)
        finally:
            self.armed = False
        for k in self.frame:
            self.counts[k] += 1
        self.counts["frames"] += 1
        self.counts["phaser_beams"] += len(got[0])
        self.counts["tractor_beams"] += len(got[1])
        return got


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


def test_native_feed_equals_python_every_frame(beam_scene, monkeypatch):
    from engine.appc.ship_iter import iter_ships
    from tests.host.test_native_k2_differential import (
        OPS, POSE_FROM, POSE_TO, POSED)
    bs = beam_scene
    sc = bs.scene
    start = sc.tick
    assert start < POSE_FROM, start
    cov = _Coverage(monkeypatch)
    manual = random.Random(MANUAL_SEED)

    def frame(scene):
        _manual_aim_beat(scene, scene.tick - start, manual)
        cov.posed = (scene.ship(POSED)
                     if POSE_FROM <= scene.tick < POSE_TO else None)
        ships = list(iter_ships())
        want = cov.python_feed(ships, bs.ship_instances)
        ok, phasers, tractors = _native_feed(ships, bs.ship_instances, want)
        assert ok, "tick %d: the native feed fell back" % scene.tick
        assert phasers == want[0], "tick %d: phasers differ" % scene.tick
        assert tractors == want[1], "tick %d: tractors differ" % scene.tick

    sc.run(OPS, 1, ticks=start + 300, before_tick=frame)
    c = cov.counts
    print("\nbeam feed coverage over %d frames: %r" % (c["frames"], c))
    assert c["frames"] == 300, c
    assert nc.beam_feed_fallbacks == 0
    for case in ("bubble", "hull_trace", "tractor", "manual_aim"):
        assert c[case] > 0, "no frame had a %s pair: %r" % (case, c)


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


def test_native_feed_equals_python_across_regions(native_combat_on, regions,
                                                  far_scene):
    """far_scene's player 450,000 GU out in an unmapped set (another frame),
    viewed instead from Ona1 at a non-zero render origin: one tow split
    from Ona1 to Ona2, one from Ona2 back to Ona1, one into the far set.
    (native_combat_on: the K2 differential's autouse _hermetic, imported
    here, resets the switch off.)"""
    ships = _regions_ships(far_scene)
    want = _python_feed(ships, None)
    # The two pairs in the viewed frame draw; the one in another frame not.
    assert len(want[1]) == 4, want
    ok, phasers, tractors = _native_feed(ships, None, want)
    assert ok
    assert (phasers, tractors) == want
    assert nc.beam_feed_fallbacks == 0


def test_a_throw_leaves_no_partial_feed_and_python_fills_the_frame(
        beam_scene, monkeypatch):
    import App
    from engine import host_loop
    from engine.appc.sets import SetClass_Create
    bs = beam_scene
    # A firing ship moved to a set of its own frame: Python draws none of
    # its beams; the native feed must look that set's frame up -- and it is
    # left out of the frames table, so the feed throws.
    # The LAST firing shooter, so ships before it in list order have drawn
    # pairs into the native build when it throws: a partial build really is
    # discarded.
    shooter = [s for s in bs.ships if s is not bs.player
               and s.GetPhaserSystem() is not None
               and host_loop._firing_banks(s.GetPhaserSystem())][-1]
    before = bs.ships[:bs.ships.index(shooter)]
    elsewhere = SetClass_Create()
    App.g_kSetManager.AddSet(elsewhere, "Elsewhere")
    name = shooter.GetName()
    shooter.GetContainingSet().RemoveObjectFromSet(name)
    elsewhere.AddObjectToSet(shooter, name)
    gone = nc._slot_of(elsewhere)
    assert gone is not None
    table = nc._beam_frames

    def without(*a, **k):
        t = table(*a, **k)
        assert gone in t, "premise: the set is in the table"
        del t[gone]
        return t

    monkeypatch.setattr(nc, "_beam_frames", without)
    ships = [s for s in bs.ships if s.GetContainingSet() is not None]
    assert host_loop._build_phaser_beam_render_data(
        [s for s in before if s in ships],
        ship_instances=bs.ship_instances), \
        "premise: a ship before the shooter draws phasers"
    _h.set_phaser_beams([FULL])
    _h.set_tractor_beams([MINIMAL, FULL])
    try:
        assert nc.beam_feed(ships, bs.ship_instances) is False
        assert nc.beam_feed_fallbacks == 1
        # Neither vector was touched: no partial frame.
        assert _beams("phaser") == [packed(FULL)]
        assert _beams("tractor") == [packed(MINIMAL), packed(FULL)]
        # host_loop's frame: the native feed falls back, Python fills it.
        host_loop._push_combat_render_data(
            ships, ship_instances=bs.ship_instances, player=bs.player)
        assert nc.beam_feed_fallbacks == 2
        pushed = (_beams("phaser"), _beams("tractor"))
        want = _python_feed(ships, bs.ship_instances)
        assert want[0], "premise: other ships' phasers still draw"
        assert pushed == want
    finally:
        _h.set_phaser_beams([])
        _h.set_tractor_beams([])


def test_a_patched_getter_is_not_honoured(beam_scene, monkeypatch):
    from engine.appc import weapon_subsystems as ws
    bs = beam_scene
    want = _python_feed(bs.ships, bs.ship_instances)
    assert want[0], "premise: phasers draw"
    monkeypatch.setattr(ws.PhaserBank, "GetPhaserWidth", lambda self: 9.0)
    patched = _python_feed(bs.ships, bs.ship_instances)
    width = 10          # emitter 3, target 3, colour 4, then the width
    outer = [struct.unpack(PACK, d)[width] for d in patched[0][0::2]]
    assert outer and all(w == f32(9.0 * 3.0) for w in outer), \
        "premise: the Python builder honours the patch"
    ok, phasers, tractors = _native_feed(bs.ships, bs.ship_instances, want)
    assert ok
    assert nc.beam_feed_fallbacks == 0
    # The mirrored widths, not the patched getter's.
    assert (phasers, tractors) == want


# ── Counters: did the native feed run every frame? ──────────────────────────

def test_the_feed_counts_native_frames_fallbacks_and_stand_downs(
        beam_scene, monkeypatch):
    import types
    from engine.core.tracked_instances import TrackedInstances
    bs = beam_scene
    assert nc.beam_feed_counts() == {
        "native": 0, "fallbacks": 0,
        "stand_downs": {"off": 0, "audit": 0, "unsnapped": 0,
                        "instances": 0, "no_host": 0}}
    assert type(bs.ship_instances) is TrackedInstances
    assert nc.beam_feed(bs.ships, bs.ship_instances) is True
    assert nc.beam_feed(bs.ships, bs.ship_instances) is True
    # A ship with no row: the mirror cannot answer.
    assert nc.beam_feed(bs.ships + [types.SimpleNamespace()],
                        bs.ship_instances) is False
    # A plain dict: not the session's TrackedInstances.
    assert nc.beam_feed(bs.ships, dict(bs.ship_instances.items())) is False
    monkeypatch.setattr(nc, "_switch", False)
    assert nc.beam_feed(bs.ships, bs.ship_instances) is False
    c = nc.beam_feed_counts()
    assert c["native"] == 2 and c["fallbacks"] == 1, c
    assert c["stand_downs"] == {"off": 1, "audit": 0, "unsnapped": 0,
                                "instances": 1, "no_host": 0}, c
    assert nc.beam_feed_fallbacks == 1
    nc.reset()
    assert nc.beam_feed_counts() == {
        "native": 0, "fallbacks": 0,
        "stand_downs": dict.fromkeys(
            ("off", "audit", "unsnapped", "instances", "no_host"), 0)}
    assert nc.beam_feed_fallbacks == 0


# ── Render goldens (phase 6 follow-up 4, Task 1) ────────────────────────────
#
# The same scenes as the equality tests above, checked against goldens
# recorded from the Python builders (tests/helpers/render_golden.py): under
# UPDATE_RENDER_GOLDEN=1 the frames are the Python builders' and are
# recorded; otherwise they are the native feed's and are checked.

from tests.helpers import render_golden  # noqa: E402


def golden_beam_frame(ships, ship_instances):
    """This frame's beams as a render_golden frame: the Python builders'
    while recording, else the native feed's (a feed that fell back leaves
    its sentinels, so the frame differs from the golden)."""
    if render_golden.recording():
        render_golden.require_python_builders()
        phasers, tractors = _python_feed(ships, ship_instances)
        source = "python"
    else:
        _ok, phasers, tractors = _native_feed(ships, ship_instances)
        source = "native"
    return render_golden.frame(phasers=phasers, tractors=tractors,
                               source=source)


def _record_or_check(scene_name, frames):
    if render_golden.recording():
        render_golden.record(scene_name, frames)
    render_golden.check(scene_name, frames)


def test_beam_scene_matches_the_golden(beam_scene):
    """test_native_feed_equals_python_every_frame's 300 frames: the K2
    differential's seeded op stream, its posed beat and the Manual Aim
    beat."""
    from engine.appc.ship_iter import iter_ships
    from tests.host.test_native_k2_differential import OPS
    bs = beam_scene
    sc = bs.scene
    start = sc.tick
    manual = random.Random(MANUAL_SEED)
    frames = []

    def frame(scene):
        _manual_aim_beat(scene, scene.tick - start, manual)
        frames.append(golden_beam_frame(list(iter_ships()),
                                        bs.ship_instances))

    sc.run(OPS, 1, ticks=start + 300, before_tick=frame)
    assert len(frames) == 300
    assert sum(len(f["phasers"]) for f in frames) > 0
    assert sum(len(f["tractors"]) for f in frames) > 0
    _record_or_check("beam_scene", frames)


def test_beam_regions_match_the_golden(native_combat_on, regions, far_scene):
    """test_native_feed_equals_python_across_regions' one frame."""
    ships = _regions_ships(far_scene)
    frames = [golden_beam_frame(ships, None)]
    _record_or_check("beam_regions", frames)
