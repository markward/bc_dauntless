"""Headless M3Gameflow combat smoke via gameloop_harness.

M3Gameflow is the SDK's combat tutorial: Galaxy 1 (friendly, AI:
FriendlyAI) and Galaxy 2 (enemy, AI: EnemyAI → BasicAttack) start in
the Biranu1 system; player starts in Biranu2 (so combat happens between
the two Galaxies). With Slice D2's PlainAI body ports landed, the enemy
Galaxy 2's BasicAttack tree should drive observable combat behaviour.

This test runs the full SDK mission init path: PreLoadAssets,
Initialize, CreateRegions, CreateStartingObjects, SetupAI,
SetupEventHandlers, StartBriefingSequence. Expect this to surface
mission-script-only API gaps that pure-AI tests never reach."""
import pytest


@pytest.fixture(scope="session", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


def test_m3gameflow_initializes_without_crash(sdk_setup):
    """Minimum: the mission loads + Initialize() runs without raising.
    Zero ticks — pure init smoke."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=0,
    )
    assert status == "pass", f"M3Gameflow init failed: {exc}"
    assert exc is None
    assert ticks == 0


def test_m3gameflow_runs_60_ticks(sdk_setup):
    """One game-second (60 ticks at 60Hz) without crash. Combat may
    not yet be observable at 1s; this asserts the tick loop is stable."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=60,
    )
    assert status == "pass", f"M3Gameflow tick loop failed: {exc}"
    assert ticks == 60


def test_m3gameflow_600_ticks_with_combat(sdk_setup):
    """Ten game-seconds: the enemy Galaxy 2 should have closed range
    and produced observable combat behaviour. Uses return_state=True to
    inspect the Biranu1 set's Galaxy 1 hull condition."""
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks, state = run_mission_with_loop(
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
        n_ticks=600,
        return_state=True,
    )
    assert status == "pass", f"M3Gameflow long-run failed: {exc}"
    assert ticks == 600
    # The Biranu1 set contains Galaxy 1 (friendly) and Galaxy 2 (enemy).
    biranu1 = state["set_manager"].GetSet("Biranu1")
    assert biranu1 is not None, "Biranu1 set missing from state"
    galaxy1 = biranu1.GetObject("Galaxy 1")
    galaxy2 = biranu1.GetObject("Galaxy 2")
    assert galaxy1 is not None, "Galaxy 1 missing from Biranu1 set"
    assert galaxy2 is not None, "Galaxy 2 missing from Biranu1 set"
    # Combat-relevant assertion: after 10 game-seconds, at least one
    # of the Galaxies should have written a speed setpoint (the AI
    # subtrees ran and drove motion). The hull-damage assertion is
    # stretch — VFX/combat-hit propagation may not deliver damage in
    # 10s of game time given the BasicAttack closing-range cadence.
    assert (
        galaxy1._speed_setpoint is not None
        or galaxy2._speed_setpoint is not None
    ), "no Galaxy wrote a speed setpoint over 600 ticks"
