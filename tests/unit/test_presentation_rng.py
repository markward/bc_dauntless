"""The presentation random-number generator P (engine/appc/presentation_rng.py;
spec docs/superpowers/specs/2026-11-02-presentation-rng-design.md, map
docs/reference/engine/native-combat/rng-map.md §7.1-7.2).

P serves every cosmetic draw, so a sound, a puff or a bridge animation never
shifts a gameplay roll. Inside ``scope()`` the SDK's own draw
(``App.g_kSystemWrapper.GetRandomNumber``) answers from P, so an SDK script
the engine runs only to present draws from it too. The scope is thread-local
and exception-safe.
"""
import random
import threading

import pytest

import App

from engine.appc import presentation_rng as prng


def _s1_state():
    return App.g_kSystemWrapper._rng.getstate()


# ── The generator ───────────────────────────────────────────────────────────

def test_rand_has_get_random_number_semantics():
    prng.reset()
    assert prng.rand(0) == 0
    assert prng.rand(-3) == 0
    for _ in range(50):
        n = prng.rand(10)
        assert isinstance(n, int) and 0 <= n < 10
    assert prng.rand(7.9) in range(7)       # int(n), as GetRandomNumber


def test_rand_matches_a_random_seeded_with_the_presentation_seed():
    prng.reset()
    ref = random.Random(prng.PRESENTATION_SEED)
    assert [prng.rand(1000) for _ in range(20)] == \
        [ref.randrange(1000) for _ in range(20)]


def test_reset_repeats_the_sequence_and_takes_a_seed():
    prng.reset()
    a = [prng.random(), prng.uniform(2.0, 3.0), prng.gauss(0.0, 1.0),
         prng.randrange(5, 50), prng.rand(9)]
    prng.reset()
    b = [prng.random(), prng.uniform(2.0, 3.0), prng.gauss(0.0, 1.0),
         prng.randrange(5, 50), prng.rand(9)]
    assert a == b
    prng.reset(1234)
    c = [prng.rand(1 << 30) for _ in range(5)]
    prng.reset(1234)
    assert c == [prng.rand(1 << 30) for _ in range(5)]
    prng.reset()
    assert c != [prng.rand(1 << 30) for _ in range(5)]


def test_p_draws_leave_the_gameplay_streams_alone():
    s1, s2 = _s1_state(), random.getstate()
    prng.rand(10), prng.random(), prng.uniform(0, 1), prng.gauss(0, 1)
    prng.randrange(4)
    assert _s1_state() == s1
    assert random.getstate() == s2


# ── The scope ───────────────────────────────────────────────────────────────

def test_get_random_number_answers_from_p_inside_the_scope():
    """RM §7.5 test 1: inside scope() GetRandomNumber leaves S1 alone and
    advances P; outside, the reverse."""
    prng.reset()
    s1 = _s1_state()
    with prng.scope():
        got = [App.g_kSystemWrapper.GetRandomNumber(1000) for _ in range(5)]
        assert App.g_kSystemWrapper.GetRandomNumber(0) == 0
    assert _s1_state() == s1
    prng.reset()
    assert got == [prng.rand(1000) for _ in range(5)]

    prng.reset()
    p = prng._rng.getstate()
    App.g_kSystemWrapper.GetRandomNumber(1000)
    assert prng._rng.getstate() == p
    assert _s1_state() != s1


def test_in_scope_follows_nesting():
    assert not prng.in_scope()
    with prng.scope():
        assert prng.in_scope()
        with prng.scope():
            assert prng.in_scope()
        assert prng.in_scope()
    assert not prng.in_scope()


def test_an_exception_inside_a_scope_unwinds_it():
    with pytest.raises(RuntimeError):
        with prng.scope():
            with prng.scope():
                raise RuntimeError("boom")
    assert not prng.in_scope()
    s1 = _s1_state()
    App.g_kSystemWrapper.GetRandomNumber(10)
    assert _s1_state() != s1        # back on S1


def test_the_scope_is_thread_local():
    """Another thread's scope never moves this thread's draws onto P, and
    this thread's scope never moves another's."""
    seen = {}
    entered, release = threading.Event(), threading.Event()

    def other():
        with prng.scope():
            entered.set()
            release.wait(5.0)
        seen["after"] = prng.in_scope()

    t = threading.Thread(target=other)
    t.start()
    assert entered.wait(5.0)
    try:
        assert not prng.in_scope()
        s1 = _s1_state()
        App.g_kSystemWrapper.GetRandomNumber(10)
        assert _s1_state() != s1
    finally:
        release.set()
        t.join(5.0)
    assert seen["after"] is False

    def probe():
        seen["inner"] = prng.in_scope()

    with prng.scope():
        t = threading.Thread(target=probe)
        t.start()
        t.join(5.0)
    assert seen["inner"] is False


# ── GetRandomPointOnModel ───────────────────────────────────────────────────

def _object(radius=10.0):
    from engine.appc.objects import ObjectClass
    obj = ObjectClass()
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    obj.SetRadius(radius)
    return obj


