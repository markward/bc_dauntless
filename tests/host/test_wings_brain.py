"""Wing brain glue (spec 2026-11-09-wing-leaders-phase-a-design.md §5-§10):
snapshot the live world into ShipViews, resolve the commander, pick a
decision, write the wing target group and push member condition statuses.

Headless against real loadspacehelper ships in a fresh set."""
import pytest

pytest.importorskip("_dauntless_host")

import App  # noqa: E402
import loadspacehelper  # noqa: E402

from engine.appc.sets import SetClass_Create  # noqa: E402
from engine.wings import brain, decisions, dials, roster  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    def _clear():
        App.g_kSetManager._sets.clear()
        roster.reset()
        dials.reset()
        decisions.reset_registry()
    _clear()
    yield
    _clear()


def _ship(pSet, kind, name, xyz):
    s = loadspacehelper.CreateShip(kind, pSet, name, None, 0, 0)
    s.SetTranslateXYZ(*xyz)
    return s


def _scene(enemy_xyz, extra_enemy_names=(), n_members=2):
    """Akira members (m1 at the origin, m2 20 GU off, m3 40 GU off) and Bird
    of Prey enemies at the given offsets, named e1, e2, ..."""
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    ships = {"m%d" % i: _ship(pSet, "Akira", "m%d" % i,
                              (20.0 * (i - 1), 0.0, 0.0))
             for i in range(1, n_members + 1)}
    group = App.ObjectGroup()
    for i, xyz in enumerate(enemy_xyz, 1):
        name = "e%d" % i
        ships[name] = _ship(pSet, "BirdOfPrey", name, xyz)
        group.AddName(name)
    for name in extra_enemy_names:
        group.AddName(name)
    wing = roster.create_wing("blue", group)
    for i in range(1, n_members + 1):
        roster.add_member(wing, "m%d" % i)
    brain.arm_chain(wing)
    return wing, ships


def _move(ship, to_set_name):
    """Take the ship out of its set and put it in another (a warp)."""
    name = ship.GetName()
    ship.GetContainingSet().RemoveObjectFromSet(name)
    other = App.g_kSetManager.GetSet(to_set_name)
    if other is None:
        other = SetClass_Create()
        App.g_kSetManager.AddSet(other, to_set_name)
    other.AddObjectToSet(ship, name)


def _group(wing):
    return {n: wing.target_group[n]["Priority"]
            for n in wing.target_group.GetNameTuple()}


def _select_node(ship, target_group):
    """A real PreprocessingAI holding the SDK's stock SelectTarget, weighted
    the way a wing member's is (popularity = wing_popularity)."""
    from AI import Preprocessors
    node = App.PreprocessingAI_Create(ship, "SelectTarget")
    node.SetPreprocessingMethod(Preprocessors.SelectTarget(target_group),
                                "Update")
    node.GetPreprocessingInstance().SetRelativeImportance(
        fPopularity=dials.get("wing_popularity"))
    return node


# ── view_of ────────────────────────────────────────────────────────────────

def test_view_of_reads_the_live_ship():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    s = _ship(pSet, "Akira", "a", (10.0, 20.0, 30.0))
    s.GetHull().SetConditionPercentage(0.5)
    v = brain.view_of(s, "blue", True)
    assert v.name == "a" and v.pos == (10.0, 20.0, 30.0)
    assert v.hull == pytest.approx(0.5)
    assert v.shield == pytest.approx(1.0)
    assert v.power == pytest.approx(
        s.GetPowerSubsystem().GetProperty().GetPowerOutput())
    assert v.power > 0.0
    assert v.wing_id == "blue" and v.is_commander is True


def test_view_of_is_none_for_missing_dead_and_dying():
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "WingTest")
    dead = _ship(pSet, "Akira", "d", (0.0, 0.0, 0.0))
    dying = _ship(pSet, "Akira", "y", (0.0, 0.0, 0.0))
    dead.SetDead()
    dying.SetDying(1)
    assert brain.view_of(None) is None
    assert brain.view_of(dead) is None
    assert brain.view_of(dying) is None


def test_arm_chain_ranks_rated_power_and_sets_commander():
    wing, _ships = _scene([(100.0, 0.0, 0.0)])
    assert wing.chain == ["m1"]          # 2 members -> chain of 1; tie keeps order
    assert wing.commander == "m1"


# ── tick ───────────────────────────────────────────────────────────────────

