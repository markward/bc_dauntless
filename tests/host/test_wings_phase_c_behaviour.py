"""Wing Phase C behaviour (spec 2026-11-09-wing-leaders-phase-c-design.md
§8): focus face, disable and the reserve seen in a real headless fight.

The scenes are tests/host/test_wings_brain_c.py's: loadspacehelper ships in
one set, every member's stock BasicAttack wrapped (the wing FireScript, the
real ConditionWing conditions), the wing armed on the service, with
OPEN_STBC_HOST_HEADLESS pinned unset so radii come from the models
(tests/host/test_wings_combat_stress.py). Each tick is the host's
(tests/helpers/k1_fight.py _loop_arm): GameLoop.tick, then the weapons and
combat step, where beams do damage -- GameLoop.tick alone never deals any.

The trigger of each behaviour is forced so it is the same every run -- a held
shield face, a fixed strength gap, a scripted kill -- and each test runs
against a control: the same scene with the behaviour dialled off. Each runs
three times, every RNG the fight draws on seeded differently
(k3_fight.seed_every_rng); these scenes came out close run to run
(2026-11-09), but every bound is still generous and its margin is documented
beside it."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine import host_loop  # noqa: E402
from engine.appc import ship_death  # noqa: E402
from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.appc.ship_iter import iter_ships  # noqa: E402
from engine.core.loop import TICK_DELTA, GameLoop  # noqa: E402
from engine.wings import assess, dials, roster, service, tree  # noqa: E402
from tests.helpers import headless_mission  # noqa: E402
from tests.helpers.k3_fight import seed_every_rng  # noqa: E402

HZ = 60
SEEDS = (1, 2, 3)
_LEFT = 4


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


def _ship(pSet, kind, name, xyz):
    s = loadspacehelper.CreateShip(kind, pSet, name, None, 0, 0)
    s.SetTranslateXYZ(*xyz)
    s.UpdateNodeOnly()
    return s


def _scene(monkeypatch, seed, member_kind, member_xyz, enemy_kind,
           enemy_xyz, dial_overrides=None, enemy_ai=True):
    """A fresh world: members m1.. (m1 commands) with wrapped BasicAttack
    trees, armed on the service; enemies e1.. with stock BasicAttack
    against the members (none with enemy_ai False: they hold still);
    `dial_overrides` applied. Returns (wing, ships, GameLoop)."""
    import AI.Compound.BasicAttack
    _clear()
    for k, v in (dial_overrides or {}).items():
        monkeypatch.setitem(dials._dials, k, v)
    seed_every_rng(seed)
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {}
    mine = App.ObjectGroup()
    for i, xyz in enumerate(member_xyz, 1):
        ships["m%d" % i] = _ship(pSet, member_kind, "m%d" % i, xyz)
        mine.AddName("m%d" % i)
    theirs = App.ObjectGroup()
    for i, xyz in enumerate(enemy_xyz, 1):
        ships["e%d" % i] = _ship(pSet, enemy_kind, "e%d" % i, xyz)
        theirs.AddName("e%d" % i)
    wing = roster.create_wing("blue", theirs)
    for i in range(1, len(member_xyz) + 1):
        roster.add_member(wing, "m%d" % i)
    for i in range(1, len(member_xyz) + 1):
        s = ships["m%d" % i]
        stock = AI.Compound.BasicAttack.CreateAI(s, wing.target_group,
                                                 Difficulty=0.5)
        s.SetAI(tree.wrap_tree(s, stock, wing))
    if enemy_ai:
        for i in range(1, len(enemy_xyz) + 1):
            s = ships["e%d" % i]
            s.SetAI(AI.Compound.BasicAttack.CreateAI(s, mine,
                                                     Difficulty=0.5))
    service.arm(wing)
    return wing, ships, GameLoop(owns_boundary=False)


def _step(loop):
    """One sim tick the host's way: GameLoop.tick, the weapons and the
    combat step in the tick's effect scope, then the tick boundary."""
    loop.tick()
    ships = list(iter_ships())
    with host_loop._combat_effect_scope():
        host_loop._advance_weapons(ships, TICK_DELTA)
        host_loop._advance_combat(ships, TICK_DELTA, push_render_data=False)
    host_loop._combat_tick_boundary()


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _body(target, ship):
    """`ship`'s position in `target`'s body frame: R^T (p - t)."""
    R = target.GetWorldRotation()
    d = [a - b for a, b in zip(_pos(ship), _pos(target))]
    return tuple(sum(c * x for c, x in zip((col.x, col.y, col.z), d))
                 for col in (R.GetCol(0), R.GetCol(1), R.GetCol(2)))


