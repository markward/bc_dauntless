"""Wing reserve (spec 2026-11-09-wing-leaders-phase-c-design.md §6): a wing
of reserve_min_wing+ live non-player members holds its healthiest
non-commander back behind the commander, away from the enemy, and commits it
permanently -- once -- when the fight tips (a member dies, Protect, the
primary nearly dead, 2x advantage in reach, reserve_max_s) or command goes.

Headless against real loadspacehelper ships with wrapped BasicAttack trees,
the brain ticked directly (tests/host/test_wings_brain_c.py's scene)."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import (  # noqa: E402
    assess, brain, dials, reserve, roster, service, tree)


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


def _scene(enemy_xyz, n_members=5, member_xyz=None, enemy_kind="Warbird"):
    """Akira members m1.. (m1 commands; 20 GU apart along -x) with wrapped
    BasicAttack trees, enemies e1.. at the given offsets. Two Warbirds in
    reach (3000) against five Akiras (4000) is no 2x advantage."""
    import AI.Compound.BasicAttack
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {}
    for i in range(1, n_members + 1):
        xyz = (member_xyz[i - 1] if member_xyz
               else (-20.0 * (i - 1), 0.0, 0.0))
        ships["m%d" % i] = _ship(pSet, "Akira", "m%d" % i, xyz)
    group = App.ObjectGroup()
    for i, xyz in enumerate(enemy_xyz, 1):
        name = "e%d" % i
        ships[name] = _ship(pSet, enemy_kind, name, xyz)
        group.AddName(name)
    wing = roster.create_wing("blue", group)
    for i in range(1, n_members + 1):
        roster.add_member(wing, "m%d" % i)
    for i in range(1, n_members + 1):
        s = ships["m%d" % i]
        stock = AI.Compound.BasicAttack.CreateAI(s, wing.target_group,
                                                 Difficulty=0.5)
        s.SetAI(tree.wrap_tree(s, stock, wing))
    brain.arm_chain(wing)
    return wing, ships


_HELD = [(150.0, 0.0, 0.0), (160.0, 30.0, 0.0)]      # two Warbirds in reach
_FAR = [(900.0, 0.0, 0.0)]                           # out of engage_gu


def _status(name, kind):
    return roster.member(name).conditions[kind].GetStatus()


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _spent(wing):
    assert wing.reserve is None and wing.reserve_spent is True
    for m in wing.members.values():
        assert m.reserve is False
    for n in wing.members:
        assert _status(n, "reserve") == 0


# ── who ────────────────────────────────────────────────────────────────────

def test_reserve_picked_in_wing_of_five(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_HELD)
    assert wing.commander == "m1"
    assert wing.reserve == "m2"           # all equal: lowest power, then name
    assert wing.reserve_since == 0.0
    assert wing.reserve_spent is False
    assert wing.reserve_live == 5
    assert roster.member("m2").reserve is True
    assert [n for n, m in wing.members.items() if m.reserve] == ["m2"]
    assert "[wings] blue reserve m2" in capsys.readouterr().err.splitlines()


def test_reserve_is_the_healthiest_non_commander(now):
    wing, ships = _scene(_HELD, n_members=6)
    # Undo the scene's pick, then re-arm with m4 the only untouched hull.
    wing.reserve = None
    for m in wing.members.values():
        m.reserve = False
    for n in ("m2", "m3", "m5", "m6"):
        ships[n].GetHull().SetConditionPercentage(0.7)
    brain.arm_chain(wing)
    assert wing.reserve == "m4"
    assert [n for n, m in wing.members.items() if m.reserve] == ["m4"]


def test_no_reserve_in_wing_of_four(now):
    wing, ships = _scene(_HELD, n_members=4)
    assert wing.reserve is None and wing.reserve_spent is False
    brain.tick_wing(wing)
    assert not any(m.reserve for m in wing.members.values())
    for n in wing.members:
        assert _status(n, "reserve") == 0


# ── where ──────────────────────────────────────────────────────────────────

def test_reserve_holds_behind_commander(now):
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    m2 = roster.member("m2")
    anchor = _pos(ships["m1"])
    centroid = assess.centroid([brain.view_of(ships[e]) for e in ("e1", "e2")])
    gu = dials.get("reserve_gu")
    # reserve_gu past the commander's range, on the reserve's own bearing
    # (Task 6: the commander's bearing swept faster than the ship).
    assert m2.move_point == pytest.approx(
        reserve.hold_point(anchor, _pos(ships["m2"]), centroid, gu))
    assert (assess.dist(m2.move_point, centroid)
            == pytest.approx(assess.dist(anchor, centroid) + gu))
    assert _status("m2", "reserve") == 1
    for kind in ("attack", "guard", "fallback", "withdraw", "rejoin"):
        assert _status("m2", kind) == 0, kind
    assert m2.slot is None and m2.guard is False
    assert m2.fallback_since is None and m2.rejoin is False
    # Recomputed each tick: the enemy moves, the point follows.
    ships["e1"].SetTranslateXYZ(0.0, 150.0, 0.0)
    ships["e2"].SetTranslateXYZ(30.0, 160.0, 0.0)
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    assert m2.move_point[1] < anchor[1] - 0.5 * gu


def test_reserve_never_guards_or_falls_back(now):
    """A reserve with low shields is no faller, and no guard either."""
    wing, ships = _scene(_HELD)
    shields = ships["m2"].GetShields()
    for i in range(6):
        shields.SetCurShields(i, 0.1 * shields.GetMaxShields(i))
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    m2 = roster.member("m2")
    assert m2.fallback_since is None and _status("m2", "fallback") == 0
    assert m2.guard is False and _status("m2", "reserve") == 1


def test_reserve_holds_at_anchor_with_no_enemy_ever(now):
    wing, ships = _scene(_FAR)
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    assert roster.member("m2").move_point == pytest.approx(_pos(ships["m1"]))
    assert _status("m2", "reserve") == 1


def test_reserve_uses_last_centroid_when_enemies_leave(now):
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    first = roster.member("m2").move_point
    for e in ("e1", "e2"):
        ships[e].SetTranslateXYZ(2000.0, 0.0, 0.0)
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    assert roster.member("m2").move_point == pytest.approx(first)


# ── commits ────────────────────────────────────────────────────────────────

def test_reserve_commits_on_member_death(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    ships["m3"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    _spent(wing)
    assert "[wings] blue reserve commits (loss)" in \
        capsys.readouterr().err.splitlines()


def test_reserve_commits_on_protect(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene([(150.0, 0.0, 0.0), (160.0, 30.0, 0.0),
                          (170.0, -30.0, 0.0)], enemy_kind="BirdOfPrey")
    for e in ("e1", "e2", "e3"):
        ships[e].SetTarget("m3")
    brain.tick_wing(wing)
    assert wing.decision == "protect"
    _spent(wing)
    assert "[wings] blue reserve commits (protect)" in \
        capsys.readouterr().err.splitlines()


def test_reserve_commits_on_weak_primary(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    assert wing.reserve == "m2" and wing.primary is not None
    ships[wing.primary].GetHull().SetConditionPercentage(0.2)
    now[0] = 1.0
    brain.tick_wing(wing)
    _spent(wing)
    assert "[wings] blue reserve commits (finish)" in \
        capsys.readouterr().err.splitlines()


def test_reserve_commits_on_advantage(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene([(150.0, 0.0, 0.0)], enemy_kind="BirdOfPrey")
    brain.tick_wing(wing)
    _spent(wing)
    assert "[wings] blue reserve commits (advantage)" in \
        capsys.readouterr().err.splitlines()


def test_reserve_commits_on_timeout(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_FAR)
    brain.tick_wing(wing)
    now[0] = dials.get("reserve_max_s") - 1.0
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    now[0] = dials.get("reserve_max_s") + 1.0
    brain.tick_wing(wing)
    _spent(wing)
    assert "[wings] blue reserve commits (timeout)" in \
        capsys.readouterr().err.splitlines()


def test_reserve_commits_when_it_takes_command(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_HELD)
    wing.chain = ["m1", "m2"]
    brain.tick_wing(wing)
    assert wing.reserve == "m2"
    ships["m1"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.commander == "m2"
    _spent(wing)
    assert "[wings] blue reserve commits (command)" in \
        capsys.readouterr().err.splitlines()


def test_dead_reserve_is_spent(now):
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    ships["m2"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.reserve is None and wing.reserve_spent is True


def test_reserve_never_repicked_after_commit(now):
    """Committed with all five alive (timeout), so a re-arm -- as a late
    wave's arrival does -- would pick again but for reserve_spent."""
    wing, ships = _scene(_FAR)
    brain.tick_wing(wing)
    now[0] = dials.get("reserve_max_s") + 1.0
    brain.tick_wing(wing)
    _spent(wing)
    service.arm(wing)
    assert wing.reserve is None and wing.reserve_spent is True
    assert not any(m.reserve for m in wing.members.values())
    now[0] += 1.0
    brain.tick_wing(wing)
    _spent(wing)