def test_snapshot_skips_dead_and_missing():
    wing, ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0)],
                         extra_enemy_names=("ghost",))
    ships["e2"].SetDead()
    assert "ghost" in wing.target_group.GetNameTuple()   # seeded at create
    brain.tick_wing(wing)
    names = set(wing.target_group.GetNameTuple())
    assert "ghost" not in names and "e2" not in names
    assert names == {"e1"}


def test_tick_writes_reach_set_and_primary():
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0),
                          (250.0, 0.0, 0.0)])
    ships["e2"].GetHull().SetConditionPercentage(0.5)   # e2 is the weakest
    brain.tick_wing(wing)
    # 2 Akiras outmatch 3 Birds of Prey -> swarm the weakest in reach;
    # e3 is past the 200 GU leash, so it is not in the group at all.
    assert wing.decision == "swarm_weakest"
    assert _group(wing) == {"e2": 3.0, "e1": 1.5}
    assert wing.primary == "e2"


def test_far_enemy_removed_from_group():
    wing, ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0)])
    brain.tick_wing(wing)
    assert "e1" in wing.target_group.GetNameTuple()
    ships["e1"].SetTranslateXYZ(600.0, 0.0, 0.0)
    brain.tick_wing(wing)
    assert set(wing.target_group.GetNameTuple()) == {"e2"}


def test_nothing_in_reach_holds_only_the_nearest():
    wing, _ships = _scene([(500.0, 0.0, 0.0), (900.0, 0.0, 0.0)])
    brain.tick_wing(wing)
    assert _group(wing) == {"e1": 3.0}
    assert wing.primary == "e1"


def test_km_priority_kept_for_reach_set():
    wing, _ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0),
                           (140.0, 0.0, 0.0)])
    wing.km_priorities = lambda: {"e3": 2.0}
    brain.tick_wing(wing)
    group = _group(wing)
    # The listed e3 is the primary; the decision's e1 steps down.
    assert group["e3"] == 3.0 and group["e1"] == 1.5 and group["e2"] == 1.5


def test_km_listed_ship_outside_enemy_group_is_a_candidate():
    """A listed ship that is not in the enemy group (a neutral Quick Battle
    protect target) is still a candidate enemy: enemy-group names first,
    then the km names."""
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    pSet = ships["m1"].GetContainingSet()
    ships["n1"] = _ship(pSet, "BirdOfPrey", "n1", (120.0, 0.0, 0.0))
    wing.km_priorities = lambda: {"n1": 2.0}
    brain.tick_wing(wing)
    group = _group(wing)
    assert set(group) == {"e1", "n1"}
    assert group["n1"] == 3.0


def test_handover_on_commander_death():
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    wing.chain = ["m1", "m2"]
    brain.tick_wing(wing)
    assert wing.commander == "m1"
    ships["m1"].SetDead()
    brain.tick_wing(wing)
    assert wing.commander == "m2"
    assert wing.leaderless is False


def test_leaderless_latches_and_restores_stock():
    wing, ships = _scene([(100.0, 0.0, 0.0), (600.0, 0.0, 0.0)])
    node = _select_node(ships["m2"], wing.target_group)
    roster.member("m2").select_nodes.append(node)
    roster.member("m2").select_saved[id(node)] = -1.1   # as found (stock)
    node.GetPreprocessingInstance().fDistanceFactor = 2.5  # never touched
    rejoin = App.TGCondition()
    rejoin.SetStatus(1)
    roster.member("m2").conditions["rejoin"] = rejoin
    roster.member("m2").rejoin = True
    ships["m1"].SetDead()                     # the whole chain
    brain.tick_wing(wing)
    assert wing.leaderless is True and wing.commander is None
    assert _group(wing) == {"e1": 0.0, "e2": 0.0}   # every enemy, out of reach too
    inst = node.GetPreprocessingInstance()
    assert inst.fPopularityFactor == pytest.approx(-1.1)    # restored
    assert inst.fDistanceFactor == pytest.approx(2.5)
    assert rejoin.GetStatus() == 0 and roster.member("m2").rejoin is False
    # The command is not re-elected even if a chain ship came back.
    ships["m1"].SetDead(False)
    brain.tick_wing(wing)
    assert wing.leaderless is True and wing.commander is None