def test_random_point_on_model_draws_p_inside_the_scope():
    obj = _object()
    prng.reset()
    s1, s2 = _s1_state(), random.getstate()
    with prng.scope():
        a = obj.GetRandomPointOnModel()
    assert (_s1_state(), random.getstate()) == (s1, s2)
    prng.reset()
    with prng.scope():
        b = obj.GetRandomPointOnModel()
    assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


def test_random_point_on_model_draws_the_module_random_outside():
    obj = _object()
    p = prng._rng.getstate()
    random.seed(5)
    a = obj.GetRandomPointOnModel()
    assert prng._rng.getstate() == p
    random.seed(5)
    b = obj.GetRandomPointOnModel()
    assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


def test_random_point_on_model_surface_pick_follows_the_scope(monkeypatch):
    """The render instance's surface-point pick (live) takes the same
    stream as the bounding-sphere fallback (headless)."""
    from engine import renderer
    from engine.appc import render_instances
    obj = _object()
    render_instances.register(obj, 42)
    try:
        monkeypatch.setattr(renderer, "instance_surface_points",
                            lambda iid: [(float(i), 0.0, 0.0)
                                         for i in range(100)])
        s2 = random.getstate()
        p = prng._rng.getstate()
        with prng.scope():
            obj.GetRandomPointOnModel()
        assert random.getstate() == s2
        assert prng._rng.getstate() != p
        p = prng._rng.getstate()
        obj.GetRandomPointOnModel()
        assert prng._rng.getstate() == p
        assert random.getstate() != s2
    finally:
        render_instances.reset()


def test_random_unit_vector_draws_p_inside_the_scope():
    """Final review M4: a death script (run in the scope) that asks for a
    random unit vector, as Effects.CollisionEffect does, draws P, not the
    AI's private unit-vector generator (flee/evade headings)."""
    from engine.appc import math as appc_math
    appc_math.reset_random_unit_vector_rng()
    unit = appc_math._unit_vector_rng.getstate()
    s1, s2 = _s1_state(), random.getstate()
    prng.reset()
    with prng.scope():
        a = App.TGPoint3_GetRandomUnitVector()
    assert appc_math._unit_vector_rng.getstate() == unit
    assert (_s1_state(), random.getstate()) == (s1, s2)
    assert abs(a.x * a.x + a.y * a.y + a.z * a.z - 1.0) < 1e-9
    prng.reset()
    with prng.scope():
        b = App.TGPoint3_GetRandomUnitVector()
    assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


def test_random_unit_vector_draws_its_own_generator_outside():
    from engine.appc import math as appc_math
    p = prng._rng.getstate()
    appc_math.reset_random_unit_vector_rng()
    unit = appc_math._unit_vector_rng.getstate()
    App.TGPoint3_GetRandomUnitVector()
    assert prng._rng.getstate() == p
    assert appc_math._unit_vector_rng.getstate() != unit


# ── Gameplay is never drawn from P ──────────────────────────────────────────

def test_apply_hit_inside_a_presentation_scope_is_caught():
    """Review Focus 1: a presentation call that reaches gameplay (an SDK
    presentation script that damages, a death script calling a gameplay
    API) fails loudly under tests instead of drawing gameplay numbers from
    P."""
    from engine.appc import combat
    with prng.scope():
        with pytest.raises(AssertionError, match="presentation scope"):
            combat.apply_hit(None, 1.0, None, None)
    assert not prng.in_scope()


def test_the_gameplay_check_is_silent_in_production(monkeypatch, capsys):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    with prng.scope():
        prng.check_gameplay("apply_hit", modules={})        # no raise
        with pytest.raises(AssertionError):
            prng.check_gameplay("apply_hit", modules={"pytest": None})
    prng.check_gameplay("apply_hit")                        # out of scope
    assert capsys.readouterr().err == ""


def test_under_developer_the_gameplay_check_logs_once_and_carries_on(
        monkeypatch, capsys):
    """Final review M2: a dev session plays the same game as production, so
    --developer reports a scoped gameplay call on stderr, once per call
    site, and never raises (raising would skip the rest of the script and
    its damage). Only pytest raises."""
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    monkeypatch.setattr(prng, "_reported", set())
    with prng.scope():
        prng.check_gameplay("apply_hit", modules={})        # no raise
        prng.check_gameplay("apply_hit", modules={})
        prng.check_gameplay("other_site", modules={})
    prng.check_gameplay("third_site", modules={})           # out of scope
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2, lines
    assert lines[0].startswith("[presentation-rng] apply_hit ")
    assert lines[1].startswith("[presentation-rng] other_site ")


# ── Every differential's seed_every_rng resets P ────────────────────────────

def _seed_copies():
    from tests.helpers import k3_fight
    from tests.helpers import k1_fight as k1d
    from tests.host import test_native_k2_differential as k2d
    return (k3_fight.seed_every_rng, k1d._seed_every_rng,
            k2d._seed_every_rng)