def _holders(wing):
    return sorted(n for n, m in wing.members.items() if m.slot is not None)


# ── (a) focus face: the slot-holders flank the weak (LEFT) side ────────────

def _hold_target(ship):
    """Full hull and shields, the LEFT face at 0.1: the weak side stays."""
    ship.GetHull().SetConditionPercentage(1.0)
    shields = ship.GetShields()
    for i in range(App.ShieldClass.NUM_SHIELDS):
        frac = 0.1 if i == _LEFT else 1.0
        shields.SetCurShields(i, frac * shields.GetMaxShields(i))


def _focus_face_run(seed, monkeypatch, slots_on):
    """Five Akiras against a Bird of Prey that fights back, its LEFT face
    held at 0.1. The wing starts on the target's RIGHT (+x of an unrotated
    target). Returns (decisions seen, samples every 0.5 s from 30 s:
    (slot-holders, slot-holders on the LEFT, non-commanders on the LEFT))."""
    wing, ships, loop = _scene(
        monkeypatch, seed, "Akira",
        [(150.0 + 20.0 * i, 0.0, 0.0) for i in range(5)],
        "BirdOfPrey", [(0.0, 0.0, 0.0)],
        None if slots_on else {"attack_slots": 0})
    target = ships["e1"]
    samples, decs = [], set()
    for t in range(60 * HZ):
        _hold_target(target)
        _step(loop)
        decs.add(wing.decision)
        if t < 30 * HZ or t % 30:
            continue
        holders = _holders(wing)
        others = [n for n in wing.members if n != wing.commander
                  and not ships[n].IsDead()]
        samples.append((
            len(holders),
            sum(1 for n in holders if _body(target, ships[n])[0] < 0.0),
            sum(1 for n in others if _body(target, ships[n])[0] < 0.0)))
    return decs, samples


@pytest.mark.parametrize("seed", SEEDS)
def test_focus_face_flanks_weak_side(seed, monkeypatch):
    decs, on = _focus_face_run(seed, monkeypatch, True)
    c_decs, off = _focus_face_run(seed, monkeypatch, False)
    frac_on = sum(1 for _h, left, _o in on if left >= 2) / len(on)
    frac_off = sum(1 for _h, _l, left in off if left >= 2) / len(off)
    print("\n[focus_face seed %d] >=2 slot-holders LEFT on %.2f of samples "
          "30-60 s (holders %s); control (attack_slots 0) >=2 members LEFT "
          "%.2f; decisions %s / %s"
          % (seed, frac_on, sorted({h for h, _l, _o in on}), frac_off,
             sorted(map(str, decs)), sorted(map(str, c_decs))))
    assert "focus_face" in decs
    # The wing starts on the target's right; the holders take ~26-30 s to
    # come round the turning target (focus_face from the first brain tick).
    # From 30 s: >= 2 holders on the LEFT on 0.88-0.93 of samples, the
    # control's members on 0.00 (2026-11-09, 3 seeds).
    assert frac_on >= 0.7
    assert frac_off <= 0.3


# ── (b) disable: a much stronger enemy loses its weapons first ─────────────

def _weapon_systems(ship):
    return [s for s in (ship.GetTorpedoSystem(), ship.GetPhaserSystem(),
                        ship.GetPulseWeaponSystem()) if s is not None]