def test_leaderless_desperation_pushes_ram_or_flee():
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    ram, flee = App.TGCondition(), App.TGCondition()
    m2 = roster.member("m2")
    m2.conditions.update({"ram": ram, "flee": flee})
    ships["m2"].GetHull().SetConditionPercentage(0.2)
    ships["m2"].SetTarget("e1")
    ships["m1"].SetDead()
    dials._dials["ram_chance"] = 1.0           # deterministic: always ram

    class _Ram:
        target = None

        def SetTargetObjectName(self, name):
            self.target = name
    m2.ram_script = _Ram()
    brain.tick_wing(wing)
    assert m2.desperate == "ram"
    assert ram.GetStatus() == 1 and flee.GetStatus() == 0
    assert m2.ram_script.target == "e1"
    # Permanent: a later tick does not re-roll.
    dials._dials["ram_chance"] = 0.0
    brain.tick_wing(wing)
    assert m2.desperate == "ram" and flee.GetStatus() == 0


def test_rejoin_pushed_with_hysteresis():
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    cond = App.TGCondition()
    roster.member("m2").conditions["rejoin"] = cond
    ships["m2"].SetTranslateXYZ(-350.0, 0.0, 0.0)    # past leash + slack
    brain.tick_wing(wing)
    assert cond.GetStatus() == 1 and roster.member("m2").rejoin is True
    ships["m2"].SetTranslateXYZ(-250.0, 0.0, 0.0)    # inside the slack: hold
    brain.tick_wing(wing)
    assert cond.GetStatus() == 1
    ships["m2"].SetTranslateXYZ(-150.0, 0.0, 0.0)    # inside the leash
    brain.tick_wing(wing)
    assert cond.GetStatus() == 0 and roster.member("m2").rejoin is False


def test_primary_change_forces_select_update(monkeypatch):
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    node = _select_node(ships["m2"], wing.target_group)
    roster.member("m2").select_nodes.append(node)
    calls = []
    monkeypatch.setattr(node, "ForceUpdate", lambda: calls.append(1))
    brain.tick_wing(wing)
    assert wing.primary == "e1" and len(calls) == 1
    brain.tick_wing(wing)                       # unchanged primary
    assert len(calls) == 1
    ships["e2"].GetHull().SetConditionPercentage(0.3)
    brain.tick_wing(wing)
    assert wing.primary == "e2" and len(calls) == 2


def test_enemy_commander_flagged_from_roster(monkeypatch):
    wing, ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0)])
    red = roster.create_wing("red", App.ObjectGroup())
    roster.add_member(red, "e1")
    red.commander = "e1"
    seen = {}
    real = decisions.pick

    def spy(ctx):
        seen.update({e.name: (e.wing_id, e.is_commander) for e in ctx.enemies})
        return real(ctx)
    monkeypatch.setattr(decisions, "pick", spy)
    brain.tick_wing(wing)
    assert seen == {"e1": ("red", True), "e2": (None, False)}


def test_player_commander_target_is_primary(monkeypatch):
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    roster.member("m1").is_player = True
    brain.arm_chain(wing)
    assert wing.chain == ["m1"] and wing.commander == "m1"
    ships["m1"].SetTarget("e2")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["m1"])
    brain.tick_wing(wing)
    assert wing.primary == "e2" and _group(wing)["e2"] == 3.0


def test_tick_safely_swallows_one_wing_and_runs_the_rest(monkeypatch):
    wing, _ships = _scene([(100.0, 0.0, 0.0)])
    bad = roster.create_wing("bad", App.ObjectGroup())
    ran = []
    real = brain.tick_wing

    def tick(w):
        if w is bad:
            raise RuntimeError("boom")
        ran.append(w.wing_id)
        real(w)
    monkeypatch.setattr(brain, "tick_wing", tick)
    brain.tick_all()
    assert ran == ["blue"]


def test_log_only_when_env_set(monkeypatch, capsys):
    monkeypatch.delenv("DAUNTLESS_WINGS_LOG", raising=False)
    brain.log("quiet")
    monkeypatch.setenv("DAUNTLESS_WINGS_LOG", "1")
    brain.log("loud")
    err = capsys.readouterr().err
    assert "quiet" not in err and "[wings] loud" in err


# ── sets: the wing lives where most of its members are ─────────────────────

def test_commander_in_another_set_hands_over_and_reclaims():
    wing, ships = _scene([(100.0, 0.0, 0.0), (900.0, 0.0, 0.0)], n_members=3)
    wing.chain = ["m1", "m2"]
    brain.tick_wing(wing)
    assert wing.commander == "m1"
    _move(ships["m1"], "Elsewhere")
    brain.tick_wing(wing)
    assert wing.commander == "m2" and wing.leaderless is False
    assert "e1" in wing.target_group.GetNameTuple()
    _move(ships["m1"], "WingTest")
    brain.tick_wing(wing)
    assert wing.commander == "m1"


