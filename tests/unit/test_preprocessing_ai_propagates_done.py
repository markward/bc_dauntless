"""A PreprocessingAI must report its contained AI's completion.

Every player helm order is a PreprocessingAI wrapping the real work --
AI/Player/InterceptTarget.py:24-29 wraps `Intercept` in `AvoidObstacles`, and
OrbitPlanet, FollowObject and friends have the same shape (the orbit tests
assert the root's name is "OrbitAvoidObstacles"). So if the wrapper swallows
its contained AI's US_DONE, no player order can ever finish.

It did. `_tick_preprocessing` ended:

    ai._status = US_ACTIVE
    if ai._contained_ai is not None:
        tick_ai(ai._contained_ai, game_time)
    return ai._status

-- dispatching the contained AI and then discarding its status.

Live symptom, and what it cost, simulated against the real SDK AI and E1M1's
real placements: order an intercept on the Starbase 12 nav point and the
`Intercept` leaf returns US_DONE correctly, at 3.207 GU from the point. The
root PreprocessingAI stays US_ACTIVE forever. So ET_AI_DONE never fires (Helm
never returns to "Waiting"), the AI is never released, and `_tick_plain`
early-returns for the finished leaf -- no further SetSpeed, no further
TurnTowardLocation. The ship sails straight through the nav point and keeps
going: 126.71 km out and climbing, at 3059 kph, 200 s later.

`_tick_conditional` already carries exactly this fold, added for the same
reason and with the same shape (ai_driver.py:552). This is its missing twin.
"""
import App
import pytest
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ai_driver import tick_ai, US_ACTIVE, US_DONE
from engine.appc.ships import ShipClass


class _Preprocessor:
    """A preprocessor that stays out of the way, like the AvoidObstacles
    wrapper does when there is nothing to avoid."""

    def __init__(self, result=None):
        self._result = App.PreprocessingAI.PS_NORMAL if result is None else result
        self.calls = 0

    def Update(self, _end_time):
        self.calls += 1
        return self._result


class _Leaf:
    """Contained AI script: runs `active_for` updates, then finishes -- the
    shape of Intercept, which returns US_DONE the tick it arrives."""

    def __init__(self, active_for=1):
        self._left = active_for
        self.updates = 0

    def Update(self):
        self.updates += 1
        if self._left > 0:
            self._left -= 1
            return US_ACTIVE
        return US_DONE

    def GetNextUpdateTime(self):
        return 0.0


def _order(ship, leaf, preprocessor=None):
    """The wrapper-around-leaf tree every AI/Player/* order builds."""
    inner = PlainAI_Create(ship, "Intercept")
    inner.GetScriptInstance()   # realize the instance before we swap it in
    inner._script_instance = leaf
    outer = PreprocessingAI_Create(ship, "AvoidObstacles")
    outer.SetPreprocessingMethod(preprocessor or _Preprocessor(), "Update")
    outer.SetContainedAI(inner)
    return outer, inner


def _run(ai, ticks, start=0.0):
    """Tick like the host loop does: repeatedly, with advancing game time."""
    statuses = []
    t = start
    for _ in range(ticks):
        statuses.append(tick_ai(ai, t))
        t += 1.0
    return statuses


def test_wrapper_reports_done_once_the_contained_ai_finishes():
    """THE defect: the order completes, the wrapper must say so."""
    ship = ShipClass()
    outer, inner = _order(ship, _Leaf(active_for=1))

    statuses = _run(outer, 3)

    assert inner._status == US_DONE
    assert statuses[-1] == US_DONE
    assert outer._status == US_DONE


def test_wrapper_stays_active_while_the_contained_ai_is_working():
    """The other half of the branch: an order in progress must NOT read as
    finished, or every order would end on its first tick."""
    ship = ShipClass()
    outer, inner = _order(ship, _Leaf(active_for=5))

    statuses = _run(outer, 3)

    assert inner._status == US_ACTIVE
    assert all(s == US_ACTIVE for s in statuses)
    assert outer._status == US_ACTIVE


