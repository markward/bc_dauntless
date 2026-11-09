"""Wing Phase D behaviour (spec 2026-11-09-wing-leaders-phase-d-design.md
§9): reinforce, flank and feint seen in a real headless fight between two
wings on one side and a shared enemy group.

The scenes are tests/host/test_wings_phase_c_behaviour.py's: loadspacehelper
ships in one set, every member's stock BasicAttack wrapped (the wing
FireScript, the real ConditionWing conditions), both wings armed on the
service (the 1 Hz brain, staggered), with OPEN_STBC_HOST_HEADLESS pinned
unset so radii come from the models. Each tick is the host's
(tests/helpers/k1_fight.py _loop_arm): GameLoop.tick, then the weapons and
combat step, where beams do damage -- GameLoop.tick alone never deals any.

Each test runs against a control: the same scene with the decision under
test unregistered (decisions.register of a stand-in that never scores),
every other decision live. Each runs three times, every RNG the fight draws
on seeded differently (k3_fight.seed_every_rng); every bound is generous
and its margin is documented beside it.

An "idle" wing is never idle for long (2026-11-09): with nothing in reach
its target group holds the nearest enemy at 3.0 (Phase A §9), and the
commander's stock intercept goes for it, in-system warp included. So (a)
gives the idle wing somewhere else to go -- a decoy -- and (c)'s ally holds
station (spec §12)."""
import math

import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine import host_loop  # noqa: E402
from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.appc.ship_iter import iter_ships  # noqa: E402
from engine.core.loop import TICK_DELTA, GameLoop  # noqa: E402
from engine.wings import assess, decisions, dials, roster, service, tree  # noqa: E402
from tests.helpers import headless_mission  # noqa: E402
from tests.helpers.k3_fight import seed_every_rng  # noqa: E402

HZ = 60
SEEDS = (1, 2, 3)


def _clear():
    App.g_kSetManager._sets.clear()
    service.reset_all()
    App.g_kTimerManager._time = 0.0
    headless_mission.clear_in_flight()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
    _clear()
    yield
    _clear()


class _Off:
    """A registered decision that never scores: the control's way of
    taking the decision under test out (decisions.register replaces by
    name; service.reset_all restores the stock registry)."""

    def __init__(self, name):
        self.name = name

    def score(self, ctx):
        return 0.0

    def choose(self, ctx):
        return decisions.swarm_choice(ctx)


def _ship(pSet, kind, name, xyz):
    s = loadspacehelper.CreateShip(kind, pSet, name, None, 0, 0)
    s.SetTranslateXYZ(*xyz)
    s.UpdateNodeOnly()
    return s


def _scene(seed, wings, enemies, off=()):
    """A fresh world with the decisions named in `off` unregistered.

    `wings`: (wing id, ship kind, positions[, hold]) each, a wing on side
    "friendly" with members <id>1.. (1 commands) and wrapped BasicAttack
    trees against one shared enemy group -- none with hold true: its ships
    hold station, the brain still leads it and publishes its status.
    `enemies`: (kind, position, foes) each, ships e1.. with stock
    BasicAttack against the members of the wings named in `foes` ("*":
    every wing), or none (it holds still) when foes is empty. Every wing
    is armed on the service. Returns (wings by id, ships, GameLoop)."""
    import AI.Compound.BasicAttack
    _clear()
    for name in off:
        decisions.register(_Off(name))
    seed_every_rng(seed)
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {}
    theirs = App.ObjectGroup()
    for i, (kind, xyz, _foes) in enumerate(enemies, 1):
        ships["e%d" % i] = _ship(pSet, kind, "e%d" % i, xyz)
        theirs.AddName("e%d" % i)
    built, members = {}, {}
    for wid, kind, xyzs, *hold in wings:
        wing = roster.create_wing(wid, theirs)
        wing.side = "friendly"
        names = []
        for i, xyz in enumerate(xyzs, 1):
            n = "%s%d" % (wid, i)
            ships[n] = _ship(pSet, kind, n, xyz)
            roster.add_member(wing, n)
            names.append(n)
        for n in names if not any(hold) else ():
            s = ships[n]
            stock = AI.Compound.BasicAttack.CreateAI(s, wing.target_group,
                                                     Difficulty=0.5)
            s.SetAI(tree.wrap_tree(s, stock, wing))
        built[wid], members[wid] = wing, names
    for i, (_kind, _xyz, foes) in enumerate(enemies, 1):
        if not foes:
            continue
        group = App.ObjectGroup()
        for wid in (built if foes == "*" else foes):
            for n in members[wid]:
                group.AddName(n)
        s = ships["e%d" % i]
        s.SetAI(AI.Compound.BasicAttack.CreateAI(s, group, Difficulty=0.5))
    for wing in built.values():
        service.arm(wing)
    return built, ships, GameLoop(owns_boundary=False)


