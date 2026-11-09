"""Wing brain glue, Phase D (spec 2026-11-09-wing-leaders-phase-d-design.md
§4-§6): the brain fills the reinforce / feint / flank latches and cooldowns
into the Context, keeps them on the wing across ticks, and applies a hold
decision (screen, flank, feint) as the hold branch: every non-player member,
the commander included, on a formation point round the hold point, every
other move / attack / rejoin branch off, the reserve held but moving with
the formation.

Headless against real loadspacehelper ships with wrapped BasicAttack trees
(tests/host/test_wings_allies.py's two-wing scenes, 3+ members so command
can go away), the brain ticked directly; the reinforce sim steps the real
GameLoop with both wings armed on the service."""
import math

import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import (  # noqa: E402
    allies, attack, brain, decisions, dials, roster, service, tree)

_OFF = ("withdraw", "guard", "fallback", "reserve", "attack", "rejoin")
_KINDS = ("withdraw", "hold", "guard", "fallback", "reserve", "attack",
          "rejoin", "ram", "flee")
# A player member is never pushed these (rejoin is pushed off for every
# member by the Phase A rejoin pass: not a move).
_PLAYER_KINDS = tuple(k for k in _KINDS if k != "rejoin")


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


def _set():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    return pSet


def _enemies(pSet, specs, kind="Warbird"):
    """Enemy ships (no AI: they hold still) in one group both wings share.
    A spec is (name, xyz) or (name, xyz, kind)."""
    group = App.ObjectGroup()
    ships = {}
    for name, xyz, *k in specs:
        ships[name] = _ship(pSet, k[0] if k else kind, name, xyz)
        group.AddName(name)
    return group, ships


def _wing(pSet, wid, origin, group, n=3, side="friendly"):
    """Akira members <wid>1.. (1 commands; 20 GU apart along -x from
    origin) with wrapped BasicAttack trees against the shared group."""
    import AI.Compound.BasicAttack
    wing = roster.create_wing(wid, group)
    wing.side = side
    ships = {}
    for i in range(1, n + 1):
        name = "%s%d" % (wid, i)
        ships[name] = _ship(pSet, "Akira", name,
                            (origin[0] - 20.0 * (i - 1), origin[1], origin[2]))
        roster.add_member(wing, name)
    for name, s in ships.items():
        s.SetAI(tree.wrap_tree(s, AI.Compound.BasicAttack.CreateAI(
            s, wing.target_group, Difficulty=0.5), wing))
    brain.arm_chain(wing)
    return wing, ships


def _status(name, kind):
    return roster.member(name).conditions[kind].GetStatus()


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _close(a, b, tol=1e-3):
    return a is not None and all(abs(x - y) < tol for x, y in zip(a, b))


def _group(wing):
    return {n: wing.target_group[n]["Priority"]
            for n in wing.target_group.GetNameTuple()}


def _spy(monkeypatch):
    seen = {}
    real = decisions.pick

    def spy(ctx):
        seen[ctx.anchor.name] = ctx
        return real(ctx)
    monkeypatch.setattr(decisions, "pick", spy)
    return seen


def _assert_hold(wing, ships, hold_point, toward, names=None):
    """Every (live) non-player member on "hold" at its formation point
    (the commander at the centre), every other branch off, no slot."""
    if names is None:
        names = [n for n, m in wing.members.items() if not m.is_player]
    pts = allies.formation_points(hold_point, toward, len(names),
                                  dials.get("hold_spread_gu"))
    assert _close(roster.member(wing.commander).move_point, pts[0])
    got = []
    for n in names:
        m = roster.member(n)
        assert _status(n, "hold") == 1, n
        for k in _OFF:
            assert _status(n, k) == 0, (n, k)
        assert m.slot is None and m.guard is False
        assert m.fallback_since is None and m.rejoin is False
        got.append(next(i for i, p in enumerate(pts)
                        if _close(m.move_point, p)))
    assert sorted(got) == list(range(len(names)))