def test_split_set_arm_is_no_loss(now):
    """A member outside the home set at arming is not counted, so the first
    led tick does not read it as a loss."""
    wing, ships = _scene(_HELD, n_members=6)
    ships["m6"].GetContainingSet().RemoveObjectFromSet("m6")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships["m6"], "m6")
    brain.arm_chain(wing)
    assert wing.reserve == "m2" and wing.reserve_live == 5
    brain.tick_wing(wing)
    assert wing.reserve == "m2" and wing.reserve_spent is False


def test_rearm_keeps_a_held_reserve(now):
    wing, ships = _scene(_HELD)
    now[0] = 5.0
    brain.arm_chain(wing)
    assert wing.reserve == "m2" and wing.reserve_since == 0.0


def test_reserve_no_advantage_commit_without_enemies(now):
    """Five Akiras against one Bird of Prey is 10x -- but nothing is in
    reach, so the reserve is held (review focus 4)."""
    wing, ships = _scene(_FAR, enemy_kind="BirdOfPrey")
    for t in range(20):
        now[0] = float(t)
        brain.tick_wing(wing)
        assert wing.reserve == "m2", t
        assert _status("m2", "reserve") == 1
    assert wing.reserve_spent is False


# ── withdraw and stand-down ────────────────────────────────────────────────

