"""Wing brain glue, Phase C (spec 2026-11-09-wing-leaders-phase-c-design.md
§3-§5): the brain fills the slot-eligible count, hands attack slots out from
the decision's slot directions, retargets each slot-holder's wing FireScript
(hull or weapons first) and ship target, pushes the attack branch, exempts
slot-holders from rejoin, and stands it all down without command.

Headless against real loadspacehelper ships with wrapped BasicAttack trees
(tests/host/test_wings_tree.py), the brain ticked directly as
tests/host/test_wings_brain_b.py does; the sim tests step the real GameLoop
with the wing armed on the service."""
import math

import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import (  # noqa: E402
    attack, brain, decisions, dials, reserve, roster, service, tree)

_BRANCHES = ("withdraw", "guard", "fallback", "reserve", "attack")
_LEFT = 4


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


def _scene(enemy_xyz, n_members=4, member_xyz=None, member_kind="Akira",
           enemy_kind="BirdOfPrey"):
    """Members m1.. (m1 commands; default 20 GU apart along -x) with wrapped
    BasicAttack trees (so each has its wing FireScript and real
    ConditionWing conditions), enemies e1.. at the given offsets."""
    import AI.Compound.BasicAttack
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {}
    for i in range(1, n_members + 1):
        xyz = (member_xyz[i - 1] if member_xyz
               else (-20.0 * (i - 1), 0.0, 0.0))
        ships["m%d" % i] = _ship(pSet, member_kind, "m%d" % i, xyz)
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


def _hold(monkeypatch, wing, name):
    """Hold `name` as the wing's reserve for the whole test: the arm-time
    pick replaced, and never committed (tests/host/test_wings_reserve.py
    covers the commits)."""
    wing.reserve, wing.reserve_since = name, 0.0
    for n, m in wing.members.items():
        m.reserve = n == name
    monkeypatch.setattr(reserve, "commit_reason", lambda **_kw: None)


def _status(name, kind):
    return roster.member(name).conditions[kind].GetStatus()


def _set_shields(ship, frac):
    shields = ship.GetShields()
    for i in range(6):
        shields.SetCurShields(i, frac * shields.GetMaxShields(i))


def _set_face(ship, face, frac):
    shields = ship.GetShields()
    shields.SetCurShields(face, frac * shields.GetMaxShields(face))


def _holders(wing):
    return sorted(n for n, m in wing.members.items() if m.slot is not None)


def _pos(ship):
    p = ship.GetWorldLocation()
    return (p.x, p.y, p.z)


def _slot_world(target, body_dir, standoff):
    R = target.GetWorldRotation()
    cols = [(c.x, c.y, c.z) for c in (R.GetCol(0), R.GetCol(1), R.GetCol(2))]
    return attack.slot_point(_pos(target), cols, body_dir, standoff)


# ── focus face: slots on the weak side ─────────────────────────────────────