def _disable_run(seed, monkeypatch, disable_on, cap_s=600):
    """Four Galors (power 500 each) against a Warbird (1500: 3x) holding
    still, 150 GU off. Returns the first time (s) its weapons are all down
    the way the brain reads them (IsDisabled() or the system's own condition
    gone, brain._weapons_down), the first time they all read IsDisabled(),
    the first time its hull is below 0.5, the decisions (s each) and a
    minute-by-minute trace (hull, each weapon system's own condition)."""
    wing, ships, loop = _scene(
        monkeypatch, seed, "Galor",
        [(-20.0 * i, 0.0, 0.0) for i in range(4)],
        "Warbird", [(150.0, 0.0, 0.0)],
        None if disable_on else {"disable_threat": 5.0}, enemy_ai=False)
    target = ships["e1"]
    down_t = isdis_t = hull_t = None
    trace, decs = [], {}
    for t in range(cap_s * HZ):
        _step(loop)
        if t % HZ == 0:
            decs[wing.decision] = decs.get(wing.decision, 0) + 1
        systems = _weapon_systems(target)
        if down_t is None and all(s.IsDisabled() or s.GetCondition() <= 0.0
                                  for s in systems):
            down_t = t / HZ
        if isdis_t is None and all(s.IsDisabled() for s in systems):
            isdis_t = t / HZ
        hull = target.GetHull().GetConditionPercentage()
        if hull_t is None and hull < 0.5:
            hull_t = t / HZ
        if t % (60 * HZ) == 0:
            trace.append((t // HZ, round(hull, 2),
                          [round(s.GetConditionPercentage(), 2)
                           for s in systems]))
        if hull_t is not None and (down_t is not None or not disable_on):
            break
    return down_t, isdis_t, hull_t, decs, trace


@pytest.mark.parametrize("seed", SEEDS)
def test_disable_weapons_before_hull_half(seed, monkeypatch):
    down, isdis, hull, decs, trace = _disable_run(seed, monkeypatch, True)
    c_down, c_isdis, c_hull, c_decs, c_trace = _disable_run(
        seed, monkeypatch, False)
    for tag, d, i, h, ds, tr in (
            ("disable", down, isdis, hull, decs, trace),
            ("control", c_down, c_isdis, c_hull, c_decs, c_trace)):
        print("\n[%s seed %d] weapons down %s s (IsDisabled %s) hull<0.5 %s s "
              "decisions %s %s" % (tag, seed, d, i, h, ds, tr))
    assert "disable" in decs
    # Weapons-first aim lands on each weapon SYSTEM's own condition, which
    # its IsDisabled() (the banks' aggregate) never reads; the brain reads a
    # system with none left as down (spec §2). Seen: weapons down at
    # 235.3-235.8 s, hull below half at 283.6-348.2 s (2026-11-09, 3
    # seeds); IsDisabled() never all true within the run.
    assert down is not None
    assert hull is None or down < hull
    # Control (disable_threat 5.0: hull fire on envelop / focus_face slots):
    # hull below half at 352.5-385.8 s with every weapon system untouched.
    assert c_hull is not None
    assert c_down is None or c_hull < c_down


def _latch_run(seed, monkeypatch):
    """Four Akiras (800 each) against a Warbird (1500: 1.88x) that fights
    back, 150 GU off (final review I1). Returns (the first time (s) the
    brain reads its weapons down, the lowest strength ratio seen while the
    wing was still disabling, the decision every second until then)."""
    wing, ships, loop = _scene(
        monkeypatch, seed, "Akira",
        [(-20.0 * i, 0.0, 0.0) for i in range(4)],
        "Warbird", [(150.0, 0.0, 0.0)])
    target = ships["e1"]
    from engine.wings import brain
    decs, low = [], None
    for t in range(int(dials.get("disable_max_s")) * HZ):
        _step(loop)
        if t % HZ or t == 0:
            continue
        ev = brain.view_of(target, weapons=True)
        if ev.weapons_down:
            return t / HZ, low, decs
        decs.append(wing.decision)
        mine = max(assess.strength(brain.view_of(ships[n]))
                   for n in wing.members if brain._alive(ships[n]))
        if wing.decision == "disable":
            r = assess.strength(ev) / mine
            low = r if low is None else min(low, r)
    return None, low, decs


@pytest.mark.parametrize("seed", SEEDS)
def test_disable_holds_until_weapons_down(seed, monkeypatch):
    down, low, decs = _latch_run(seed, monkeypatch)
    print("\n[disable latch seed %d] weapons down %s s; lowest ratio while "
          "disabling %.2f; decisions %s"
          % (seed, down, low, sorted(set(map(str, decs)))))
    # Before the latch, disable ended at 103 s at ratio 1.5 (the gate) with
    # the weapons up, and they never went down (final review I1, seed 1).
    # Latched: one unbroken disable from the first brain tick until the
    # weapons are down. Seen: down at 179 / 267 / 220 s, the ratio falling
    # to 0.94-0.98 while still disabling (2026-11-09, seeds 1-3). With a
    # 120 s cap no seed got the weapons down: disable_max_s defaults to 300.
    assert down is not None
    assert set(decs) == {"disable"}
    assert low < dials.get("disable_threat")