def test_reserve_withdraws_with_the_wing(now):
    enemies = [(120.0 + 10.0 * i, 10.0 * (i % 3), 0.0) for i in range(8)]
    wing, ships = _scene(enemies, enemy_kind="BirdOfPrey")
    for i in range(1, 6):
        ships["m%d" % i].GetHull().SetConditionPercentage(0.3)
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    assert wing.reserve == "m2"                    # still held
    assert roster.member("m2").reserve is True
    assert _status("m2", "withdraw") == 1
    assert _status("m2", "reserve") == 0
    assert roster.member("m2").slot is None


def test_reserve_returns_after_withdraw_ends(now):
    enemies = [(120.0 + 10.0 * i, 10.0 * (i % 3), 0.0) for i in range(8)]
    wing, ships = _scene(enemies, enemy_kind="BirdOfPrey")
    for i in range(1, 6):
        ships["m%d" % i].GetHull().SetConditionPercentage(0.3)
    brain.tick_wing(wing)
    assert wing.decision == "withdraw" and _status("m2", "reserve") == 0
    for i in range(1, 9):
        ships["e%d" % i].SetTranslateXYZ(2000.0 + i, 0.0, 0.0)
    now[0] = 1.0
    brain.tick_wing(wing)
    now[0] = 1.0 + dials.get("withdraw_clear_s")
    brain.tick_wing(wing)
    assert wing.withdraw_since is None and wing.decision != "withdraw"
    assert wing.reserve == "m2"
    assert _status("m2", "reserve") == 1
    assert _status("m2", "withdraw") == 0
    m2 = roster.member("m2")
    anchor = _pos(ships["m1"])
    assert m2.move_point == pytest.approx(reserve.hold_point(
        anchor, _pos(ships["m2"]), wing.last_centroid,
        dials.get("reserve_gu")))


def test_stand_down_without_a_reserve_still_spends_it(now):
    """A wing that lost command never holds a reserve, even if re-armed."""
    wing, ships = _scene(_HELD)
    wing.reserve = None                       # as if nothing was picked
    for m in wing.members.values():
        m.reserve = False
    ships["m1"].SetDead()
    wing.chain = ["m1"]
    brain.tick_wing(wing)
    assert wing.leaderless is True and wing.reserve_spent is True
    service.arm(wing)
    assert wing.reserve is None
    assert not any(m.reserve for m in wing.members.values())


def test_leaderless_commits_reserve(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    assert _status("m2", "reserve") == 1
    ships["m1"].SetDead()                          # the whole chain
    wing.chain = ["m1"]
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.leaderless is True
    _spent(wing)
    assert roster.member("m2").move_point is None
    assert "[wings] blue reserve commits (leaderless)" in \
        capsys.readouterr().err.splitlines()


def test_command_away_commits_reserve(now):
    wing, ships = _scene(_HELD)
    brain.tick_wing(wing)
    wing.chain = ["m1"]
    ships["m1"].GetContainingSet().RemoveObjectFromSet("m1")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships["m1"], "m1")
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.away is True
    _spent(wing)