def _step(loop):
    """One sim tick the host's way: GameLoop.tick, the weapons and the
    combat step in the tick's effect scope, then the tick boundary."""
    loop.tick()
    ships = list(iter_ships())
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, push_render_data=False)
    host_loop._combat_tick_boundary()


def _alive(ship):
    return not ship.IsDead() and not ship.IsDying()


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _anchor(wing, ships):
    """The wing commander's position, or None (leaderless / dead)."""
    s = ships.get(wing.commander)
    return _pos(s) if s is not None and _alive(s) else None


def _centroid(ships, names):
    pts = [_pos(ships[n]) for n in names if _alive(ships[n])]
    if not pts:
        return None
    return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


def _enemies(ships):
    return sorted(n for n in ships if n.startswith("e"))


def _row(origin, n, dx=-20.0):
    return [(origin[0] + dx * i, origin[1], origin[2]) for i in range(n)]


def _count(tally, key):
    tally[key] = tally.get(key, 0) + 1


# ── (a) reinforce: an idle wing goes to a losing ally ──────────────────────

_FIVE = [(0.0, 0.0, 0.0), (0.0, 30.0, 0.0), (0.0, -30.0, 0.0),
         (20.0, 15.0, 0.0), (20.0, -15.0, 0.0)]


def _reinforce_run(seed, off=(), secs=60):
    """B (2 Akiras, 1600) fights five Galors (2500) 150 GU off: in
    trouble. A (4 Akiras) sits idle 600 GU from the Galors, B between
    them. The Galors fight B; a Warbird decoy holds still 450 GU off A's
    far side, nearer A than any Galor: what A's nearest-enemy fallback
    goes for when nothing sends it to B. Returns (the A-commander to
    B-commander distance every tick, A's decisions (ticks))."""
    wings, ships, loop = _scene(
        seed,
        [("a", "Akira", _row((-600.0, 0.0, 0.0), 4)),
         ("b", "Akira", _row((-150.0, 0.0, 0.0), 2))],
        [("Galor", xyz, ("b",)) for xyz in _FIVE]
        + [("Warbird", (-1050.0, 0.0, 0.0), ())], off)
    a, b = wings["a"], wings["b"]
    dists, decs = [], {}
    for _t in range(secs * HZ):
        _step(loop)
        pa, pb = _anchor(a, ships), _anchor(b, ships)
        dists.append(None if pa is None or pb is None
                     else assess.dist(pa, pb))
        _count(decs, a.decision)
    return dists, decs


def _first(dists, limit):
    """The first time (s) a distance is at most `limit`, or None."""
    return next((i / HZ for i, x in enumerate(dists)
                 if x is not None and x <= limit), None)


def _low(dists):
    return min(x for x in dists if x is not None)


@pytest.mark.parametrize("seed", SEEDS)
def test_idle_wing_reinforces_losing_ally(seed):
    d, decs = _reinforce_run(seed)
    c, c_decs = _reinforce_run(seed, off=("reinforce",))
    leash = dials.get("leash_gu")
    print("\n[reinforce seed %d] A within leash of B at %s s (closest %.0f "
          "GU); A's decisions (ticks) %s; control closest %.0f GU, end "
          "%.0f GU; decisions %s" % (seed, _first(d, leash), _low(d), decs,
                                     _low(c), c[-1], c_decs))
    assert "reinforce" in decs
    # A's commander intercepts the far primary (in-system warp included)
    # and the reinforce ends on arrival, within leash of B's commander.
    # Bound 60 s; seen at 7.0 / 19.2 / 6.7 s, closest 107 / 199 / 127 GU
    # (2026-11-09, seeds 1-3; 6.7-10.0 s on seeds 4-9 with feint off).
    assert _first(d, leash) is not None
    # Control: A goes for the decoy (and disables it). Seen: closest
    # 431 / 450 / 450 GU, 867-977 GU at 60 s (435-450 on seeds 4-9).
    # Without the decoy the control's nearest-enemy fallback took A to
    # B's fight anyway (within 130 GU of B, seed 1), so this bound could
    # not tell the two apart.
    assert _low(c) > 400.0


# ── (b) flank: an idle wing swings onto the side of an ally's fight ────────

_FOUR = [(0.0, 0.0, 0.0), (0.0, 30.0, 0.0), (20.0, 15.0, 0.0),
         (20.0, -15.0, 0.0)]