@pytest.mark.parametrize("which", range(3))
def test_every_seed_every_rng_copy_resets_p(which):
    """RM §7.5 test 7: the two arms of a differential start P alike, or a
    presentation draw could differ between them."""
    seed = _seed_copies()[which]
    prng.reset()
    fresh = prng._rng.getstate()
    prng.rand(1000)
    seed(0)
    assert prng._rng.getstate() == fresh


# ── Mission swap ────────────────────────────────────────────────────────────

def _swap():
    """Drive the REAL _drain_pending_swap (as test_damage_geometry_mission
    _swap does), so deleting a reset line from the production block fails."""
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()


def test_mission_swap_reseeds_p_and_rearms_the_hit_sound(monkeypatch):
    """R3: P reseeded at every mission load (host_loop._reset_session_scratch,
    the seam every load, swap and in-transit mission change runs). Review
    Focus 4: the hit-sound edge stamps are cleared too: a new ship that
    reuses the old one's id() inside the contact gap of its stamp would
    otherwise be silent. (A clock that went backwards re-arms on its own,
    _audio_should_play, so the probe clock sits just AFTER the stamp: only
    the reset can re-arm it.)"""
    from engine.appc import damage_decals, hit_feedback
    ship = object()
    clock = [100.0]
    monkeypatch.setattr(damage_decals, "_game_time_source", lambda: clock[0])
    assert hit_feedback._audio_should_play(ship, hit_feedback.Severity.HULL)
    prng.reset()
    fresh = prng._rng.getstate()
    prng.rand(1000)

    _swap()

    assert prng._rng.getstate() == fresh
    clock[0] = 100.0 + hit_feedback._AUDIO_CONTACT_GAP_S / 2   # the same id(ship)
    assert hit_feedback._audio_should_play(ship, hit_feedback.Severity.HULL)


# ── A hit's presentation leaves the gameplay streams alone ──────────────────

class _Hull:
    def GetConditionPercentage(self): return 1.0
    def IsDestroyed(self): return 0


class _HitShip:
    def __init__(self):
        self._hull = _Hull()
    def GetHull(self): return self._hull


def test_a_hit_presents_without_touching_the_gameplay_streams(monkeypatch):
    """RM §7.5 test 2: torpedo hull hits and critical hits, with a sound
    manager and a renderer instance (so the hit sound's pick, the smoke roll
    and the SDK smoke recipe all run), leave S1 and S2 where they were."""
    import Effects
    import LoadDamageHitSounds
    import LoadTacticalSounds
    from engine import host_io
    from engine.appc import hit_feedback, hull_hit_smoke, particles
    from engine.appc.math import TGPoint3

    class _Snd:
        def Play(self, position=None): pass

    class _Mgr:
        def GetSound(self, name): return _Snd()

    monkeypatch.setattr(App, "g_kSoundManager", _Mgr(), raising=False)
    for name in ("shield_hit", "damage_decal_add", "hull_damage_add"):
        monkeypatch.setattr(host_io, name, lambda *a, **k: None)
    monkeypatch.setattr(host_io, "world_to_body",
                        lambda *a, **k: ((0.1, 0.2, 0.3), (0.0, 0.0, 1.0)))
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    if LoadDamageHitSounds.GetRandomSound is None:
        monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                            LoadTacticalSounds.GetRandomSound)
    seen = {"picks": 0, "smokes": 0}
    picks = (LoadTacticalSounds.GetRandomSound,
             LoadDamageHitSounds.GetRandomSound)

    def counted(orig):
        def pick(pool):
            seen["picks"] += 1
            return orig(pool)
        return pick

    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound",
                        counted(picks[0]))
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                        counted(picks[1]))
    smoke = Effects.CreateSmokeHigh

    def counted_smoke(*a, **k):
        seen["smokes"] += 1
        return smoke(*a, **k)

    monkeypatch.setattr(Effects, "CreateSmokeHigh", counted_smoke)

    random.seed(3)
    App.g_kSystemWrapper.SetRandomSeed(3)
    s1, s2 = _s1_state(), random.getstate()
    sub = object()
    ships = []      # held, so no freed ship's id() is reused (and throttled)
    for i in range(40):
        ship = _HitShip()
        ships.append(ship)
        critical = i % 2 == 1
        hit_feedback.dispatch(
            ship=ship, source=None, point=TGPoint3(1.0, 2.0, 3.0),
            normal=TGPoint3(0.0, 1.0, 0.0), damage=100.0,
            subsystem=sub if critical else ship.GetHull(),
            absorbed_shields=0.0, absorbed_subsystem=50.0 if critical else 0.0,
            absorbed_hull=50.0, sub_transition="destroyed" if critical else None,
            ship_instances={ship: 7}, weapon_type="torpedo")
    particles.reset()
    hull_hit_smoke.reset()
    assert seen["picks"] == 40 and seen["smokes"] > 0, seen
    assert _s1_state() == s1
    assert random.getstate() == s2
