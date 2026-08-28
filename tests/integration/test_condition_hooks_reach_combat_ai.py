"""The Cardassian torpedo doctrine must be reachable in a real fight.

THE BUG THIS PINS. ``AI/Compound/NonFedAttack.py`` BuilderCreate8 gates its
whole close-range torpedo branch on

    if (bUsingTorps and bTorpsReady) or (bAggroPulse and bPulseReady): ACTIVE

where ``bUsingTorps`` is a ``ConditionUsingWeapon``. That condition has no way
to evaluate itself -- ``__init__`` sets it false and the ONLY thing that ever
sets it true is the ``UsingWeaponType`` callback broadcast by
``FireScript.Update`` (AI/Preprocessors.py:290) down the AI subtree. Reaching
it needs both halves of the external-function path: the condition's
``RegisterExternalFunctions`` has to be called when it is attached to the AI,
and the ConditionalAI has to actually dispatch the resulting ``CodeID``
mapping.

Live capture before the fix, 3 Keldons vs the player in QuickBattle:

    FwdTorpsOrPulseReady            DORMANT  conds=[1, 0, 0, 0]
    RearTorpsReadySortaClose...     DORMANT  conds=[1, 1, 1, 0]
    FireAll  lWeapons=['Torpedoes','Compressors']  bCallUsingWeaponTypeFunc=0

-- torpedoes ready, the broadcast already sent and reset, and the fourth
condition still false because it reached nobody.

This test is deliberately behavioural. A structural assertion ("was
RegisterExternalFunctions called?") passes over a registration that resolves to
nothing, which is the other half of the same bug.
"""
import pytest


SHIPS = 12
SETTLE_TICKS = 120
MEASURE_TICKS = 400


@pytest.fixture
def nonfed_scene(monkeypatch):
    """combat_stress, but running the Cardassian doctrine rather than
    BasicAttack -- NonFedAttack is where the torpedo gates live.

    Yields the loop UNSETTLED. SelectTarget broadcasts SetTarget only when its
    chosen target changes, and the first change (None -> "Enemy-1") happens on
    the first few ticks -- a fixture that settles before yielding hides it, and
    a test written against that fixture would report "the dispatch never
    reaches conditions" when what it actually missed was the one broadcast.
    """
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", str(SHIPS))
    monkeypatch.setenv("DAUNTLESS_COMBAT_AVOID", "1")

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import importlib
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.core.loop import GameLoop

    cs = importlib.import_module("engine.dev_missions.combat_stress")
    monkeypatch.setattr(cs, "_ATTACK_AI_MODULE", "AI.Compound.NonFedAttack")

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)
    cs.Initialize(mission)
    evt = App.TGEvent()
    evt.SetEventType(App.ET_MISSION_START)
    evt.SetDestination(ep)
    App.g_kEventManager.AddEvent(evt)

    yield GameLoop()
    _set_current_game(None)


def _nodes_named(name):
    """Every AI node called `name`, across every ship's tree."""
    from engine.appc.ship_iter import iter_ships

    found = []

    def walk(node):
        if node is None:
            return
        if node.GetName() == name:
            found.append(node)
        walk(getattr(node, "_contained_ai", None))
        for child in (getattr(node, "_ais", None) or []):
            walk(child[1] if isinstance(child, tuple) else child)

    for ship in iter_ships():
        try:
            walk(ship.GetAI())
        except Exception:
            pass
    return found