# ── reinforce ──────────────────────────────────────────────────────────────

def _reinforce_scene():
    """b (2400) fights two Warbirds (3000) at the origin: in trouble. a sits
    idle 1000 GU off, nothing near it."""
    pSet = _set()
    group, es = _enemies(pSet, [("w1", (150.0, 0.0, 0.0)),
                                ("w2", (160.0, 30.0, 0.0))])
    a, sa = _wing(pSet, "a", (0.0, 1000.0, 0.0), group)
    b, sb = _wing(pSet, "b", (0.0, 0.0, 0.0), group)
    return a, b, {**es, **sa, **sb}


def test_reinforce_writes_far_primary(now):
    a, b, _ships = _reinforce_scene()
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "reinforce"
    assert _group(a) == {"w1": 3.0, "w2": 1.5}
    assert a.reinforce_ally == "b" and a.decision_since == 0.0
    # Reinforce is no hold: nobody on the hold branch.
    for n in a.members:
        assert _status(n, "hold") == 0


def test_reinforce_latch_survives_a_tick(monkeypatch, now):
    a, b, _ships = _reinforce_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)
    brain.tick_wing(a)
    now[0] = 1.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    ctx = seen["a1"]
    assert ctx.current == "reinforce" and ctx.reinforce_ally == "b"
    assert ctx.decision_age_s == pytest.approx(1.0)
    assert a.decision == "reinforce"
    assert a.reinforce_ally == "b" and a.decision_since == 0.0


def test_reinforce_cap_puts_ally_on_cooldown(monkeypatch, now):
    a, b, _ships = _reinforce_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)
    brain.tick_wing(a)
    now[0] = 90.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].decision_age_s == pytest.approx(90.0)
    assert a.decision != "reinforce"
    assert a.reinforce_ally is None
    assert a.reinforce_done == {"b": pytest.approx(150.0)}
    now[0] = 91.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].reinforce_done == frozenset({"b"})
    assert a.decision != "reinforce"
    # The cooldown is over: reinforce enters again over the current swarm
    # (stickiness only damps baseline switches).
    now[0] = 150.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].reinforce_done == frozenset()
    assert a.reinforce_done == {}
    assert a.decision == "reinforce"


def test_reinforce_ends_next_tick_when_the_ally_dies(now):
    a, b, ships = _reinforce_scene()
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.reinforce_ally == "b"
    for n in b.members:
        ships[n].SetDead()
    now[0] = 1.0
    brain.tick_wing(b)
    assert b.status is None
    brain.tick_wing(a)
    assert a.decision != "reinforce"
    assert a.reinforce_ally is None
    assert a.reinforce_done == {}             # not the cap: no cooldown


def test_reinforce_ends_when_the_ally_command_goes_away(now):
    a, b, ships = _reinforce_scene()
    brain.tick_wing(b)
    brain.tick_wing(a)
    cmd = b.commander
    b.chain = [cmd]
    ships[cmd].GetContainingSet().RemoveObjectFromSet(cmd)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships[cmd], cmd)
    now[0] = 1.0
    brain.tick_wing(b)
    assert b.away is True and b.status is None
    brain.tick_wing(a)
    assert a.decision != "reinforce" and a.reinforce_ally is None


def test_reinforce_latch_clears_on_stand_down(now):
    a, b, ships = _reinforce_scene()
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.reinforce_ally == "b"
    ships[a.commander].SetDead()
    a.chain = [a.commander]
    now[0] = 1.0
    brain.tick_wing(a)
    assert a.leaderless is True
    assert a.reinforce_ally is None
    assert a.decision is None and a.decision_since == 0.0


