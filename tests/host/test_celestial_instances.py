"""The system map's planets and moons are DRAWN from the draw list
(system-frames Plan 3, Task 4).

Task 3 stopped realizing a mapped set's Planet objects; the map draws them
instead. Every tick the celestial render instances are diffed against
celestial.draw_list(frames.viewing_set()): new keys are created (scaled to
radius_gu over the model's bound-sphere radius) and placed with
set_world_transform (static, not store-bound), vanished keys are destroyed,
a key whose view position changed is re-pushed, and an unchanged list costs
no renderer call at all.

A script that moves or resizes a mapped body is logged loudly, once per body
per mission, and never arbitrated.

Fake renderer mirrors tests/unit/test_realize_set.py and
tests/host/test_render_scope_viewed_frame.py.
"""
import pytest

import App
import engine.host_loop as host_loop
from engine.appc.sets import SetClass_Create
from engine.core.game import Game, _set_current_game
from engine.systems import celestial, frames, region_hooks, resolve
from tests.helpers.mapped_regions import load_region

_HALF = 2.0     # the fake model's bound-sphere radius


class _FakeRenderer:
    def __init__(self):
        self._next = 1
        self.live = set()
        self.pushed = {}
        self.visible = {}
        self.calls = []

    def load_model(self, path, search, texture_replacements=None, decals=None,
                   scale=1.0, geosphere=False):
        self.calls.append(("load_model", path))
        return 100

    def model_aabb(self, h):
        self.calls.append(("model_aabb", h))
        return ((0.0, 0.0, 0.0), (_HALF, _HALF, _HALF))

    def create_instance(self, h):
        self.calls.append(("create_instance", h))
        iid = self._next
        self._next += 1
        self.live.add(iid)
        return iid

    def destroy_instance(self, iid):
        self.calls.append(("destroy_instance", iid))
        self.live.discard(iid)

    def set_world_transform(self, iid, m):
        self.calls.append(("set_world_transform", iid))
        self.pushed[iid] = m

    def set_emissive_scale(self, iid, s):
        self.calls.append(("set_emissive_scale", iid))

    def set_rim_eligible(self, iid, b):
        pass

    def set_surface_rock(self, iid, rock):
        pass

    def set_rim_strength(self, iid, s):
        pass

    def nebula_lightning_enabled(self):
        return False

    def set_visible(self, iid, v):
        self.calls.append(("set_visible", iid))
        self.visible[iid] = v


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    def _clear():
        App.g_kSetManager._sets.clear()
        App.g_kSetManager.ClearRenderedSet()
        _set_current_game(None)
        host_loop._mapped_body_warned.clear()
    _clear()
    monkeypatch.setattr(host_loop, "_planet_model_path",
                        lambda rel, **k: f"/fake/{rel}")
    yield
    _clear()


@pytest.fixture
def ona():
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    ona3 = load_region("Ona", "Ona3")
    for s in (ona1, ona2, ona3):
        assert region_hooks.is_mapped(s), "premise: a mapped region"
    return ona1, ona2, ona3


def _make_player(pSet):
    s = App.ShipClass_Create()
    s.SetName("Player")
    pSet.AddObjectToSet(s, "Player")
    game = Game()
    game.SetPlayer(s)
    _set_current_game(game)
    return s


def _translation(m):
    return (m[3], m[7], m[11])


def _scale(m):
    return m[0]


def _reconcile(sess, r):
    host_loop._reconcile_celestial_instances(sess, r)


def test_viewing_ona1_realizes_every_ona_body_at_its_view_position(ona):
    ona1, *_ = ona
    _make_player(ona1)
    assert frames.viewing_set() is ona1
    bodies = celestial.draw_list(ona1)
    assert len(bodies) == 3, "premise: Ona's three planets"
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)

    assert set(sess.celestial_instances) == {b.key for b in bodies}
    assert len(set(sess.celestial_instances.values())) == len(bodies)
    for b in bodies:
        iid = sess.celestial_instances[b.key]
        assert iid in r.live
        m = r.pushed[iid]
        assert _translation(m) == pytest.approx(b.position)
        assert _scale(m) == pytest.approx(b.radius_gu / _HALF)


def test_moving_the_view_to_a_sibling_repositions_without_recreating(ona):
    ona1, _ona2, _ona3 = ona
    _make_player(ona1)
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    before = dict(sess.celestial_instances)
    t1 = {k: _translation(r.pushed[iid]) for k, iid in before.items()}
    n = len(r.calls)

    App.g_kSetManager.MakeRenderedSet("Ona2")
    assert frames.viewing_set().GetName() == "Ona2"
    _reconcile(sess, r)

    assert sess.celestial_instances == before
    assert not any(c[0] in ("create_instance", "destroy_instance")
                   for c in r.calls[n:])
    a1, a2 = resolve.anchor_of("Ona1"), resolve.anchor_of("Ona2")
    for k, iid in before.items():
        assert _translation(r.pushed[iid]) == pytest.approx(
            tuple(p + x1 - x2 for p, x1, x2 in zip(t1[k], a1, a2)))


def test_leaving_the_system_destroys_its_bodies(ona):
    ona1, *_ = ona
    player = _make_player(ona1)
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    iids = set(sess.celestial_instances.values())
    assert iids

    plain = SetClass_Create()
    App.g_kSetManager.AddSet(plain, "Plain")
    ona1.RemoveObjectFromSet("Player")
    plain.AddObjectToSet(player, "Player")
    assert frames.viewing_set() is plain
    _reconcile(sess, r)

    assert sess.celestial_instances == {}
    assert sess.celestial_placed == {}
    assert not (iids & r.live)