# ── (c) reserve: held back until a loss, then committed ────────────────────

def _hold_full(ships):
    """Every live ship at full hull and shields: no death, no damage rate
    (so no protect), no strength change (so no advantage commit) but the
    scripted one."""
    for s in ships.values():
        if s.IsDead() or s.IsDying():
            continue
        s.GetHull().SetConditionPercentage(1.0)
        shields = s.GetShields()
        for i in range(App.ShieldClass.NUM_SHIELDS):
            shields.SetCurShields(i, shields.GetMaxShields(i))


def _centroid(ships, names):
    pts = [_pos(ships[n]) for n in names
           if not ships[n].IsDead() and not ships[n].IsDying()]
    return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


KILL_S = 40
AFTER_S = 25


def _reserve_run(seed, monkeypatch, kill):
    """Six Akiras (4800 power) against two Warbirds (3000: no 2x
    advantage) that fight back. With `kill`, a member that is neither the
    commander nor the reserve dies at KILL_S. Returns (reserve, commit
    time, held samples every 0.5 s before KILL_S [(d_reserve, d_cmd)],
    the reserve's distance every 0.5 s from KILL_S on), distances to the
    enemy centroid."""
    wing, ships, loop = _scene(
        monkeypatch, seed, "Akira",
        [(-20.0 * i, 0.0, 0.0) for i in range(6)],
        "Warbird", [(150.0, 0.0, 0.0), (160.0, 30.0, 0.0)])
    res = wing.reserve
    assert res is not None
    victim = next(n for n in sorted(wing.members)
                  if n not in (wing.commander, res))
    held, after, committed = [], [], None
    for t in range((KILL_S + AFTER_S) * HZ):
        _hold_full(ships)
        if kill and t == KILL_S * HZ:
            ship_death.begin(ships[victim])
        _step(loop)
        if committed is None and wing.reserve is None:
            committed = t / HZ
        if t % 30:
            continue
        cen = _centroid(ships, ("e1", "e2"))
        d_res = assess.dist(_pos(ships[res]), cen)
        if t < KILL_S * HZ:
            d_cmd = assess.dist(_pos(ships[wing.commander]), cen)
            held.append((d_res, d_cmd))
        else:
            after.append(d_res)
    return res, committed, held, after


@pytest.mark.parametrize("seed", SEEDS)
def test_reserve_stays_back_until_loss(seed, monkeypatch):
    res, committed, held, after = _reserve_run(seed, monkeypatch, True)
    _r, c_committed, _h, c_after = _reserve_run(seed, monkeypatch, False)
    back = sum(1 for r, c in held if r > c) / len(held)
    print("\n[reserve seed %d] %s farther than the commander on %.2f of held "
          "samples (mean %.0f GU); committed %s s; distance at the kill %.0f, "
          "min within %d s %.0f, end %.0f GU; control (no kill) committed %s, "
          "end %.0f GU"
          % (seed, res, back, sum(r for r, _c in held) / len(held),
             committed, after[0], AFTER_S, min(after), after[-1],
             c_committed, c_after[-1]))
    # Held: farther from the enemy than the commander on 1.00 of samples
    # (2026-11-09, 3 seeds).
    assert back >= 0.8
    # Held until the kill, committed on the brain tick after it (seen 40.98 s).
    assert committed is not None and KILL_S <= committed <= KILL_S + 2.0
    # Then it closes. It sits ~130-150 GU farther out than the commander and
    # first turns about (it keeps opening the range ~7 s); an Akira makes
    # 6.6 GU/s. Seen: 268-269 GU at the kill, 179-185 GU 25 s later (-84
    # to -90); the control (held, or committed on advantage at 64 s) ends
    # at 311-323 GU (2026-11-09, 3 seeds).
    assert min(after) <= after[0] - 50.0
    assert after[-1] <= c_after[-1] - 50.0