def test_whole_chain_in_another_set_fights_stock_not_latched():
    """Command alive but away (e.g. the player warped): the wing is
    TEMPORARILY leaderless -- every candidate at stock priority, no latch."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)], n_members=3)
    rejoin = App.TGCondition()
    roster.member("m2").conditions["rejoin"] = rejoin
    brain.tick_wing(wing)
    assert wing.chain == ["m1"] and _group(wing)
    _move(ships["m1"], "Elsewhere")             # e.g. the player warped
    ships["e1"].SetTranslateXYZ(900.0, 0.0, 0.0)   # out of any reach
    ships["m2"].SetTranslateXYZ(-900.0, 0.0, 0.0)  # far past the leash
    brain.tick_wing(wing)
    assert _group(wing) == {"e1": 0.0, "e2": 0.0}  # all candidates
    assert wing.leaderless is False and wing.commander == "m1"
    assert rejoin.GetStatus() == 0


def test_command_away_restores_stock_everywhere_once(monkeypatch):
    """Away: popularity back as found, rejoin stood down for every member in
    ANY set, SelectTarget forced once on entering, no desperation roll; when
    a chain entry is home again the wing is a wing again."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0),
                          (900.0, 0.0, 0.0)], n_members=4)
    m2, m4 = roster.member("m2"), roster.member("m4")
    node = _select_node(ships["m2"], wing.target_group)
    m2.select_nodes.append(node)
    m2.select_saved[id(node)] = -1.1           # as found (stock)
    m2.ai_root = ships["m2"].GetAI()
    calls = []
    monkeypatch.setattr(node, "ForceUpdate", lambda: calls.append(1))
    rejoin2, rejoin4, ram = App.TGCondition(), App.TGCondition(), \
        App.TGCondition()
    m2.conditions.update({"rejoin": rejoin2, "ram": ram})
    m4.conditions["rejoin"] = rejoin4
    brain.tick_wing(wing)
    assert "e3" not in _group(wing)
    calls.clear()
    for m, cond in ((m2, rejoin2), (m4, rejoin4)):
        m.rejoin = True
        cond.SetStatus(1)
    _move(ships["m4"], "Other")                 # a straggler in a third set
    _move(ships["m1"], "Elsewhere")             # the whole chain away
    ships["m2"].GetHull().SetConditionPercentage(0.2)
    dials._dials["ram_chance"] = 1.0
    brain.tick_wing(wing)
    assert wing.leaderless is False and wing.commander == "m1"
    assert _group(wing) == {"e1": 0.0, "e2": 0.0, "e3": 0.0}
    inst = node.GetPreprocessingInstance()
    assert inst.fPopularityFactor == pytest.approx(-1.1)
    assert rejoin2.GetStatus() == 0 and rejoin4.GetStatus() == 0
    assert m2.rejoin is False and m4.rejoin is False
    assert calls == [1]
    assert m2.desperate is None and ram.GetStatus() == 0
    brain.tick_wing(wing)                       # still away: forced once
    assert calls == [1]
    _move(ships["m1"], "WingTest")
    brain.tick_wing(wing)
    assert wing.commander == "m1" and "e3" not in _group(wing)
    assert inst.fPopularityFactor == pytest.approx(
        dials.get("wing_popularity"))


def test_member_outside_home_set_is_never_left_rejoining():
    """A member left in another set while command is home is stood down:
    WingRejoin cannot reach a commander in another set."""
    wing, ships = _scene([(100.0, 0.0, 0.0)], n_members=3)
    cond = App.TGCondition()
    roster.member("m3").conditions["rejoin"] = cond
    ships["m3"].SetTranslateXYZ(-350.0, 0.0, 0.0)    # past leash + slack
    brain.tick_wing(wing)
    assert cond.GetStatus() == 1
    _move(ships["m3"], "Other")
    brain.tick_wing(wing)
    assert wing.commander == "m1"
    assert cond.GetStatus() == 0 and roster.member("m3").rejoin is False