def test_reinforce_commander_targets_far_primary(monkeypatch):
    """After the AI runs, the idle wing's commander has the far primary as
    its ship target (its stock tree reads the wing's target group)."""
    from engine.core.loop import GameLoop
    monkeypatch.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
    App.g_kTimerManager._time = 0.0
    a, b, ships = _reinforce_scene()
    service.arm(a)
    service.arm(b)
    loop = GameLoop()
    got = None
    for _ in range(6 * 60):
        loop.tick()
        t = ships["a1"].GetTarget()
        if a.decision == "reinforce" and t is not None:
            got = t.GetName()
            break
    assert a.decision == "reinforce"
    assert got == "w1"


# ── screen ─────────────────────────────────────────────────────────────────

def _screen_scene(n=3, player=None):
    """w (hull 0.4: strength_frac 0.4) at the origin; two Warbirds 600 GU
    off, closing (within screen_watch_gu, beyond engage_gu). a (n Akiras)
    idle 800 GU off, nothing near it."""
    pSet = _set()
    group, es = _enemies(pSet, [("e1", (600.0, 0.0, 0.0)),
                                ("e2", (600.0, 30.0, 0.0))])
    a, sa = _wing(pSet, "a", (0.0, 800.0, 0.0), group, n=n)
    w, sw = _wing(pSet, "w", (0.0, 0.0, 0.0), group)
    for s in sw.values():
        s.GetHull().SetConditionPercentage(0.4)
    return a, w, {**es, **sa, **sw}


_SCREEN_TOWARD = (600.0, 15.0, 0.0)          # the enemy centroid


def _screen_point(ships):
    return allies.screen_point(_pos(ships["w1"]), _SCREEN_TOWARD)