def test_focus_face_assigns_slots_on_weak_side(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert wing.decision == "focus_face"
    holders = _holders(wing)
    assert len(holders) >= 2
    assert "m1" not in holders                    # the commander anchors
    for n in holders:
        m = roster.member(n)
        target, body_dir, standoff = m.slot
        assert target == "e1"
        assert body_dir[0] < 0.0                  # the LEFT side
        assert standoff == dials.get("attack_standoff_gu")
        assert m.attack_target == "e1"
        assert m.fire_script.sTarget == "e1"
        assert not m.fire_script.HasSubsystemTargets()   # hull mode
        assert m.weapons_first is False
        assert ships[n].GetTarget().GetName() == "e1"
        assert _status(n, "attack") == 1
        assert _status(n, "rejoin") == 0 and m.rejoin is False
    # Distinct slots, one per holder.
    assert len({roster.member(n).slot[1] for n in holders}) == len(holders)
    assert _status("m1", "attack") == 0 and roster.member("m1").slot is None


def test_slot_eligible_counts_live_non_commanders(monkeypatch, now):
    wing, ships = _scene([(150.0, 0.0, 0.0)], n_members=5)
    seen = []
    real = decisions.pick
    monkeypatch.setattr(decisions, "pick",
                        lambda ctx: (seen.append(ctx), real(ctx))[1])
    roster.member("m4").fallback_since = -1.0       # last tick's faller
    _hold(monkeypatch, wing, "m5")
    brain.tick_wing(wing)
    assert seen[-1].slot_eligible == 2              # m2, m3
    ships["m2"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    # m4 recovered (full shields) last tick; m2 is dead.
    assert seen[-1].slot_eligible == 2              # m3, m4


def test_slot_holders_stay_out_of_rejoin_even_far(now):
    """A slot-holder beyond the leash keeps its slot and is never pushed to
    rejoin (its slot hangs off the primary)."""
    wing, ships = _scene([(150.0, 0.0, 0.0)],
                         member_xyz=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                     (-20.0, 0.0, 0.0), (500.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert "m4" in _holders(wing)
    assert roster.member("m4").rejoin is False and _status("m4", "rejoin") == 0


# ── exclusivity ────────────────────────────────────────────────────────────

class _GuardAndSlots:
    """Test-only decision: protect m2 against e1 AND slot every free member
    round e1, so guards, fallers and slot-holders compete in one tick."""
    name = "guard_and_slots"

    def score(self, ctx):
        return 9.0

    def choose(self, ctx):
        return decisions.Choice("e1", (), protectee="m2",
                                slot_dirs=attack.envelop_dirs(5),
                                slot_all=True)


def test_commander_guard_faller_reserve_never_slot(monkeypatch, now):
    wing, ships = _scene(
        [(150.0, 0.0, 0.0)], n_members=7,
        member_xyz=[(0.0, 0.0, 0.0), (-40.0, 0.0, 0.0), (-30.0, 20.0, 0.0),
                    (-20.0, -20.0, 0.0), (-60.0, 0.0, 0.0),
                    (-20.0, 40.0, 0.0), (-20.0, -40.0, 0.0)])
    decisions.register(_GuardAndSlots())
    _set_shields(ships["m4"], 0.1)                 # falls back
    _hold(monkeypatch, wing, "m5")                 # held back
    for t in range(3):
        now[0] = float(t)
        brain.tick_wing(wing)
        m = {n: roster.member(n) for n in wing.members}
        # Two guards (a wing of 6+): the nearest healthy to m2 that are
        # not the reserve -- m5, nearer than m6, is held back.
        assert sorted(n for n in m if m[n].guard) == ["m3", "m6"]
        assert m["m4"].fallback_since is not None
        for n in ("m1", "m3", "m4", "m5", "m6"):
            assert m[n].slot is None, n
            assert _status(n, "attack") == 0, n
        assert _holders(wing) == ["m2", "m7"]
        for n in wing.members:
            on = [k for k in _BRANCHES if _status(n, k) == 1]
            if n == "m1":
                assert on == []                    # stock tree
            elif n == "m5":
                assert on == ["reserve"]
            else:
                assert len(on) == 1, (n, on)


def test_withdraw_has_no_slot_holders(now):
    enemies = [(120.0 + 10.0 * i, 10.0 * (i % 3), 0.0) for i in range(8)]
    wing, ships = _scene(enemies, n_members=3)
    for n in ("m1", "m2", "m3"):
        ships[n].GetHull().SetConditionPercentage(0.3)
    # A slot already held from an earlier tick is dropped too.
    m2 = roster.member("m2")
    m2.slot = ("e1", (0.0, -1.0, 0.0), 120.0)
    m2.conditions["attack"].SetStatus(1)
    brain.tick_wing(wing)
    assert wing.decision == "withdraw"
    assert _holders(wing) == []
    for n in ("m2", "m3"):
        assert _status(n, "attack") == 0
        assert _status(n, "withdraw") == 1


# ── disable: weapons-first aim survives the engine sync ────────────────────

def _disable_scene():
    """Four Birds of Prey against one Warbird (strength 1500 vs 400): the
    Warbird sits still with no AI, 150 GU off the commander."""
    wing, ships = _scene([(150.0, 0.0, 0.0)], member_kind="BirdOfPrey",
                         enemy_kind="Warbird")
    return wing, ships


def _weapon_systems(ship):
    return [s for s in (ship.GetTorpedoSystem(), ship.GetPhaserSystem(),
                        ship.GetPulseWeaponSystem()) if s is not None]


def _is_weapon_of(sub, target):
    systems = _weapon_systems(target)
    while sub is not None:
        if any(sub is s for s in systems):
            return True
        sub = sub.GetParentSubsystem()
    return False


def _no_fire_errors(capsys):
    """The wing FireScript never raised (the AI driver logs and carries on,
    so a raise would leave its weapon cycle stuck, silently)."""
    err = capsys.readouterr().err
    assert "'WingFire' raised" not in err, err[-2000:]


def test_disable_aims_at_weapons_and_survives_sync(monkeypatch, capsys):
    from engine.core.loop import GameLoop
    monkeypatch.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
    App.g_kTimerManager._time = 0.0
    wing, ships = _disable_scene()
    service.arm(wing)
    loop = GameLoop()
    for _ in range(90):                            # the first brain tick
        loop.tick()
    assert wing.decision == "disable"
    holders = _holders(wing)
    assert set(holders) == {"m2", "m3", "m4"}      # every eligible member
    for n in holders:
        m = roster.member(n)
        assert m.weapons_first is True
        assert m.fire_script.lTargetSubsystems     # weapons first
        assert ships[n].GetTarget().GetName() == "e1"
    aimed, first = None, None
    for t in range(60 * 60):
        loop.tick()
        for n in holders:
            sub = ships[n].GetTargetSubsystem()
            if sub is not None:
                aimed, first = n, sub
                break
        if aimed is not None:
            break
    assert aimed is not None, "no holder ever aimed at a subsystem"
    assert _is_weapon_of(first, ships["e1"])
    for _ in range(60):
        loop.tick()
        sub = ships[aimed].GetTargetSubsystem()
        assert sub is not None
        assert _is_weapon_of(sub, ships["e1"])
        assert ships[aimed].GetTarget().GetName() == "e1"
    _no_fire_errors(capsys)


# ── stand-down ─────────────────────────────────────────────────────────────

def test_slot_target_death_clears_slots(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert len(_holders(wing)) >= 2
    ships["e1"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    assert _holders(wing) == []
    for n, m in wing.members.items():
        assert m.attack_target is None
        assert _status(n, "attack") == 0


def test_leaderless_clears_attack(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert len(_holders(wing)) >= 2
    ships["m1"].SetDead()                          # the whole chain
    wing.chain = ["m1"]
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.leaderless is True
    assert _holders(wing) == []
    for n, m in wing.members.items():
        assert m.attack_target is None
        assert _status(n, "attack") == 0


def test_command_away_clears_attack(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert len(_holders(wing)) >= 2
    wing.chain = ["m1"]
    ships["m1"].GetContainingSet().RemoveObjectFromSet("m1")
    other = SetClass_Create()
    App.g_kSetManager.AddSet(other, "Elsewhere")
    other.AddObjectToSet(ships["m1"], "m1")
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.away is True
    assert _holders(wing) == []
    for n in wing.members:
        assert _status(n, "attack") == 0


def test_attack_change_logged_once(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    now[0] = 1.0
    brain.tick_wing(wing)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if " attack " in ln]
    assert lines == ["[wings] blue attack e1 slots=3 weapons_first=0"]


# ── in the sim: a holder reaches its slot and faces the target ─────────────

def _angle_deg(ship, target):
    fwd = ship.GetWorldRotation().GetCol(1)
    here, there = _pos(ship), _pos(target)
    d = [there[i] - here[i] for i in range(3)]
    n = math.sqrt(sum(x * x for x in d))
    f = (fwd.x, fwd.y, fwd.z)
    c = sum(f[i] * d[i] for i in range(3)) / max(n, 1e-9)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def test_slot_holder_reaches_slot_and_faces(monkeypatch, capsys):
    from engine.core.loop import GameLoop
    monkeypatch.delenv("OPEN_STBC_HOST_HEADLESS", raising=False)
    App.g_kTimerManager._time = 0.0
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    target = ships["e1"]                           # no AI: it holds still
    service.arm(wing)
    loop = GameLoop()
    best = None
    for t in range(1800):
        _set_shields(target, 1.0)
        _set_face(target, _LEFT, 0.1)              # held: the weak face
        loop.tick()
        if t < 600 or t % 30:
            continue
        assert wing.decision == "focus_face"
        for n in _holders(wing):
            slot = roster.member(n).slot
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(
                _pos(ships[n]), _slot_world(target, slot[1], slot[2]))))
            ang = _angle_deg(ships[n], target)
            if d < 40.0 and ang < 30.0:
                best = (n, d, ang)
    assert best is not None, "no holder reached its slot facing the target"
    _no_fire_errors(capsys)


# ── fix round 1 ────────────────────────────────────────────────────────────

def _rewrap(wing, ship):
    """Re-run the wrap on a ship (as DauntlessWings.WrapTree / the QB
    CreateAI wrap do): a fresh FireScript, own-name target, hull mode."""
    import AI.Compound.BasicAttack
    stock = AI.Compound.BasicAttack.CreateAI(ship, wing.target_group,
                                             Difficulty=0.5)
    ship.SetAI(tree.wrap_tree(ship, stock, wing))


def test_rewrapped_holder_gets_new_fire_script_retargeted(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    assert "m2" in _holders(wing)
    old = roster.member("m2").fire_script
    _rewrap(wing, ships["m2"])
    new = roster.member("m2").fire_script
    assert new is not old and new.sTarget == "m2"     # the placeholder
    now[0] = 1.0
    brain.tick_wing(wing)
    assert "m2" in _holders(wing)
    assert new.sTarget == "e1"
    assert not new.HasSubsystemTargets()
    assert _status("m2", "attack") == 1


def test_rewrapped_holder_under_disable_is_weapons_first(now):
    wing, ships = _disable_scene()
    brain.tick_wing(wing)
    assert wing.decision == "disable" and "m2" in _holders(wing)
    _rewrap(wing, ships["m2"])
    new = roster.member("m2").fire_script
    assert not new.HasSubsystemTargets()              # built in hull mode
    now[0] = 1.0
    brain.tick_wing(wing)
    assert new.sTarget == "e1"
    assert new.HasSubsystemTargets()
    assert roster.member("m2").weapons_first is True


def test_member_without_fire_script_takes_no_slot(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    roster.member("m2").fire_script = None            # stock tree kept
    brain.tick_wing(wing)
    assert wing.decision == "focus_face"
    holders = _holders(wing)
    assert "m2" not in holders and len(holders) >= 2


class _AlwaysSlots:
    """Test-only decision naming e1 with slots whatever the snapshot says,
    so the brain's own check on the resolved primary decides."""
    name = "always_slots"

    def score(self, ctx):
        return 9.0

    def choose(self, ctx):
        return decisions.Choice("e1", (), slot_dirs=attack.envelop_dirs(3))


def test_cloaked_primary_gets_no_slots(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    decisions.register(_AlwaysSlots())
    brain.tick_wing(wing)
    assert len(_holders(wing)) == 3
    ships["e1"].GetCloakingSubsystem().StartCloaking()
    assert ships["e1"].GetCloakingSubsystem().IsCloaking()
    now[0] = 1.0
    brain.tick_wing(wing)
    assert _holders(wing) == []
    for n in wing.members:
        assert _status(n, "attack") == 0


def test_dead_primary_named_by_decision_gets_no_slots(now):
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    decisions.register(_AlwaysSlots())
    brain.tick_wing(wing)
    assert len(_holders(wing)) == 3
    ships["e1"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    assert _holders(wing) == []


def test_attack_end_is_logged(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    ships["e1"].SetDead()
    now[0] = 1.0
    brain.tick_wing(wing)
    now[0] = 2.0
    brain.tick_wing(wing)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if " attack" in ln]
    assert lines == ["[wings] blue attack e1 slots=3 weapons_first=0",
                     "[wings] blue attack ends"]


def test_attack_end_is_logged_on_stand_down(monkeypatch, capsys, now):
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    wing, ships = _scene([(150.0, 0.0, 0.0)])
    _set_face(ships["e1"], _LEFT, 0.1)
    brain.tick_wing(wing)
    ships["m1"].SetDead()                          # the whole chain
    wing.chain = ["m1"]
    now[0] = 1.0
    brain.tick_wing(wing)
    assert wing.leaderless is True
    err = capsys.readouterr().err
    assert "[wings] blue attack ends" in err.splitlines()
