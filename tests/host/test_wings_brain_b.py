"""Wing brain glue, Phase B (spec 2026-11-09-wing-leaders-phase-b-design.md
§2-§5): strength history and damage rates, protect with body-blocking
guards, damaged ships falling back, and withdraw with its cooldown.

Headless against real loadspacehelper ships in a fresh set, built like
tests/host/test_wings_brain.py."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import (  # noqa: E402
    assess, brain, decisions, dials, protect, roster, rotate)

_KINDS = ("withdraw", "guard", "fallback", "rejoin")


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        roster.reset()
        dials.reset()
        decisions.reset_registry()
        brain.reset_cache()
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


def _scene(enemy_xyz, n_members=3, member_xyz=None):
    """Akira members m1.. (m1 commands; default 20 GU apart along -x) and
    Bird of Prey enemies e1.. at the given offsets. Every member gets real
    TGConditions for the wing branches."""
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
        ships[name] = _ship(pSet, "BirdOfPrey", name, xyz)
        group.AddName(name)
    wing = roster.create_wing("blue", group)
    for i in range(1, n_members + 1):
        m = roster.add_member(wing, "m%d" % i)
        m.conditions.update({k: App.TGCondition() for k in _KINDS})
    brain.arm_chain(wing)
    return wing, ships


def _status(name, kind):
    return roster.member(name).conditions[kind].GetStatus()


def _group(wing):
    return {n: wing.target_group[n]["Priority"]
            for n in wing.target_group.GetNameTuple()}


def _set_shields(ship, frac):
    shields = ship.GetShields()
    for i in range(6):
        shields.SetCurShields(i, frac * shields.GetMaxShields(i))


def _spy_ctx(monkeypatch):
    seen = []
    real = decisions.pick

    def spy(ctx):
        seen.append(ctx)
        return real(ctx)
    monkeypatch.setattr(decisions, "pick", spy)
    return seen


def _on_segment(p, a, b, tol=1e-6):
    ab, ap, pb = assess.dist(a, b), assess.dist(a, p), assess.dist(p, b)
    return abs(ap + pb - ab) <= tol and 0.0 < ap < ab


# ── seeing: targets, history, armed strength ───────────────────────────────

def test_view_of_fills_target():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    a = _ship(pSet, "Akira", "a", (0.0, 0.0, 0.0))
    _ship(pSet, "BirdOfPrey", "b", (100.0, 0.0, 0.0))
    assert brain.view_of(a).target is None
    a.SetTarget("b")
    assert brain.view_of(a).target == "b"


def test_arm_sets_armed_strength():
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    want = sum(assess.strength(brain.view_of(ships[n]))
               for n in ("m1", "m2", "m3"))
    assert want > 0.0
    assert wing.armed_strength == pytest.approx(want)


def test_history_and_rate(monkeypatch, now):
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    seen = _spy_ctx(monkeypatch)
    m2 = roster.member("m2")
    brain.tick_wing(wing)
    full = assess.strength(brain.view_of(ships["m2"]))
    assert m2.strength_hist == [(0.0, pytest.approx(full))]
    now[0] = 1.0
    ships["m2"].GetHull().SetConditionPercentage(0.5)
    brain.tick_wing(wing)
    assert len(m2.strength_hist) == 2
    assert seen[-1].rates["m2"] == pytest.approx(0.5)
    assert seen[-1].rates["m1"] == pytest.approx(0.0)
    assert seen[-1].now == 1.0
    assert seen[-1].armed_strength == pytest.approx(wing.armed_strength)
    # Samples older than the window are trimmed: the loss leaves the rate.
    now[0] = 1.0 + dials.get("heavy_fire_window_s") - 0.5   # t=0 out
    brain.tick_wing(wing)
    assert [t for t, _s in m2.strength_hist] == [1.0, now[0]]
    assert seen[-1].rates["m2"] == pytest.approx(0.0)


def test_protectees_are_members_plus_protect_names(monkeypatch, now):
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    pSet = ships["m1"].GetContainingSet()
    ships["p1"] = _ship(pSet, "Akira", "p1", (-60.0, 0.0, 0.0))
    wing.protect_names = lambda: ("p1", "m2", "nobody")
    seen = _spy_ctx(monkeypatch)
    brain.tick_wing(wing)
    names = [p.name for p in seen[-1].protectees]
    assert sorted(names) == ["m1", "m2", "m3", "p1"]


# ── protect: guards body-block ─────────────────────────────────────────────

def _protect_scene():
    """m2 (the protectee, 40 GU behind m1) is targeted by three enemies;
    m3 is the healthy member nearest it."""
    wing, ships = _scene([(150.0, 0.0, 0.0), (160.0, 30.0, 0.0),
                          (170.0, -30.0, 0.0)],
                         member_xyz=[(0.0, 0.0, 0.0), (-40.0, 0.0, 0.0),
                                     (-30.0, 20.0, 0.0)])
    for e in ("e1", "e2", "e3"):
        ships[e].SetTarget("m2")
    return wing, ships


def test_protect_assigns_guard_between(now):
    wing, ships = _protect_scene()
    brain.tick_wing(wing)
    assert wing.decision == "protect"
    m3 = roster.member("m3")
    assert m3.guard is True and _status("m3", "guard") == 1
    m2pos = brain.view_of(ships["m2"]).pos
    e1pos = brain.view_of(ships["e1"]).pos      # nearest attacker to m2
    assert m3.move_point == pytest.approx(protect.guard_point(m2pos, e1pos))
    assert _on_segment(m3.move_point, m2pos, e1pos)
    assert _group(wing)["e1"] == 3.0
    # Never the commander, never the protectee.
    for n in ("m1", "m2"):
        assert roster.member(n).guard is False and _status(n, "guard") == 0
        assert roster.member(n).move_point is None


def test_guard_released_when_protectee_dies(now):
    wing, ships = _protect_scene()
    brain.tick_wing(wing)
    assert roster.member("m3").guard is True
    ships["m2"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    m3 = roster.member("m3")
    assert m3.guard is False and _status("m3", "guard") == 0
    assert m3.move_point is None


def test_protect_names_ship_is_protected_but_never_pushed(now):
    """A protect ship (or the player) is covered, but is no member: no
    move point, no push, never a guard."""
    wing, ships = _scene([(150.0, 0.0, 0.0), (160.0, 30.0, 0.0),
                          (170.0, -30.0, 0.0)])
    pSet = ships["m1"].GetContainingSet()
    ships["p1"] = _ship(pSet, "Akira", "p1", (-50.0, 0.0, 0.0))
    for e in ("e1", "e2", "e3"):
        ships[e].SetTarget("p1")
    wing.protect_names = lambda: ("p1",)
    brain.tick_wing(wing)
    assert wing.decision == "protect"
    assert roster.member("p1") is None
    guards = [n for n in ("m1", "m2", "m3") if roster.member(n).guard]
    assert guards == ["m3"]                      # nearest p1, not m1


# ── rotate: damaged ships fall back ────────────────────────────────────────

def test_fallback_moves_behind_and_returns(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_shields(ships["m2"], 0.1)
    brain.tick_wing(wing)
    m2 = roster.member("m2")
    assert m2.fallback_since == 0.0 and _status("m2", "fallback") == 1
    anchor = brain.view_of(ships["m1"]).pos
    e1pos = brain.view_of(ships["e1"]).pos
    want = rotate.fallback_point(anchor, e1pos,
                                 dials.get("regroup_gather_gu"))
    assert m2.move_point == pytest.approx(want)
    assert m2.move_point[0] < anchor[0]          # behind, away from e1
    # Shields restored: back into the fight.
    _set_shields(ships["m2"], 0.7)
    now[0] = 1.0
    brain.tick_wing(wing)
    assert m2.fallback_since is None and _status("m2", "fallback") == 0
    assert m2.move_point is None


def test_fallback_never_commander_and_not_without_enemies(now):
    wing, ships = _scene([(900.0, 0.0, 0.0)])      # out of reach
    _set_shields(ships["m1"], 0.1)
    _set_shields(ships["m2"], 0.1)
    brain.tick_wing(wing)
    for n in ("m1", "m2"):
        assert roster.member(n).fallback_since is None
        assert _status(n, "fallback") == 0
    ships["e1"].SetTranslateXYZ(150.0, 0.0, 0.0)  # now in reach
    now[0] = 1.0
    brain.tick_wing(wing)
    assert roster.member("m1").fallback_since is None   # the commander
    assert _status("m2", "fallback") == 1
    ships["e1"].SetTranslateXYZ(900.0, 0.0, 0.0)  # gone again: all back
    now[0] = 2.0
    brain.tick_wing(wing)
    assert roster.member("m2").fallback_since is None
    assert _status("m2", "fallback") == 0
    assert roster.member("m2").move_point is None


# ── withdraw ───────────────────────────────────────────────────────────────

def _withdraw_scene():
    """A 2-ship wing at 0.3 hull against 8 enemies close by."""
    enemies = [(120.0 + 10.0 * i, 10.0 * (i % 3), 0.0) for i in range(8)]
    wing, ships = _scene(enemies, n_members=2)
    for n in ("m1", "m2"):
        ships[n].GetHull().SetConditionPercentage(0.3)
    return wing, ships


def test_withdraw_enters_and_cools_down(now):
    wing, ships = _withdraw_scene()
    now[0] = 5.0
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    assert wing.withdraw_since == 5.0
    assert _group(wing) == {}
    m1, m2 = roster.member("m1"), roster.member("m2")
    # Every member withdraws on its own line away from the enemy, and
    # nobody rejoins (ruling 2026-11-09, fix round 1).
    assert _status("m1", "withdraw") == 1 and _status("m2", "withdraw") == 1
    assert _status("m1", "rejoin") == 0 and _status("m2", "rejoin") == 0
    assert not m1.rejoin and not m2.rejoin
    cen = assess.centroid([brain.view_of(ships["e%d" % i])
                           for i in range(1, 9)])
    step = dials.get("withdraw_step_gu")
    for n, m in (("m1", m1), ("m2", m2)):
        own = brain.view_of(ships[n]).pos
        assert m.move_point == pytest.approx(
            rotate.fallback_point(own, cen, step))
    # Enemies still close: not clear.
    now[0] = 6.0
    brain.tick_wing(wing)
    assert wing.clear_since is None and wing.withdraw_since == 5.0
    # withdraw_max_s elapses: it ends and the cooldown starts.
    now[0] = 5.0 + dials.get("withdraw_max_s")
    brain.tick_wing(wing)
    assert wing.decision != "withdraw"
    assert wing.withdraw_since is None and wing.clear_since is None
    assert wing.withdraw_cooldown_until == pytest.approx(
        now[0] + dials.get("withdraw_cooldown_s"))
    assert _status("m1", "withdraw") == 0 and m1.move_point is None
    assert _status("m2", "withdraw") == 0 and m2.move_point is None
    # Inside the cooldown it does not come back.
    now[0] += 1.0
    brain.tick_wing(wing)
    assert wing.decision != "withdraw" and wing.withdraw_since is None


def test_withdraw_tracks_clear_since_and_ends_when_clear(now):
    wing, ships = _withdraw_scene()
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    for i in range(1, 9):
        ships["e%d" % i].SetTranslateXYZ(2000.0 + i, 0.0, 0.0)
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.clear_since == 1.0 and wing.decision == "withdraw"
    now[0] = 1.0 + dials.get("withdraw_clear_s")
    brain.tick_wing(wing)
    assert wing.decision != "withdraw" and wing.withdraw_since is None


def test_withdraw_skips_fallback(now):
    wing, ships = _withdraw_scene()
    _set_shields(ships["m2"], 0.1)
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    assert roster.member("m2").fallback_since is None
    assert _status("m2", "fallback") == 0


# ── stand-down ─────────────────────────────────────────────────────────────

def _all_on(wing):
    for m in wing.members.values():
        m.move_point = (1.0, 2.0, 3.0)
        m.guard = True
        m.fallback_since = 0.0
        for k in ("withdraw", "guard", "fallback"):
            m.conditions[k].SetStatus(1)


def _assert_stood_down(wing):
    for name, m in wing.members.items():
        assert m.move_point is None and m.guard is False
        assert m.fallback_since is None
        for k in ("withdraw", "guard", "fallback"):
            assert m.conditions[k].GetStatus() == 0, (name, k)


def test_new_branches_stand_down_when_leaderless_or_away(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    wing.withdraw_since, wing.clear_since = 0.0, 0.0
    _all_on(wing)
    ships["m1"].SetDead()                         # the whole chain
    now[0] = 2.0
    brain.tick_wing(wing)
    assert wing.leaderless is True
    _assert_stood_down(wing)
    assert wing.withdraw_since is None and wing.clear_since is None

    App.g_kSetManager._sets.clear()
    roster.reset()
    brain.reset_cache()
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _all_on(wing)
    name = "m1"
    ships[name].GetContainingSet().RemoveObjectFromSet(name)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships[name], name)        # command away (a warp)
    now[0] = 3.0
    brain.tick_wing(wing)
    assert wing.away is True
    _assert_stood_down(wing)


# ── fix round 1 ────────────────────────────────────────────────────────────

def test_current_faller_is_never_picked_as_guard(now):
    """m3 is already falling back (shields 0.22, hull 1.0: strength frac
    0.61, guard-eligible on health alone) and nearest the threatened m2:
    m4 guards instead and m3 keeps falling back."""
    wing, ships = _scene([(150.0, 0.0, 0.0), (160.0, 30.0, 0.0),
                          (170.0, -30.0, 0.0)], n_members=4,
                         member_xyz=[(0.0, 0.0, 0.0), (-40.0, 0.0, 0.0),
                                     (-30.0, 20.0, 0.0), (-80.0, -30.0, 0.0)])
    _set_shields(ships["m3"], 0.22)
    brain.tick_wing(wing)                    # nobody attacked yet
    m3 = roster.member("m3")
    assert m3.fallback_since == 0.0
    for e in ("e1", "e2", "e3"):
        ships[e].SetTarget("m2")
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.decision == "protect"
    assert m3.guard is False and _status("m3", "guard") == 0
    assert m3.fallback_since == 0.0 and _status("m3", "fallback") == 1
    assert roster.member("m4").guard is True


def test_guard_released_when_attacker_dies(now):
    wing, ships = _protect_scene()
    brain.tick_wing(wing)
    assert roster.member("m3").guard is True
    ships["e1"].SetDead()                    # the primary attacker
    now[0] = 1.0
    brain.tick_wing(wing)
    m3 = roster.member("m3")
    assert m3.guard is False and _status("m3", "guard") == 0
    assert m3.move_point is None


def _player_member(wing, ships, name, xyz, hull=1.0):
    pSet = ships["m1"].GetContainingSet()
    ships[name] = _ship(pSet, "Akira", name, xyz)
    ships[name].GetHull().SetConditionPercentage(hull)
    m = roster.add_member(wing, name, is_player=True)
    m.conditions.update({k: App.TGCondition() for k in _KINDS})
    return m


def test_player_member_never_guards_moves_or_is_pushed(monkeypatch, now):
    """Library path: a player member nearest the threatened ship, healthy
    then shield-less, is never a guard or faller and gets no push."""
    wing, ships = _protect_scene()
    p = _player_member(wing, ships, "p", (-45.0, 5.0, 0.0))
    wing.chain = ["m1"]                      # the player does not command
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["p"])
    for k in ("withdraw", "guard", "fallback"):
        p.conditions[k].SetStatus(1)         # any push would show as 0
    brain.tick_wing(wing)
    assert wing.decision == "protect"
    assert roster.member("m3").guard is True
    _set_shields(ships["p"], 0.1)
    now[0] = 1.0
    brain.tick_wing(wing)
    assert p.guard is False and p.move_point is None
    assert p.fallback_since is None
    for k in ("withdraw", "guard", "fallback"):
        assert p.conditions[k].GetStatus() == 1, k


def test_withdraw_ends_when_the_player_takes_command(monkeypatch, now):
    """Library path: a withdrawing wing whose commander becomes the player
    stops withdrawing (Withdraw never applies to a player-led wing)."""
    enemies = [(120.0 + 10.0 * i, 10.0 * (i % 3), 0.0) for i in range(8)]
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {}
    group = App.ObjectGroup()
    wing = roster.create_wing("blue", group)
    for name, xyz, player in (("m1", (0.0, 0.0, 0.0), False),
                              ("m2", (-20.0, 0.0, 0.0), False),
                              ("p", (-40.0, 0.0, 0.0), True)):
        ships[name] = _ship(pSet, "Akira", name, xyz)
        m = roster.add_member(wing, name, is_player=player)
        m.conditions.update({k: App.TGCondition() for k in _KINDS})
    for i, xyz in enumerate(enemies, 1):
        ships["e%d" % i] = _ship(pSet, "BirdOfPrey", "e%d" % i, xyz)
        group.AddName("e%d" % i)
    brain.arm_chain(wing)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["p"])
    for n in ("m1", "m2", "p"):
        ships[n].GetHull().SetConditionPercentage(0.3)
    wing.chain = ["m1"]
    brain.tick_wing(wing)
    assert wing.decision == "withdraw" and wing.withdraw_since == 0.0
    assert _status("m1", "withdraw") == 1 and _status("m2", "withdraw") == 1
    assert _status("p", "withdraw") == 0          # the player is never pushed
    assert roster.member("p").move_point is None
    wing.chain = ["p", "m1"]                 # the player takes command
    now[0] = 2.0
    brain.tick_wing(wing)
    assert wing.commander == "p"
    assert wing.decision != "withdraw"
    assert wing.withdraw_since is None and wing.clear_since is None
    assert wing.withdraw_cooldown_until == pytest.approx(
        2.0 + dials.get("withdraw_cooldown_s"))
    assert _status("m1", "withdraw") == 0 and _status("m2", "withdraw") == 0
    assert roster.member("m1").move_point is None
    assert roster.member("m2").move_point is None


def test_withdraw_ends_when_odds_recover(now):
    wing, ships = _withdraw_scene()
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    for i in range(2, 9):                    # seven enemies die; e1 stays near
        ships["e%d" % i].SetDead()
    engage = dials.get("engage_gu")
    anchor = brain.view_of(ships["m1"]).pos
    ours = assess.side_strength([brain.view_of(ships[n])
                                 for n in ("m1", "m2")], anchor, engage)
    theirs = assess.side_strength([brain.view_of(ships[n])
                                   for n in ("e1",)], anchor, engage)
    assert theirs > 0.0
    assert ours >= 1.5 * dials.get("withdraw_odds") * theirs
    now[0] = 3.0
    brain.tick_wing(wing)
    assert wing.decision != "withdraw" and wing.withdraw_since is None
    assert wing.withdraw_cooldown_until == pytest.approx(
        3.0 + dials.get("withdraw_cooldown_s"))
    assert _status("m1", "withdraw") == 0 and _status("m2", "withdraw") == 0