def test_screen_puts_every_member_on_hold(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    a, w, ships = _screen_scene()
    for n in a.members:                       # any push shows as 0
        for k in _OFF:
            roster.member(n).conditions[k].SetStatus(1)
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    _assert_hold(a, ships, _screen_point(ships), _SCREEN_TOWARD)
    # Screen keeps the normal target writes: nothing in reach, so the
    # nearest enemy.
    assert _group(a) == {"e2": 3.0}
    assert "[wings] a screen -> w" in capsys.readouterr().err.splitlines()


@pytest.mark.parametrize("n", [1, 2])
def test_screen_hold_with_few_members(n, now):
    a, w, ships = _screen_scene(n=n)
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    hp = _screen_point(ships)
    _assert_hold(a, ships, hp, _SCREEN_TOWARD)
    assert _close(roster.member("a1").move_point, hp)
    if n == 2:
        d = math.dist(roster.member("a2").move_point, hp)
        assert d == pytest.approx(dials.get("hold_spread_gu"))


def test_screen_ends_and_branches_return(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    a, w, ships = _screen_scene()
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    for n in w.members:                       # the ally recovers
        ships[n].GetHull().SetConditionPercentage(1.0)
    now[0] = 1.0
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision != "screen"
    for n in a.members:
        assert _status(n, "hold") == 0
        assert roster.member(n).move_point is None
    assert a.hold_prev is None
    assert "[wings] a screen ends" in capsys.readouterr().err.splitlines()


def test_hold_incumbency_while_the_hold_point_stays(monkeypatch, now):
    a, w, ships = _screen_scene()
    calls = []
    real = attack.assign_slots

    def spy(cands, points, prev=None):
        out = real(cands, points, prev)
        calls.append((prev, out))
        return out
    monkeypatch.setattr(attack, "assign_slots", spy)
    brain.tick_wing(w)
    brain.tick_wing(a)
    first = dict(calls[-1][1])
    assert calls[-1][0] is None
    pts = {n: roster.member(n).move_point for n in ("a2", "a3")}
    # The two followers cross: nearest-first would swap their points.
    p2, p3 = _pos(ships["a2"]), _pos(ships["a3"])
    ships["a2"].SetTranslateXYZ(*p3)
    ships["a3"].SetTranslateXYZ(*p2)
    now[0] = 1.0
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert calls[-1][0] == first
    assert {n: roster.member(n).move_point for n in ("a2", "a3")} == pts
    # The hold point jumps 100 GU (the ally moved): a fresh assignment.
    for n in w.members:
        x, y, z = _pos(ships[n])
        ships[n].SetTranslateXYZ(x, y + 100.0, z)
    now[0] = 2.0
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    assert calls[-1][0] is None


def test_hold_reserve_keeps_its_flag_and_moves_with_formation(now):
    a, w, ships = _screen_scene(n=5)
    assert a.reserve == "a2"
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    assert a.reserve == "a2" and roster.member("a2").reserve is True
    assert a.reserve_spent is False
    _assert_hold(a, ships, _screen_point(ships), _SCREEN_TOWARD)
    on = [k for k in _KINDS if _status("a2", k)]
    assert on == ["hold"]                     # exactly one branch
    # The hold ends: the reserve resumes holding its own point.
    for n in w.members:
        ships[n].GetHull().SetConditionPercentage(1.0)
    now[0] = 1.0
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision != "screen"
    assert _status("a2", "reserve") == 1 and _status("a2", "hold") == 0
    assert roster.member("a2").move_point is not None


def _player_member(wing, ships, name, xyz):
    pSet = ships["a1"].GetContainingSet()
    ships[name] = _ship(pSet, "Akira", name, xyz)
    m = roster.add_member(wing, name, is_player=True)
    m.conditions.update({k: App.TGCondition() for k in _KINDS})
    for c in m.conditions.values():
        c.SetStatus(1)                        # any push would show as 0
    return m


def test_player_member_never_holds(monkeypatch, now):
    a, w, ships = _screen_scene()
    p = _player_member(a, ships, "p", (-60.0, 800.0, 0.0))
    a.chain = ["a1"]
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["p"])
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    assert p.move_point is None
    for k in _PLAYER_KINDS:
        assert p.conditions[k].GetStatus() == 1, k
    _assert_hold(a, ships, _screen_point(ships), _SCREEN_TOWARD)


def test_player_commander_gets_no_hold_point(monkeypatch, now):
    a, w, ships = _screen_scene()
    p = _player_member(a, ships, "p", (10.0, 800.0, 0.0))
    a.chain = ["p"]
    a.commander = "p"
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["p"])
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.commander == "p" and a.decision == "screen"
    assert p.move_point is None
    for k in _PLAYER_KINDS:
        assert p.conditions[k].GetStatus() == 1, k
    hp = _screen_point(ships)
    # The three AI members take the ring; the centre is the commander's.
    ring = allies.formation_points(hp, _SCREEN_TOWARD, 4,
                                   dials.get("hold_spread_gu"))[1:]
    got = []
    for n in ("a1", "a2", "a3"):
        assert _status(n, "hold") == 1
        got.append(next(i for i, q in enumerate(ring)
                        if _close(roster.member(n).move_point, q)))
    assert sorted(got) == [0, 1, 2]


# ── flank ──────────────────────────────────────────────────────────────────

def _flank_scene():
    """b (2400) fights one Warbird (1500) at the origin: engaged, a fair
    fight. a idle 600 GU off along +y."""
    pSet = _set()
    group, es = _enemies(pSet, [("e1", (150.0, 0.0, 0.0))])
    a, sa = _wing(pSet, "a", (0.0, 600.0, 0.0), group)
    b, sb = _wing(pSet, "b", (0.0, 0.0, 0.0), group)
    return a, b, {**es, **sa, **sb}


def test_flank_holds_and_latches_its_ally(monkeypatch, now):
    a, b, ships = _flank_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)                        # a has no status yet
    brain.tick_wing(a)
    assert a.decision == "flank"
    assert a.flank_ally == "b"
    hp = allies.flank_point(_pos(ships["a1"]), _pos(ships["b1"]),
                            b.status.enemy_centroid)
    _assert_hold(a, ships, hp, b.status.enemy_centroid)
    assert _group(a) == {"e1": 3.0}           # normal writes
    now[0] = 1.0
    brain.tick_wing(a)
    assert seen["a1"].flank_ally == "b"
    assert a.decision == "flank"


