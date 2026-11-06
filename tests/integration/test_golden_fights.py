"""Recorded golden fights: the reference fire control is checked against
(fire control native only, Task 1; spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md §4.2,
M7, R9, R10; the scenes and rows are KRM §5.5,
docs/reference/engine/native-combat/k1-retirement-map.md).

One test per scene (tests/helpers/golden_fight.py SCENES): it runs the
scene's arm and compares every tick with the recording in
tests/fixtures/golden_fights/<scene>.<sys.platform>.json.gz. A platform with
no recording skips, naming the missing file (R9).

Re-record ONLY on purpose, with a reason, one scene at a time where you can:

    UPDATE_COMBAT_GOLDEN=1 COMBAT_GOLDEN_REASON="<why>" \\
        uv run pytest tests/integration/test_golden_fights.py::<test>

which writes the file and skips. Every scene runs native, the only arm
since fire control's Python copy was deleted (Task 6, M3; a re-record's
header says so); scenes 1-5 were recorded from the Python arm, then checked
native. Each scene also asserts it had no no-fire and dropped no row
(k1_no_fire all zero: ruling R3). ``tractor_modes`` runs native only since tractors went
native (fire control native only, Task 3) and was re-recorded once for
ruling R8 (its events queued). ``sdk_dumb_fire`` runs native since the SDK's
FireDumb went native (Task 4, M8.1), against its Python recording,
unchanged. ``host_frames`` and ``host_frames_tpf1`` run real host frames
(``_run_frame_sim``), recorded in the batched order, then ``host_frames`` and
``k1_ops_tpf6`` re-recorded once for native motion phase 4's whole ticks
(ruling 2); ``host_frames_tpf1`` (one tick a frame, no ops) is the same
sequence in both orders, unchanged. ``motion_branches``, ``k1_gameloop_ai``,
``host_frames``, ``host_frames_tpf1``, ``sdk_dumb_fire`` and ``posed_fight``
were re-recorded once for the motion law (the impulse law on the velocity
and angular-rate vectors, turn-to, the real GetAccelerationTG): every moving
ship's pose changes from tick 1; ``motion_branches``' Python motion arm
still matches the native recording bit for bit. Those six were re-recorded
once more on main (schema 4) with kernel M steering the stored turn goals
and GetAccelerationTG the law's own output (docs/reference/engine/
motion-law.md); every golden scene asserts no ``TurnGoal`` hand-back.
The k1_ops, midwalk and tractor scenes run no motion stage (ships are
placed by ops), so they did not change.
"""
import os

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
from engine.appc import native_motion, native_subsystems
from tests.helpers import bc_assets
from tests.helpers import golden_fight

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


def _golden(name):
    arm = os.environ.get("COMBAT_GOLDEN_ARM") or golden_fight.SCENES[name].arm
    rows = golden_fight.run_scene(name, arm)
    # Before record: a scene with a hand-back is never recorded.
    _no_turn_goal_hand_backs()
    golden_fight.record(name, rows, os.environ.get("COMBAT_GOLDEN_REASON"))
    golden_fight.check(name, rows)
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
    _golden("k1_ops_tpf1")


def test_k1_ops_tpf6():
    _golden("k1_ops_tpf6")


def test_k1_gameloop_ai():
    _golden("k1_gameloop_ai")


def test_k1_midwalk_handler():
    _golden("k1_midwalk_handler")


def test_posed_fight():
    _golden("posed_fight")


def test_tractor_modes():
    _golden("tractor_modes")


def test_sdk_dumb_fire():
    _golden("sdk_dumb_fire")


def test_host_frames():
    """Real host frames (host_loop._run_frame_sim, headless) in whole
    ticks (ruling 2): each GameLoop tick, then its combat tick and boundary;
    the op stream through the patched _poll_fire_keys at frame start (native
    motion phase 4)."""
    _golden("host_frames")


def test_host_frames_tpf1():
    """The same frame path at one tick per frame, no ops."""
    _golden("host_frames_tpf1")


# ── The recorder itself ──────────────────────────────────────────────────────

def test_golden_arm_is_native_only():
    """A re-record is labelled with the arm it ran, and fire control is
    native in every arm (fire control native only, M3): asking for "python"
    fails loudly instead of recording native rows as Python's. The one
    other arm is the native arm with the motion stage in Python (native
    motion phase 2)."""
    on = golden_fight.k1d.ON
    assert golden_fight.ARMS == {
        "native": on,
        "python_motion": dict(on, DAUNTLESS_NATIVE_MOTION="0")}
    with pytest.raises(ValueError, match="native only"):
        golden_fight.run_scene("k1_ops_tpf1", "python")


def test_golden_missing_platform_skips(monkeypatch):
    """R9: a golden is compared only on the platform that recorded it; on
    any other the check skips with a message naming the missing file."""
    monkeypatch.setattr(golden_fight.sys, "platform", "golden-test-os")
    with pytest.raises(pytest.skip.Exception,
                       match=r"k1_ops_tpf1\.golden-test-os\.json\.gz"):
        golden_fight.check("k1_ops_tpf1", [])


def _tiny_rows():
    """Three ticks in run_scene's shape (no scene run)."""
    rows = []
    for t in range(3):
        state = [] if t == 0 else [
            ["weapon", "Player/Phaser 1", ["bool", True], "Enemy-1",
             ["float", float(t).hex()]],
            ["pose", "Player", ["0x0p+0"] * 3, ["0x1p+0"] * 9,
             ["0x0p+0"] * 3]]
        rows.append((t, state, [], [], [], [], []))
    return rows


