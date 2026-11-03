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

which writes the file and skips. ``COMBAT_GOLDEN_ARM=python|native``
overrides a scene's arm (scenes 1-5 were recorded from the Python arm, then
checked native).
"""
import os

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine.appc import native_combat as nc
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
    golden_fight.record(name, rows, os.environ.get("COMBAT_GOLDEN_REASON"))
    golden_fight.check(name, rows)


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


# ── The recorder itself ──────────────────────────────────────────────────────

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
