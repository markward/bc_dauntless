"""tools/golden_ab_side.py: launching the golden A/B child in a tree.

subprocess.run is monkeypatched: no scene ever runs here."""
import json
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from engine import paths
from tools import golden_ab_side as side


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_child_env_points_at_resolved_roots():
    env = side.child_env({"KEEP": "1"})
    assert env["KEEP"] == "1"
    assert env[paths.ENV_VARS["game"]] == str(paths.game_root())  # paths-guard: ENV_VARS key
    assert env[paths.ENV_VARS["sdk"]] == str(paths.sdk_root())  # paths-guard: ENV_VARS key
    assert Path(env[paths.DATA_DIR_ENV]).is_dir()
    assert side.child_env({})[paths.DATA_DIR_ENV] != env[paths.DATA_DIR_ENV]


def test_run_child_raises_with_tail(monkeypatch, tmp_path):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return _Proc(1, "boom", "bang")
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(side.ChildError) as e:
        side.run_child(tmp_path, {"X": "1"}, tmp_path / "out")
    assert "boom" in e.value.tail and "bang" in e.value.tail
    assert seen["cmd"] == [sys.executable, "-m", "pytest",
                           "tests/helpers/golden_ab_child.py::test_child",
                           "-q", "-x", "-p", "no:cacheprovider"]
    assert seen["kw"]["cwd"] == str(tmp_path)
    assert seen["kw"]["env"]["GOLDEN_AB_OUT"] == str(tmp_path / "out")


def test_list_scenes_and_run_scene_rows(monkeypatch, tmp_path):
    def fake(cmd, **kw):
        env = kw["env"]
        out = Path(env["GOLDEN_AB_OUT"])
        if env.get("GOLDEN_AB_LIST"):
            out.write_text(json.dumps(["a", "b"]))
        else:
            assert env["GOLDEN_AB_SCENE"] == "a"
            out.write_bytes(zlib.compress(b'[[1,[]],[2,[]]]'))
        return _Proc(0)
    monkeypatch.setattr(subprocess, "run", fake)
    assert side.list_scenes(tmp_path) == ["a", "b"]
    assert side.run_scene_rows(tmp_path, "a") == [[1, []], [2, []]]


def test_check_base_usable(tmp_path):
    h = tmp_path / "tests" / "helpers"
    h.mkdir(parents=True)
    assert side.check_base_usable(tmp_path)
    (h / "golden_fight.py").write_text("SCENES = {}\n")
    assert "def run_scene" in side.check_base_usable(tmp_path)
    (h / "golden_fight.py").write_text("def run_scene(n, a):\n    pass\n")
    assert "SCENES =" in side.check_base_usable(tmp_path)
    (h / "golden_fight.py").write_text("SCENES = {}\ndef run_scene(n, a):\n    pass\n")
    assert side.check_base_usable(tmp_path) is None


def test_install_child_copies_into_tree(tmp_path):
    side.install_child(tmp_path)
    dst = tmp_path / "tests" / "helpers" / "golden_ab_child.py"
    src = Path(side.__file__).resolve().parents[1] / "tests/helpers/golden_ab_child.py"
    assert dst.read_bytes() == src.read_bytes()