def test_wrapper_with_no_contained_ai_is_unaffected():
    """A bare preprocessor (no contained AI) has nothing to fold in and must
    keep reporting active."""
    ship = ShipClass()
    outer = PreprocessingAI_Create(ship, "AvoidObstacles")
    outer.SetPreprocessingMethod(_Preprocessor(), "Update")

    assert tick_ai(outer, 0.0) == US_ACTIVE


def test_preprocessor_still_runs_on_the_tick_the_contained_ai_finishes():
    """Folding in the contained status must not short-circuit the
    preprocessor -- it is what keeps the ship off obstacles right up to the
    end of the order."""
    ship = ShipClass()
    pre = _Preprocessor()
    outer, _inner = _order(ship, _Leaf(active_for=1), preprocessor=pre)

    _run(outer, 2)

    assert pre.calls == 2


def _run_pump(ship, ticks=3):
    """Drive the real host-loop AI pump over a registered set."""
    from engine.appc import ai_driver
    from engine.appc.sets import SetClass_Create

    s = SetClass_Create()
    s.AddObjectToSet(ship, "player")
    App.g_kSetManager.AddSet(s, "test_done_set")
    try:
        for t in range(ticks):
            ai_driver.tick_all_ai(float(t))
    finally:
        App.g_kSetManager.RemoveSet("test_done_set")


def test_finished_ai_is_released_from_the_ship():
    """Propagating US_DONE is only half the job. BC tears a finished AI down —
    US_DONE -> LostFocus -> SetInactive -> unlink + delete (the binary note at
    ai_driver.py:801). Left attached, the finished tree keeps the conn:
    _PlayerControl.apply arbitrates on `if ai is not None:` with no status
    check, so it skips the entire ship-motion path — throttle included — and
    the ship coasts on the AI's last SetSpeed forever. That is the live
    symptom: impulse notch reads 0, ship holds ~3000 kph, sails past the nav
    point and never comes back."""
    ship = ShipClass()
    outer, _inner = _order(ship, _Leaf(active_for=1))
    ship.SetAI(outer)

    _run_pump(ship)

    assert ship.GetAI() is None


def test_releasing_a_finished_ai_must_not_clobber_its_replacement():
    """A completion script may hand the ship its NEXT orders as its last act,
    and the release must not destroy them.

    That is a real, load-bearing SDK idiom, not a corner case:
    AI/Compound/DockWithStarbase.FinishedUndocking ends with

        # And set the ship to coast out at impulse 2, replacing this AI.
        MissionLib.SetPlayerAI("Helm", AI.Player.FlyForward.CreateWithAvoid(...))

    so by the time the DockingSequence reports US_DONE, the ship is already
    carrying FlyForward. Clearing unconditionally wiped it -- live symptom
    after undocking from Starbase 12: the AI Inspector shows the player with
    "(no AI)", the ship never coasts clear of the starbase, and the mission
    does not move on.

    Nothing is left dangling by skipping the clear: ShipClass.SetAI already
    deactivates the outgoing tree and announces it (ships.py:132-138), which is
    also why this must not fire a second ET_AI_DONE."""
    from engine.appc import ai_driver

    received = []

    def _on_done2(_dest, event):
        received.append(event.GetInt())

    globals()["_on_done2"] = _on_done2
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_AI_DONE, None, __name__ + "._on_done2")

    ship = ShipClass()
    replacement = PlainAI_Create(ship, "FlyForward")

    class _HandsOverLeaf(_Leaf):
        def Update(self):
            status = _Leaf.Update(self)
            if status == US_DONE:
                ship.SetAI(replacement)     # what FinishedUndocking does
            return status

    outer, _inner = _order(ship, _HandsOverLeaf(active_for=1))
    ship.SetAI(outer)

    _run_pump(ship)

    assert ship.GetAI() is replacement, "the release destroyed the new orders"
    # Exactly one announcement, from SetAI's own teardown of the old tree.
    assert received == [outer.GetID()]