def test_the_forward_torpedo_gate_becomes_reachable_in_a_crowded_fight(
        nonfed_scene):
    import App

    loop = nonfed_scene
    for _ in range(SETTLE_TICKS):
        loop.tick()
    gates = _nodes_named("FwdTorpsOrPulseReady")
    assert gates, "no FwdTorpsOrPulseReady nodes — scene did not build NonFedAttack"

    reached = False
    for _ in range(MEASURE_TICKS):
        loop.tick()
        if any(g._status == App.ArtificialIntelligence.US_ACTIVE for g in gates):
            reached = True
            break

    if not reached:
        sample = gates[0]
        vec = [c.GetStatus() for c in sample._conditions]
        pytest.fail(
            "FwdTorpsOrPulseReady never reached ACTIVE across "
            f"{len(gates)} ships in {MEASURE_TICKS} ticks; sample condition "
            f"vector {vec} (order: TorpsReady, PulseReady, AggroPulse, "
            "UsingTorps). A trailing 0 on UsingTorps means the FireScript's "
            "UsingWeaponType broadcast still reaches nobody."
        )


def test_the_using_weapon_condition_is_actually_set_by_the_broadcast(
        nonfed_scene):
    """Pin the mechanism, not just the outcome: it is the fourth condition --
    the ConditionUsingWeapon -- that has to go true, not some other one."""
    loop = nonfed_scene
    for _ in range(SETTLE_TICKS):
        loop.tick()

    using_weapon = []
    for gate in _nodes_named("FwdTorpsOrPulseReady"):
        for cond in gate._conditions:
            inst = getattr(cond, "_instance", None)
            if type(inst).__name__ == "ConditionUsingWeapon":
                using_weapon.append(cond)
    assert using_weapon, "no ConditionUsingWeapon instances in the scene"

    for _ in range(MEASURE_TICKS):
        loop.tick()
        if any(c.GetStatus() for c in using_weapon):
            return

    pytest.fail(
        f"none of {len(using_weapon)} ConditionUsingWeapon instances was ever "
        "set true. FireScript broadcasts UsingWeaponType once per weapon-set "
        "change (AI/Preprocessors.py:290) and the condition is set entirely by "
        "that callback."
    )


def test_a_retarget_reaches_the_range_conditions_in_a_live_tree(nonfed_scene):
    """The other broadcast name, on real SDK conditions in a real AI tree.

    ``SelectTarget`` seeds itself with ``ForceCurrentTargetString`` -- whose
    docstring says outright "It doesn't call all the target setup functions" --
    and its ``CodeAISet`` is commented out in the shipped SDK, so the SetTarget
    broadcast fires only when the chosen target *changes* away from the one the
    tree was built with. In a scene where nobody's target dies, zero broadcasts
    is correct, so waiting for one to happen tests nothing.

    The two lines below ARE the SDK's dispatch (AI/Preprocessors.py:1405-1407)
    verbatim; everything they run through -- registration, CodeID resolution,
    the condition's own SetTarget body -- is production code. The range gates
    are built as ``ConditionInRange(fRange, sInitialTarget, pShip.GetName())``
    (NonFedAttack BuilderCreate17/26/31), so a retarget has to move
    ``sObject1``.
    """
    loop = nonfed_scene
    for _ in range(SETTLE_TICKS):
        loop.tick()

    gates = _nodes_named("CloseRange")
    assert gates, "no CloseRange nodes — scene did not build NonFedAttack"
    in_range = [c._instance for g in gates for c in g._conditions
                if type(getattr(c, "_instance", None)).__name__ == "ConditionInRange"]
    assert in_range, "no ConditionInRange instances under CloseRange"

    before = [c.sObject1 for c in in_range]
    assert any(before), "range conditions were built with no object to watch"

    selectors = _nodes_named("SelectTarget")
    assert selectors, "no SelectTarget preprocessors in the scene"
    for node in selectors:
        for pAI in node.GetAllAIsInTree()[1:]:
            pAI.CallExternalFunction("SetTarget", "Enemy-6")

    after = [c.sObject1 for c in in_range]
    assert after != before, (
        f"a SetTarget broadcast left every ConditionInRange still watching "
        f"{before[:3]}... The conditions never registered the hook, or the "
        "CodeID in the mapping resolves to nothing."
    )
    assert all(name == "Enemy-6" for name in after), after