def test_an_idle_tick_touches_nothing(ona):
    ona1, *_ = ona
    _make_player(ona1)
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    n = len(r.calls)
    _reconcile(sess, r)
    assert r.calls[n:] == []


def test_a_body_with_no_resolvable_model_is_skipped_loudly(ona, monkeypatch,
                                                           capsys):
    ona1, *_ = ona
    _make_player(ona1)
    bad = next(b for b in celestial.draw_list(ona1) if b.name == "Ona 2")
    monkeypatch.setattr(
        host_loop, "_planet_model_path",
        lambda rel, **k: None if rel == bad.model else f"/fake/{rel}")
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    _reconcile(sess, r)

    assert bad.key not in sess.celestial_instances
    assert len(sess.celestial_instances) == 2
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if "Ona 2" in ln]
    assert len(lines) == 1, lines


def test_teardown_destroys_and_forgets_celestial_instances(ona):
    ona1, *_ = ona
    _make_player(ona1)
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    iids = set(sess.celestial_instances.values())
    sess.teardown(r)
    assert sess.celestial_instances == {} and sess.celestial_placed == {}
    assert not (iids & r.live)


# ── the mapped-body detector ────────────────────────────────────────────────

def _warnings(capsys):
    return [ln for ln in capsys.readouterr().out.splitlines()
            if ln.startswith("[systems] mapped body moved by a script:")]


def test_an_untouched_mapped_set_raises_no_warning(ona, capsys):
    ona1, *_ = ona
    host_loop._check_mapped_bodies_untouched(ona1)
    assert _warnings(capsys) == []


def test_a_script_moving_a_mapped_planet_warns_once_and_changes_nothing(
        ona, capsys):
    ona1, *_ = ona
    planet = ona1.GetObject("Ona 1")
    assert planet is not None, "premise: Ona1 carries its Planet object"
    drawn = celestial.draw_list(ona1)
    p = planet.GetWorldLocation()
    planet.SetTranslateXYZ(p.x + 500.0, p.y, p.z)

    host_loop._check_mapped_bodies_untouched(ona1)
    host_loop._check_mapped_bodies_untouched(ona1)

    got = _warnings(capsys)
    assert len(got) == 1 and "Ona1/Ona 1" in got[0], got
    assert celestial.draw_list(ona1) == drawn
    assert planet.GetWorldLocation().x == pytest.approx(p.x + 500.0)


def test_a_script_resizing_a_mapped_planet_warns(ona, capsys):
    ona1, *_ = ona
    planet = ona1.GetObject("Ona 1")
    planet.SetRadius(planet.GetRadius() * 0.5)
    host_loop._check_mapped_bodies_untouched(ona1)
    assert len(_warnings(capsys)) == 1


def test_an_unmapped_view_is_not_checked(capsys):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "Plain")
    host_loop._check_mapped_bodies_untouched(s)
    host_loop._check_mapped_bodies_untouched(None)
    assert _warnings(capsys) == []


def test_a_mission_swap_forgets_which_bodies_were_warned_about(ona, capsys):
    """One warning per body per MISSION: reset_sdk_globals (every swap and
    initial load goes through it) clears the record."""
    ona1, *_ = ona
    planet = ona1.GetObject("Ona 1")
    p = planet.GetWorldLocation()
    planet.SetTranslateXYZ(p.x + 500.0, p.y, p.z)
    host_loop._check_mapped_bodies_untouched(ona1)
    assert len(_warnings(capsys)) == 1

    host_loop.reset_sdk_globals()
    host_loop._check_mapped_bodies_untouched(ona1)
    assert len(_warnings(capsys)) == 1


# ── the warp-streak hide ────────────────────────────────────────────────────

class _Warp:
    def __init__(self, streak):
        self._streak = streak

    def is_active(self):
        return self._streak > 0.0

    def streak_intensity(self):
        return self._streak


def test_map_bodies_hide_during_the_warp_streak_and_return_on_the_stop_frame(
        ona, monkeypatch):
    """Exactly as session.planet_instances: hidden while the streak runs,
    restored on the single frame it stops."""
    from engine import warp_vfx
    from engine.core.transform_buffer import TransformBuffer
    ona1, *_ = ona
    player = _make_player(ona1)
    sess = host_loop.MissionSession(mission_name="t")
    r = _FakeRenderer()
    _reconcile(sess, r)
    iids = set(sess.celestial_instances.values())
    assert len(iids) == 3
    sess.ship_instances[player] = 99
    sess.player = player
    monkeypatch.setattr(host_loop, "_warp_hidden", False)

    def _sync():
        host_loop._sync_instance_transforms(
            r, sess, player, TransformBuffer(), 1.0,
            game_time=1.0, model_scale=1.0)

    monkeypatch.setattr(warp_vfx, "get", lambda: _Warp(1.0))
    _sync()
    assert {i: r.visible.get(i) for i in iids} == {i: False for i in iids}

    monkeypatch.setattr(warp_vfx, "get", lambda: _Warp(0.0))
    _sync()
    assert {i: r.visible.get(i) for i in iids} == {i: True for i in iids}