def test_flank_ally_clears_when_flank_ends(now):
    a, b, ships = _flank_scene()
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.flank_ally == "b"
    ships["e1"].SetDead()                     # b's fight is over
    now[0] = 1.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision != "flank"
    assert a.flank_ally is None
    for n in a.members:
        assert _status(n, "hold") == 0


# ── feint ──────────────────────────────────────────────────────────────────

_FEINT_FOES = (("e1", (300.0, 0.0, 0.0)), ("e2", (300.0, 30.0, 0.0), "Galor"))


def _feint_scene(n=3, enemies=_FEINT_FOES):
    """a (n Akiras, 2400) at the origin fights a Warbird and a Galor (2000)
    300 GU off (engaged, not in reach): 1.2:1, not comfortably ahead, so a
    feint can enter (feint_max_odds 1.25). f idle 600 GU behind a, along
    -x."""
    pSet = _set()
    group, es = _enemies(pSet, list(enemies))
    f, sf = _wing(pSet, "f", (-600.0, 0.0, 0.0), group)
    a, sa = _wing(pSet, "a", (0.0, 0.0, 0.0), group, n=n)
    return a, f, {**es, **sa, **sf}


def _start_feint(a, f):
    brain.tick_wing(f)
    brain.tick_wing(a)
    assert a.decision == "feint"


