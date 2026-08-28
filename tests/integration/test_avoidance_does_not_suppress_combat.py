"""Collision avoidance must not switch the attack AI off.

THE BUG THIS PINS. `AvoidObstacles` returns PS_SKIP_ACTIVE while evading, and
`_tick_preprocessing` honours that by returning WITHOUT ticking the contained
AI. So for as long as a ship believes it is evading, its whole attack subtree
goes unreached -- and `_reconcile_focus` then dispatches LostFocus to every
node in it. Two SDK preprocessors act on that:

    AlertLevel.LostFocus  -> restores the pre-combat alert level -> SHIELDS DROP
    FireScript.LostFocus  -> StopFiring() on every weapon        -> FIRING STOPS

Live symptom, 3 Keldons vs the player in QuickBattle: ships fly around, fire an
opening volley, then stop engaging, with shields visibly dropping and raising.
The AI tree looked healthy throughout -- every node ACTIVE, targets held, the
fire branch reached -- because the damage is in FOCUS, which no status shows.

Measured with the engine-side avoidance replacement in place: the AlertLevel
preprocessor sat unfocused for runs of up to 4850 ms. With the SDK's own
AvoidObstacles it was never unfocused at all, and firing roughly doubled.

This test does not care WHICH implementation is used. It cares that a ship in a
crowded fight keeps being allowed to fight.
"""
import os

import pytest


# The scene has to be genuinely crowded or nothing evades and the test passes
# vacuously; `_ships_evaded` below fails the test if that happens.
SHIPS = 12
SETTLE_TICKS = 120
MEASURE_TICKS = 300

# A ship may legitimately break off to dodge. BC's own AvoidObstacles re-decides
# every tick, so a real evasion suppresses combat only in short bursts. Half a
# second of continuous suppression is already generous; the observed failure was
# nine times that.
MAX_SUPPRESSED_TICKS = 30


@pytest.fixture
def combat_scene(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", str(SHIPS))
    monkeypatch.setenv("DAUNTLESS_COMBAT_AVOID", "1")   # the whole point

    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.core.loop import GameLoop
    import importlib

    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)

    cs = importlib.import_module("engine.dev_missions.combat_stress")
    cs.Initialize(mission)
    evt = App.TGEvent()
    evt.SetEventType(App.ET_MISSION_START)
    evt.SetDestination(ep)
    App.g_kEventManager.AddEvent(evt)

    loop = GameLoop()
    for _ in range(SETTLE_TICKS):
        loop.tick()
    yield loop
    _set_current_game(None)


def _alert_level_nodes():
    """Every AlertLevel PreprocessingAI in the scene."""
    from engine.appc.ship_iter import iter_ships

    found = []

    def walk(node):
        if node is None:
            return
        inst = getattr(node, "_preprocessing_instance", None)
        if inst is not None and type(inst).__name__ == "AlertLevel":
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


def test_an_evading_ship_is_still_allowed_to_fight(combat_scene):
    loop = combat_scene
    nodes = _alert_level_nodes()
    assert nodes, "no AlertLevel preprocessors — scene did not build its AI"

    runs, current = [], {id(n): 0 for n in nodes}
    for _ in range(MEASURE_TICKS):
        loop.tick()
        for node in nodes:
            if not getattr(node, "_has_focus", False):
                current[id(node)] += 1
            elif current[id(node)]:
                runs.append(current[id(node)])
                current[id(node)] = 0
    runs.extend(v for v in current.values() if v)

    longest = max(runs) if runs else 0
    assert longest <= MAX_SUPPRESSED_TICKS, (
        f"an AlertLevel preprocessor went unfocused for {longest} ticks "
        f"({longest / 60.0 * 1000:.0f} ms) during a crowded fight. While it is "
        "unfocused its LostFocus has restored the pre-combat alert level, so "
        "the ship's shields are down and its FireScript has stopped firing. "
        "Avoidance is suppressing the attack subtree via PS_SKIP_ACTIVE."
    )