def test_an_unfinished_ai_keeps_the_conn():
    """The guard on the above: an order still running must NOT be released, or
    every order would be cancelled on its first tick."""
    ship = ShipClass()
    outer, _inner = _order(ship, _Leaf(active_for=99))
    ship.SetAI(outer)

    _run_pump(ship)

    assert ship.GetAI() is outer


def test_done_wrapper_fires_et_ai_done_through_the_host_pump():
    """What the propagation is FOR. tick_all_ai fires ET_AI_DONE only on a
    US_DONE root; the SDK's HelmCharacterHandlers.AIDone is what returns the
    Helm officer to "Waiting", and the engine is what releases the conn."""
    from engine.appc import ai_driver
    from engine.appc.sets import SetClass_Create

    received = []

    def _on_done(_dest, event):
        received.append(event.GetInt())

    globals()["_on_done"] = _on_done
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_AI_DONE, None, __name__ + "._on_done")

    ship = ShipClass()
    outer, _inner = _order(ship, _Leaf(active_for=1))
    ship.SetAI(outer)

    _run_pump(ship)

    # EXACTLY once. Both the pump and ClearAI can announce an ended tree, so
    # this pins that releasing the AI does not double-fire: BC's Helm officer
    # would drop to "Waiting" twice, and every ET_AI_DONE handler keyed on the
    # id would run twice.
    assert received == [outer.GetID()]


def test_a_self_completing_order_hands_the_conn_back_and_the_ship_slows():
    """The whole point, end to end: an order that finishes ON ITS OWN must
    return the ship to the player's throttle.

    tests/unit/test_player_ai_motion_handoff.py already covers the resume ramp
    for an order the player CANCELS (ClearAI). This pins the seam that was
    missing — an order nobody cancels, that simply completes. Without it the
    ship held the AI's last commanded speed indefinitely: the live symptom of
    flying through the Starbase 12 nav point at ~3000 kph with the impulse
    notch reading 0.
    """
    from engine.appc.math import TGPoint3
    from engine.appc.objects import PhysicsObjectClass
    from engine.appc.ship_motion import _step_ship_motion
    from engine.appc.subsystems import ImpulseEngineSubsystem
    from tests.unit.test_player_ai_motion_handoff import _Host, _PlayerControl

    dt = 1.0 / 60.0
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(10.0)
    ies.SetMaxAccel(2.0)
    ies.SetMaxAngularVelocity(2.0)
    ies.SetMaxAngularAccel(1.0)
    ship.SetImpulseEngineSubsystem(ies)

    pc = _PlayerControl()
    # One host for the whole run: _Keys hands out a code per NEW name from a
    # class-level counter, so a fresh _Host per tick would exhaust it.
    host = _Host()
    outer, _inner = _order(ship, _Leaf(active_for=1))
    ship.SetAI(outer)
    pc.apply(ship, dt, host)                  # latch AI ownership

    # The order is under way at speed, as an intercept run-in would be.
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0),
                  PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    ship._current_speed = 5.0
    _step_ship_motion(ship, dt)
    assert ship.GetVelocity().y == pytest.approx(5.0)

    # Let it finish, then keep flying with the player's throttle at 0.
    _run_pump(ship)
    assert ship.GetAI() is None

    for _ in range(600):                      # 10 s
        pc.apply(ship, dt, host)
        _step_ship_motion(ship, dt)

    assert pc.impulse_level == 0              # player never touched the throttle
    # Effectively stopped: 5.0 GU/s (3150 kph) down to under 0.01 GU/s (6 kph),
    # the ramp asymptote. Pre-fix it held all 5.0 indefinitely, because a
    # done-but-attached AI kept apply() from ever reaching the throttle.
    assert ship.GetVelocity().y < 0.01