def test_feint_holds_and_writes_nothing(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    a, f, ships = _feint_scene()
    _start_feint(a, f)
    assert a.feint_ally == "f"
    assert _group(a) == {}                    # nobody turns back early
    lure = allies.lure_point(_pos(ships["a1"]), _pos(ships["f1"]))
    assert _close(lure, (-500.0, 0.0, 0.0))
    _assert_hold(a, ships, lure, (300.0, 15.0, 0.0))
    assert "[wings] a feint -> f" in capsys.readouterr().err.splitlines()


def test_no_feint_when_comfortably_ahead(now):
    # One Warbird (1500) against 2400: 1.6:1, past feint_max_odds.
    a, f, _ships = _feint_scene(enemies=(("e1", (300.0, 0.0, 0.0)),))
    brain.tick_wing(f)
    brain.tick_wing(a)
    assert a.decision != "feint" and a.feint_ally is None


def test_feint_ends_when_the_ally_is_engaged(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    a, f, ships = _feint_scene()
    seen = _spy(monkeypatch)
    _start_feint(a, f)
    ships["e1"].SetTranslateXYZ(-500.0, 0.0, 0.0)    # the trap is sprung
    ships["e2"].SetTranslateXYZ(-500.0, 30.0, 0.0)
    now[0] = 5.0
    brain.tick_wing(f)
    assert f.status.engaged is True
    brain.tick_wing(a)
    assert a.decision != "feint"
    assert a.feint_ally is None
    assert a.feint_cooldown_until == pytest.approx(5.0 + 180.0)
    # f now has a fair fight and we are clear of it: we swing round its
    # flank (a new hold, the feint's ended).
    assert a.decision == "flank" and a.hold_prev[:2] == ("flank", "f")
    err = capsys.readouterr().err.splitlines()
    assert err.index("[wings] a feint ends") < err.index("[wings] a flank -> f")
    now[0] = 6.0
    brain.tick_wing(a)
    assert seen["a1"].feint_ready is False
    now[0] = 185.0
    brain.tick_wing(a)
    assert seen["a1"].feint_ready is True


def test_feint_quiet_ends_it(monkeypatch, now):
    a, f, ships = _feint_scene()
    seen = _spy(monkeypatch)
    _start_feint(a, f)
    assert a.feint_quiet_since is None
    ships["e1"].SetTranslateXYZ(3000.0, 0.0, 0.0)    # they did not follow
    ships["e2"].SetTranslateXYZ(3000.0, 30.0, 0.0)
    now[0] = 1.0
    brain.tick_wing(f)
    brain.tick_wing(a)
    assert a.feint_quiet_since == 1.0
    assert a.decision == "feint"
    now[0] = 11.0
    brain.tick_wing(f)
    brain.tick_wing(a)
    assert seen["a1"].feint_quiet_s == pytest.approx(10.0)
    assert a.decision != "feint"
    assert a.feint_ally is None and a.feint_quiet_since is None
    assert a.feint_cooldown_until == pytest.approx(11.0 + 180.0)


def test_feint_ends_when_the_ally_dies(now):
    a, f, ships = _feint_scene()
    _start_feint(a, f)
    for n in f.members:
        ships[n].SetDead()
    now[0] = 1.0
    brain.tick_wing(f)
    brain.tick_wing(a)
    assert a.decision != "feint" and a.feint_ally is None
    assert a.feint_cooldown_until == pytest.approx(181.0)


def test_feint_with_reserve_and_slots_off(now):
    # Three Warbirds (4500) against five Akiras (4000): no 2x advantage,
    # so the reserve is not committed, and not ahead, so a feint enters.
    a, f, ships = _feint_scene(n=5, enemies=(("e1", (300.0, 0.0, 0.0)),
                                             ("e2", (300.0, 30.0, 0.0)),
                                             ("e3", (300.0, -30.0, 0.0))))
    assert a.reserve == "a2"
    for n in a.members:
        for k in _OFF:
            roster.member(n).conditions[k].SetStatus(1)
        roster.member(n).slot = ("e1", (1.0, 0.0, 0.0), 48.0)
    _start_feint(a, f)
    lure = allies.lure_point(_pos(ships["a1"]), _pos(ships["f1"]))
    _assert_hold(a, ships, lure, (300.0, 0.0, 0.0))
    assert a.reserve == "a2" and roster.member("a2").reserve is True
    assert [k for k in _KINDS if _status("a2", k)] == ["hold"]
    assert a.attack_prev is None


def test_feint_stand_down_starts_cooldown(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    a, f, ships = _feint_scene()
    _start_feint(a, f)
    cmd = a.commander
    a.chain = [cmd]
    ships[cmd].GetContainingSet().RemoveObjectFromSet(cmd)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships[cmd], cmd)
    now[0] = 3.0
    brain.tick_wing(a)
    assert a.away is True
    assert a.feint_ally is None and a.feint_quiet_since is None
    assert a.feint_cooldown_until == pytest.approx(183.0)
    assert a.hold_prev is None and a.flank_ally is None
    for n in a.members:
        assert _status(n, "hold") == 0
        assert roster.member(n).move_point is None
    assert "[wings] a feint ends" in capsys.readouterr().err.splitlines()


# ── no hold: Phase B/C unchanged ───────────────────────────────────────────

def test_decision_since_resets_on_change(monkeypatch, now):
    a, b, ships = _reinforce_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "reinforce" and a.decision_since == 0.0
    now[0] = 2.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision_since == 0.0            # unchanged: no reset
    for n in b.members:
        ships[n].SetDead()
    now[0] = 3.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].decision_age_s == pytest.approx(3.0)
    assert a.decision != "reinforce" and a.decision_since == 3.0
    now[0] = 4.0
    brain.tick_wing(a)
    assert seen["a1"].decision_age_s == pytest.approx(1.0)


def test_no_hold_pushes_hold_off(now):
    a, f, _ships = _feint_scene()
    for n in a.members:
        roster.member(n).conditions["hold"].SetStatus(1)
    brain.tick_wing(a)                        # no ally: no feint
    assert a.decision != "feint"
    for n in a.members:
        assert _status(n, "hold") == 0


def test_reinforce_displaces_a_current_swarm(now):
    """The live order: a wing's first tick comes before its ally has a
    status, so it starts in swarm; once the ally publishes, reinforce
    (1.25) must beat that swarm (1.0 + stickiness) -- stickiness only
    damps baseline switches."""
    a, b, _ships = _reinforce_scene()
    brain.tick_wing(a)
    assert a.decision == "swarm_weakest"
    now[0] = 1.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "reinforce" and a.decision_since == 1.0


# ── review fixes: stand-down clears the decision; a hold member dies ──────

def _send_away(wing, ships):
    cmd = wing.commander
    wing.chain = [cmd]
    home = ships[cmd].GetContainingSet()
    home.RemoveObjectFromSet(cmd)
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships[cmd], cmd)
    return cmd, home, other


