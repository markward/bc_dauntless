"""Golden-fight scenes: the reference fights fire control is exercised by
(fire control native only, Task 1; spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md §4.2,
M7, R10; the scenes and rows are KRM §5.5,
docs/reference/engine/native-combat/k1-retirement-map.md).

One test per scene (tests/helpers/golden_fight.py SCENES): it runs the
scene's arm and asserts the invariants that must hold on any commit and
platform: one row per tick (plus tick 0), no no-fire and no dropped row
(k1_no_fire all zero: ruling R3), no ``TurnGoal`` hand-back to Python and no
skipped subsystem-stage piece.

The scenes are code; nothing is recorded. The golden A/B tool compares a
scene's rows across commits, and ``test_motion_branches_python_motion_arm``
compares the native motion arm with the Python motion arm live, in one
process.
"""

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
from engine.appc import native_motion, native_subsystems
from tests.helpers import bc_assets
from tests.helpers import golden_fight, golden_rows

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()


def _invariants(name):
    rows = golden_fight.run_scene(name, golden_fight.SCENES[name].arm)
    assert len(rows) == golden_fight.SCENES[name].ticks + 1, (
        name, len(rows))
    _no_turn_goal_hand_backs()
    _no_subsystem_skips()


def _no_turn_goal_hand_backs():
    """Kernel M steers every stored turn goal itself: no row went back to
    Python for one (PR #14 finish, Task 2). Vacuous for posed_fight:
    PosedFight resets native_combat (and with it these counters) as it
    builds the scene and its ticks never run the motion stage, so its counts
    read zero; the real guards are motion_branches and k1_gameloop_ai."""
    rows = native_motion.counts()["python_rows"]
    assert rows.get("TurnGoal", 0) == 0, rows


def _no_subsystem_skips():
    """The native subsystem stage ran every piece of the scene: nothing was
    skipped (subsystem_step.h THE SKIPS; Task 8 ruling R8-1)."""
    assert native_subsystems.counts()["stages"] > 0
    assert native_subsystems.skip_counts() == {}


def test_k1_ops_tpf1():
    _invariants("k1_ops_tpf1")


def test_k1_ops_tpf6():
    _invariants("k1_ops_tpf6")


def test_k1_gameloop_ai():
    _invariants("k1_gameloop_ai")


def test_k1_midwalk_handler():
    _invariants("k1_midwalk_handler")


def test_posed_fight():
    _invariants("posed_fight")


def test_tractor_modes():
    _invariants("tractor_modes")


def test_sdk_dumb_fire():
    _invariants("sdk_dumb_fire")


def test_host_frames():
    """Real host frames (host_loop._run_frame_sim, headless) in whole
    ticks (ruling 2): each GameLoop tick, then its combat tick and boundary;
    the op stream through the patched _poll_fire_keys at frame start (native
    motion phase 4)."""
    _invariants("host_frames")


def test_host_frames_tpf1():
    """The same frame path at one tick per frame, no ops."""
    _invariants("host_frames_tpf1")


# ── The arms, and no recordings ──────────────────────────────────────────────

def test_golden_arm_is_native_only():
    """Fire control is native in every arm (fire control native only, M3):
    asking for "python" fails loudly instead of running native rows as
    Python's. The one
    other arm is the native arm with the motion stage in Python (native
    motion phase 2)."""
    on = golden_fight.k1d.ON
    assert golden_fight.ARMS == {
        "native": on,
        "python_motion": dict(on, DAUNTLESS_NATIVE_MOTION="0")}
    with pytest.raises(ValueError, match="native only"):
        golden_fight.run_scene("k1_ops_tpf1", "python")


def test_motion_branches():
    """Native motion (the switch's default): kernel M flew the stage."""
    _invariants("motion_branches")
    counts = native_motion.counts()
    assert counts["native_calls"] > 0, counts
    assert counts["patched_stages"] == 0, counts


def test_motion_branches_python_motion_arm():
    """The same scene with the motion stage in Python
    (DAUNTLESS_NATIVE_MOTION=0) against the native motion arm, live in one
    process: kernel M is bit-exact with the Python reference (native motion
    phase 2, Task 5)."""
    nat = golden_fight.run_scene("motion_branches", "native")
    py = golden_fight.run_scene("motion_branches", "python_motion")
    assert native_motion.counts()["native_calls"] == 0
    assert len(nat) == len(py)
    for t in range(len(nat)):
        msg = golden_rows.row_difference(t, nat[t], py[t])
        assert msg is None, msg
    _no_subsystem_skips()