def test_listed_primary_change_forces_select_update(monkeypatch):
    """The ForceUpdate trigger follows the WRITTEN primary: a km-listed ship
    promoted over the decision's pick counts as a change."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0),
                          (140.0, 0.0, 0.0)])
    node = _select_node(ships["m2"], wing.target_group)
    roster.member("m2").select_nodes.append(node)
    calls = []
    monkeypatch.setattr(node, "ForceUpdate", lambda: calls.append(1))
    brain.tick_wing(wing)
    assert wing.primary == "e1" and len(calls) == 1
    wing.km_priorities = lambda: {"e3": 2.0}
    brain.tick_wing(wing)
    assert _group(wing)["e3"] == 3.0
    assert wing.primary == "e3" and len(calls) == 2


def test_player_commanding_nothing_in_reach_escorts_form_up(monkeypatch):
    """The player commands, nothing in reach, no candidate target: the
    group is empty and escorts beyond the gather distance rejoin."""
    wing, ships = _scene([(600.0, 0.0, 0.0), (900.0, 0.0, 0.0)],
                         n_members=3)
    roster.member("m1").is_player = True
    brain.arm_chain(wing)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ships["m1"])
    ships["m1"].SetTarget(None)
    near, far = App.TGCondition(), App.TGCondition()
    roster.member("m2").conditions["rejoin"] = near     # 20 GU off
    roster.member("m3").conditions["rejoin"] = far
    ships["m3"].SetTranslateXYZ(-150.0, 0.0, 0.0)  # inside leash, past gather
    brain.tick_wing(wing)
    assert _group(wing) == {}
    assert far.GetStatus() == 1 and roster.member("m3").rejoin is True
    assert near.GetStatus() == 0


def test_cloaked_enemy_never_in_target_group():
    """Cloaked or cloaking enemies are not candidates (SelectTarget skips a
    cloaked ship): not in the reach set, not the nothing-in-reach pick."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0),
                          (170.0, 0.0, 0.0)])
    ships["e1"].GetCloakingSubsystem().InstantCloak()
    ships["e2"].GetCloakingSubsystem().StartCloaking()
    assert ships["e2"].GetCloakingSubsystem().IsCloaking()
    brain.tick_wing(wing)
    assert set(_group(wing)) == {"e3"}


def test_cloaked_nearest_is_not_the_nothing_in_reach_pick():
    wing, ships = _scene([(500.0, 0.0, 0.0), (900.0, 0.0, 0.0)])
    ships["e1"].GetCloakingSubsystem().InstantCloak()
    brain.tick_wing(wing)
    assert _group(wing) == {"e2": 3.0}


def test_command_away_stands_rejoin_down():
    """While command is away nobody can rejoin it: members in the home set
    drop the flag and fight with their stock tree until it is back."""
    wing, ships = _scene([(100.0, 0.0, 0.0)], n_members=3)
    rejoin = App.TGCondition()
    roster.member("m2").conditions["rejoin"] = rejoin
    ships["m2"].SetTranslateXYZ(-350.0, 0.0, 0.0)    # past leash + slack
    brain.tick_wing(wing)
    assert rejoin.GetStatus() == 1 and roster.member("m2").rejoin is True
    _move(ships["m1"], "Elsewhere")
    brain.tick_wing(wing)
    assert rejoin.GetStatus() == 0 and roster.member("m2").rejoin is False
    assert wing.commander == "m1" and wing.leaderless is False


def test_ram_roll_with_no_target_flees():
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    ram, flee = App.TGCondition(), App.TGCondition()
    m2 = roster.member("m2")
    m2.conditions.update({"ram": ram, "flee": flee})
    ships["m2"].GetHull().SetConditionPercentage(0.2)
    ships["m2"].SetTarget(None)
    ships["m1"].SetDead()
    dials._dials["ram_chance"] = 1.0
    brain.tick_wing(wing)
    assert m2.desperate == "flee"
    assert flee.GetStatus() == 1 and ram.GetStatus() == 0


def test_going_leaderless_forces_select_update(monkeypatch):
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    brain.tick_wing(wing)                       # primary settles first
    node = _select_node(ships["m2"], wing.target_group)
    roster.member("m2").select_nodes.append(node)
    calls = []
    monkeypatch.setattr(node, "ForceUpdate", lambda: calls.append(1))
    ships["m1"].SetDead()
    brain.tick_wing(wing)
    assert wing.leaderless is True and calls == [1]


# ── shared enemy snapshot (final review M2) ────────────────────────────────

def _second_wing(ships, wing, wing_id="green", names=("g1", "g2")):
    """Another wing on the same side, same enemy group, same home set."""
    pSet = ships["m1"].GetContainingSet()
    other = roster.create_wing(wing_id, wing.enemy_group)
    for i, name in enumerate(names):
        ships[name] = _ship(pSet, "Akira", name, (-20.0 * (i + 1), 0.0, 0.0))
        roster.add_member(other, name)
    brain.arm_chain(other)
    return other


