"""Phase D Task 1: wings publish a status each led tick and see their
side's other wings in Context.allies (spec 2026-11-09 phase D §2-§3)."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import brain, decisions, roster, service, tree  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        service.reset_all()
    _clear()
    yield
    _clear()


@pytest.fixture
def now(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(App.g_kUtopiaModule, "GetGameTime", lambda: t[0])
    return t


def _ship(pSet, kind, name, xyz):
    s = loadspacehelper.CreateShip(kind, pSet, name, None, 0, 0)
    s.SetTranslateXYZ(*xyz)
    return s


def _wing(pSet, wid, side, prefix, origin, enemy_names, enemy_xyz):
    import AI.Compound.BasicAttack
    group = App.ObjectGroup()
    ships = {}
    for name, xyz in zip(enemy_names, enemy_xyz):
        ships[name] = _ship(pSet, "BirdOfPrey", name, xyz)
        group.AddName(name)
    wing = roster.create_wing(wid, group)
    wing.side = side
    for i in (1, 2, 3):
        n = "%s%d" % (prefix, i)
        ships[n] = _ship(pSet, "Akira", n,
                         (origin[0] - 20.0 * (i - 1), origin[1], origin[2]))
        roster.add_member(wing, n)
    for i in (1, 2, 3):
        s = ships["%s%d" % (prefix, i)]
        s.SetAI(tree.wrap_tree(s, AI.Compound.BasicAttack.CreateAI(
            s, wing.target_group, Difficulty=0.5), wing))
    brain.arm_chain(wing)
    return wing, ships


def _two_sides():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    a, sa = _wing(pSet, "a", "friendly", "a", (0.0, 0.0, 0.0),
                  ["ea"], [(150.0, 0.0, 0.0)])
    b, sb = _wing(pSet, "b", "friendly", "b", (0.0, 3000.0, 0.0),
                  ["eb"], [(0.0, 3150.0, 0.0)])
    c, sc = _wing(pSet, "c", "enemy", "c", (0.0, -3000.0, 0.0),
                  ["ec"], [(0.0, -3150.0, 0.0)])
    return a, b, c, {**sa, **sb, **sc}


def test_status_after_led_tick(now):
    a, _b, _c, _ships = _two_sides()
    brain.tick_wing(a)
    s = a.status
    assert s is not None
    assert s.wing_id == "a" and s.side == "friendly"
    assert s.engaged is True
    assert s.anchor == pytest.approx((0.0, 0.0, 0.0), abs=1.0)
    assert s.ours > 0 and s.theirs > 0
    assert s.enemy_centroid is not None
    assert s.decision == a.decision
    assert 0.0 < s.strength_frac <= 1.0 + 1e-6


def test_status_not_engaged_without_enemy_near(now):
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    w, _ = _wing(pSet, "a", "friendly", "a", (0.0, 0.0, 0.0),
                 ["ea"], [(5000.0, 0.0, 0.0)])
    brain.tick_wing(w)
    assert w.status.engaged is False
    assert w.status.enemy_centroid is None


def test_leaderless_clears_status(now):
    a, _b, _c, ships = _two_sides()
    brain.tick_wing(a)
    assert a.status is not None
    ships[a.commander].SetDead()
    a.chain = [a.commander]
    now[0] = 1.0
    brain.tick_wing(a)
    assert a.leaderless is True
    assert a.status is None


def test_command_away_clears_status(now):
    a, _b, _c, ships = _two_sides()
    brain.tick_wing(a)
    assert a.status is not None
    cmd = a.commander
    a.chain = [cmd]
    ships[cmd].GetContainingSet().RemoveObjectFromSet(cmd)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships[cmd], cmd)
    now[0] = 1.0
    brain.tick_wing(a)
    assert a.away is True
    assert a.status is None


def test_context_allies_same_side_only(now, monkeypatch):
    a, b, c, _ships = _two_sides()
    seen = {}
    real = decisions.pick

    def spy(ctx):
        seen[ctx.anchor.name] = ctx.allies
        return real(ctx)
    monkeypatch.setattr(decisions, "pick", spy)
    brain.tick_wing(a)
    brain.tick_wing(b)
    brain.tick_wing(c)
    now[0] = 1.0
    brain.tick_wing(a)
    brain.tick_wing(c)
    assert [s.wing_id for s in seen["a1"]] == ["b"]
    assert seen["c1"] == ()