def _angle_at(c, p, q):
    """The angle (degrees) at c between p and q."""
    u = [a - b for a, b in zip(p, c)]
    v = [a - b for a, b in zip(q, c)]
    cos = (sum(a * b for a, b in zip(u, v))
           / (math.hypot(*u) * math.hypot(*v)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _flank_run(seed, off=(), secs=120):
    """B (4 Akiras, 3200) fights four Galors (2000) 150 GU off: engaged,
    not in trouble. A (4 Akiras) sits idle 600 GU from B, on B's side of
    the Galors, 45 degrees off the line from them to B (700 GU from
    them). Returns (the angle at the enemy centroid C between A's and B's
    anchors when A's anchor first comes within engage_gu of C, or None;
    that time (s); A's decisions (ticks))."""
    wings, ships, loop = _scene(
        seed,
        [("a", "Akira", _row((-495.0, 495.0, 0.0), 4)),
         ("b", "Akira", _row((-150.0, 0.0, 0.0), 4))],
        [("Galor", xyz, ("b",)) for xyz in _FOUR], off)
    a, b = wings["a"], wings["b"]
    engage = dials.get("engage_gu")
    foes = _enemies(ships)
    decs = {}
    for t in range(secs * HZ):
        _step(loop)
        _count(decs, a.decision)
        c = _centroid(ships, foes)
        pa, pb = _anchor(a, ships), _anchor(b, ships)
        if c is None or pa is None or pb is None:
            continue
        if assess.dist(pa, c) <= engage:
            return _angle_at(c, pa, pb), t / HZ, decs
    return None, None, decs


def test_idle_wing_flanks_even_fight():
    got, ctl = [], []
    for seed in SEEDS:
        ang, t, decs = _flank_run(seed)
        c_ang, c_t, c_decs = _flank_run(seed, off=("flank",))
        print("\n[flank seed %d] angle at C %s deg at %s s; A's decisions "
              "(ticks) %s; control %s deg at %s s; decisions %s"
              % (seed, ang, t, decs, c_ang, c_t, c_decs))
        assert "flank" in decs
        assert ang is not None and c_ang is not None
        got.append(ang)
        ctl.append(c_ang)
    print("[flank] mean %.1f deg, control mean %.1f deg"
          % (sum(got) / len(got), sum(ctl) / len(ctl)))
    # A swings round to the flank point at impulse and comes in from the
    # side, past square: the two wings close on C from far apart. The
    # control intercepts straight in. Seen: 119 / 149 / 93 deg at 62-73 s
    # (mean 120); the control 52 / 52 / 49 deg at 9-10 s (2026-11-09,
    # seeds 1-3; 96-116 vs 48-55 deg on seeds 4-7 with feint off).
    assert sum(1 for a in got if a >= 60.0) >= 2
    assert sum(got) / len(got) >= sum(ctl) / len(ctl) + 20.0


# ── (c) feint: a fighting wing draws its enemy onto an idle ally ───────────

_THREE = [(0.0, 0.0, 0.0), (0.0, 30.0, 0.0), (20.0, -15.0, 0.0)]


def _feint_run(seed, off=(), secs=40):
    """W (4 Akiras, 3200) fights three Galors (1500) 150 GU off; F (4
    Akiras) holds station 500 GU from W, on W's far side from them. With
    its own AI, F flanks W's fight and its commander warps in when the
    flank ends, in both arms, so F's anchor converges on the fight either
    way and hides the lure (spec §12). The Galors fight every friendly
    ship. Returns (the enemy centroid's distance to F's anchor every 5 s,
    W's decisions (ticks))."""
    wings, ships, loop = _scene(
        seed,
        [("w", "Akira", _row((-150.0, 0.0, 0.0), 4)),
         ("f", "Akira", _row((-650.0, 0.0, 0.0), 4), True)],
        [("Galor", xyz, "*") for xyz in _THREE], off)
    w, f = wings["w"], wings["f"]
    foes = _enemies(ships)
    trace, decs = [], {}
    for t in range(secs * HZ + 1):
        if t:
            _step(loop)
            _count(decs, w.decision)
        if t % (5 * HZ):
            continue
        c, pf = _centroid(ships, foes), _anchor(f, ships)
        trace.append(None if c is None or pf is None
                     else round(assess.dist(c, pf)))
    return trace, decs


def test_feint_draws_enemy_onto_ally():
    got, ctl = [], []
    for seed in SEEDS:
        tr, decs = _feint_run(seed)
        c_tr, c_decs = _feint_run(seed, off=("feint",))
        print("\n[feint seed %d] C-F every 5 s %s; W's decisions (ticks) "
              "%s\n control C-F %s; decisions %s"
              % (seed, tr, decs, c_tr, c_decs))
        assert "feint" in decs
        assert tr[-1] is not None and c_tr[-1] is not None
        got.append(tr[-1])
        ctl.append(c_tr[-1])
    gain = [c - g for g, c in zip(got, ctl)]
    print("[feint] C-F at 40 s %s, control %s, mean gain %.0f GU"
          % (got, ctl, sum(gain) / len(gain)))
    # W pulls back toward F the whole 40 s (feint_max_s is 45 s) and the
    # Galors follow. Seen: C-F 473 GU at 40 s on every seed, the control
    # (W fights where it stands) 601 / 606 / 609 GU: a gain of 128-136 GU
    # (2026-11-09, seeds 1-5). With F's own AI on, F flanks and comes in
    # in both arms: 268 / 265 / 265 vs 276 / 276 / 278 GU.
    assert sum(1 for x in gain if x > 0) >= 2
    assert sum(gain) / len(gain) >= 50.0