def _bring_back(ships, cmd, home, other):
    other.RemoveObjectFromSet(cmd)
    home.AddObjectToSet(ships[cmd], cmd)


def test_away_and_back_mid_flank_re_gates(monkeypatch, now):
    """A flank stood down by command-away comes back with no decision and
    no ally: an ally now in trouble gets the entry gates (reinforce), not a
    latched flank round it."""
    a, b, ships = _flank_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "flank"
    away = _send_away(a, ships)
    now[0] = 1.0
    brain.tick_wing(a)
    assert a.away is True
    assert a.decision is None and a.flank_ally is None
    for n in b.members:                       # b slips into trouble
        ships[n].GetHull().SetConditionPercentage(0.5)
    brain.tick_wing(b)
    assert allies.in_trouble(b.status)
    _bring_back(ships, *away)
    now[0] = 2.0
    brain.tick_wing(a)
    assert a.away is False
    assert seen["a1"].current is None and seen["a1"].flank_ally is None
    assert a.decision == "reinforce" and a.decision_since == 2.0


def test_away_and_back_mid_reinforce_restarts_its_clock(monkeypatch, now):
    """A reinforce re-entered after command-away starts a fresh cap: it is
    not dropped at once on the pre-away clock (with no cooldown)."""
    a, b, ships = _reinforce_scene()
    seen = _spy(monkeypatch)
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "reinforce"
    away = _send_away(a, ships)
    now[0] = 80.0
    brain.tick_wing(a)
    assert a.decision is None and a.reinforce_ally is None
    _bring_back(ships, *away)
    now[0] = 85.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert a.decision == "reinforce" and a.decision_since == 85.0
    now[0] = 91.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].decision_age_s == pytest.approx(6.0)
    assert a.decision == "reinforce" and a.reinforce_ally == "b"
    assert a.reinforce_done == {}


def test_hold_member_dies_mid_hold(now):
    a, w, ships = _screen_scene()
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    ships["a3"].SetDead()
    now[0] = 1.0
    brain.tick_wing(w)
    brain.tick_wing(a)
    assert a.decision == "screen"
    hp = _screen_point(ships)
    _assert_hold(a, ships, hp, _SCREEN_TOWARD, names=["a1", "a2"])
    assert math.dist(roster.member("a2").move_point, hp) == pytest.approx(
        dials.get("hold_spread_gu"))
    m3 = roster.member("a3")
    assert _status("a3", "hold") == 0 and m3.move_point is None


# ── fix wave I3: the player's escort wing stays with the player ───────────

def test_player_escort_wing_never_reinforces(monkeypatch, now):
    a, b, _ships = _reinforce_scene()
    seen = _spy(monkeypatch)
    service.set_player_wing("a")
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].escorts_player is True
    assert seen["b1"].escorts_player is False
    assert a.decision != "reinforce" and a.reinforce_ally is None
    service.set_player_wing(None)
    now[0] = 1.0
    brain.tick_wing(b)
    brain.tick_wing(a)
    assert seen["a1"].escorts_player is False
    assert a.decision == "reinforce"