def test_golden_round_trip_and_first_difference(monkeypatch, tmp_path):
    """record writes only under UPDATE_COMBAT_GOLDEN=1 (and skips), check
    passes the same rows, and a changed field fails naming its tick, row
    label and field."""
    monkeypatch.setattr(golden_fight, "FIXTURES", tmp_path)
    monkeypatch.setitem(golden_fight.SCENES, "tiny", golden_fight.Scene(
        name="tiny", arm="python", seed=1, ships="1", ticks=2, tpf=1,
        run=None))
    rows = _tiny_rows()
    monkeypatch.delenv("UPDATE_COMBAT_GOLDEN", raising=False)
    golden_fight.record("tiny", rows, "unused")       # inert without the env
    assert not list(tmp_path.iterdir())
    monkeypatch.setenv("UPDATE_COMBAT_GOLDEN", "1")
    with pytest.raises(pytest.fail.Exception, match="reason"):
        golden_fight.record("tiny", rows, None)
    with pytest.raises(pytest.skip.Exception, match="re-recorded"):
        golden_fight.record("tiny", rows, "unit test")
    monkeypatch.delenv("UPDATE_COMBAT_GOLDEN")
    header = golden_fight.header("tiny")
    assert header["reason"] == "unit test"
    assert header["platform"] == golden_fight.sys.platform
    assert header["ticks"] == 2 and header["schema"] == golden_fight.SCHEMA
    golden_fight.check("tiny", rows)
    bad = _tiny_rows()
    bad[2][1][0][4] = ["float", (2.5).hex()]
    with pytest.raises(AssertionError) as e:
        golden_fight.check("tiny", bad)
    msg = str(e.value)
    assert "tick 2" in msg and "'Player/Phaser 1'" in msg, msg
    assert "_fire_timer" in msg or "field 3" in msg, msg
    short = _tiny_rows()[:2]
    with pytest.raises(AssertionError, match="ticks"):
        golden_fight.check("tiny", short)
    # A field perturbed in the FILE (its digest left alone) fails too.
    data = golden_fight._load("tiny")
    data["ticks"] = golden_fight._decode(data["ticks"])
    data["ticks"][1][1][0][3] = "Enemy-2"
    data["ticks"] = golden_fight._encode(data["ticks"])
    with golden_fight.gzip.open(golden_fight.path("tiny"), "wt") as f:
        golden_fight.json.dump(data, f)
    with pytest.raises(AssertionError, match=r"tick 1.*field 2 _target"):
        golden_fight.check("tiny", rows)


def test_golden_schema_2_reads_without_baked_offset(monkeypatch, tmp_path):
    """A schema-2 golden (torpedo rows with `_baked_offset`, gone since fire
    control native only M5) is read by dropping that one field: the rest of
    the recorded row is compared as recorded, and the stored digests stay
    the recorded rows'."""
    monkeypatch.setattr(golden_fight, "FIXTURES", tmp_path)
    monkeypatch.setitem(golden_fight.SCENES, "tiny", golden_fight.Scene(
        name="tiny", arm="python", seed=1, ships="1", ticks=1, tpf=1,
        run=None))

    def torp(baked=True, damage="0x1p+0"):
        row = ["torpedo", "Torpedo@0", ["0x0p+0"] * 3, ["0x1p+0"] * 3,
               "Enemy-1", ["0x0p+0"] * 3]
        if baked:
            row.append(["Enemy-1", ["0x0p+0"] * 3, ["0x0p+0"] * 3])
        return row + [["float", damage], "Player", True]

    old = [[0, [], [], [], [], [], []], [1, [torp()], [], [], [], [], []]]
    data = {"header": {"scene": "tiny", "arm": "python", "seed": 1,
                       "ships": "1", "ticks": 1, "tpf": 1, "schema": 2,
                       "platform": golden_fight.sys.platform,
                       "reason": "schema 2"},
            "digests": [golden_fight._digest(r) for r in old],
            "ticks": golden_fight._encode(old)}
    with golden_fight.gzip.open(golden_fight.path("tiny"), "wt") as f:
        golden_fight.json.dump(data, f)
    now = [(0, [], [], [], [], [], []),
           (1, [torp(baked=False)], [], [], [], [], [])]
    golden_fight.check("tiny", now)
    bad = [(0, [], [], [], [], [], []),
           (1, [torp(baked=False, damage="0x1p+1")], [], [], [], [], [])]
    with pytest.raises(AssertionError, match="field 5 _damage"):
        golden_fight.check("tiny", bad)


def test_motion_branches():
    """Native motion (the switch's default): kernel M flew the stage."""
    _golden("motion_branches")
    counts = native_motion.counts()
    assert counts["native_calls"] > 0, counts
    assert counts["patched_stages"] == 0, counts


def test_motion_branches_python_motion_arm():
    """The same scene with the motion stage in Python
    (DAUNTLESS_NATIVE_MOTION=0), against the one Python recording: both
    arms equal it (native motion phase 2, Task 5)."""
    rows = golden_fight.run_scene("motion_branches", "python_motion")
    assert native_motion.counts()["native_calls"] == 0
    golden_fight.check("motion_branches", rows)
    _no_subsystem_skips()