def _game_time(monkeypatch, start=0.0):
    now = [start]
    monkeypatch.setattr(App.g_kUtopiaModule, "GetGameTime", lambda: now[0])
    return now


def _count_shield_reads(monkeypatch):
    reads = {}
    real = brain._shield_faces

    def spy(ship):
        reads[ship.GetName()] = reads.get(ship.GetName(), 0) + 1
        return real(ship)
    monkeypatch.setattr(brain, "_shield_faces", spy)
    return reads


def test_wings_on_one_side_share_the_enemy_snapshot(monkeypatch):
    """Two wings ticking within one period read each enemy ship once."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    green = _second_wing(ships, wing)
    now = _game_time(monkeypatch)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    now[0] = 0.5
    brain.tick_wing(green)
    assert reads["e1"] == 1 and reads["e2"] == 1
    assert _group(green) == _group(wing)


def test_enemy_snapshot_older_than_the_period_is_rebuilt(monkeypatch):
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    green = _second_wing(ships, wing)
    now = _game_time(monkeypatch)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    ships["e1"].SetTranslateXYZ(600.0, 0.0, 0.0)     # out of reach
    now[0] = dials.get("brain_period_s") + 0.01
    brain.tick_wing(green)
    assert reads["e1"] == 2
    assert set(_group(green)) == {"e2"}


def test_enemy_snapshot_never_reused_by_the_wing_that_read_it(monkeypatch):
    """A wing's next tick always sees a fresh world, even if the game clock
    has not moved a whole period (float drift on the accumulator)."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    now = _game_time(monkeypatch)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    now[0] = dials.get("brain_period_s") - 1e-6
    brain.tick_wing(wing)
    assert reads["e1"] == 2


def test_enemy_commander_follows_a_handover_while_the_snapshot_is_warm(
        monkeypatch):
    """The cached views carry no roster flags: a handover in the enemy wing
    between two of our wings' ticks is seen by the second one."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (120.0, 0.0, 0.0)])
    green = _second_wing(ships, wing)
    red = roster.create_wing("red", App.ObjectGroup())
    roster.add_member(red, "e1")
    roster.add_member(red, "e2")
    red.commander = "e1"
    now = _game_time(monkeypatch)
    seen = []
    real = decisions.pick

    def spy(ctx):
        seen.append({e.name: (e.wing_id, e.is_commander)
                     for e in ctx.enemies})
        return real(ctx)
    monkeypatch.setattr(decisions, "pick", spy)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    red.commander = "e2"                       # the handover
    now[0] = 0.25
    brain.tick_wing(green)
    assert reads["e1"] == 1                    # the snapshot was warm
    assert seen[0] == {"e1": ("red", True), "e2": ("red", False)}
    assert seen[1] == {"e1": ("red", False), "e2": ("red", True)}


def test_reset_clears_the_enemy_snapshot(monkeypatch):
    from engine.wings import service
    wing, ships = _scene([(100.0, 0.0, 0.0)])
    green = _second_wing(ships, wing)
    _game_time(monkeypatch)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    service.reset()
    brain.tick_wing(green)
    assert reads["e1"] == 2


def test_enemy_snapshot_cache_drops_expired_entries(monkeypatch):
    """A candidate list that changes (a name leaves the group) keys a new
    entry; the old one is dropped once expired instead of piling up for
    the rest of the mission."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0),
                          (170.0, 0.0, 0.0)])
    now = _game_time(monkeypatch)
    period = dials.get("brain_period_s")
    for i in (1, 2, 3):
        brain.tick_wing(wing)
        wing.enemy_group.RemoveName("e%d" % i)
        now[0] += period
    brain.tick_wing(wing)
    assert len(brain._enemy_cache) == 1


def test_enemy_killed_inside_the_period_leaves_the_warm_snapshot(
        monkeypatch):
    """A ship that dies between two wings' ticks is dropped from the warm
    snapshot: it never reaches the second wing's target group."""
    wing, ships = _scene([(100.0, 0.0, 0.0), (150.0, 0.0, 0.0)])
    green = _second_wing(ships, wing)
    now = _game_time(monkeypatch)
    reads = _count_shield_reads(monkeypatch)
    brain.tick_wing(wing)
    assert "e1" in wing.target_group.GetNameTuple()
    ships["e1"].SetDead()
    now[0] = 0.25
    brain.tick_wing(green)
    assert reads["e2"] == 1                    # still the warm snapshot
    assert set(_group(green)) == {"e2"}
