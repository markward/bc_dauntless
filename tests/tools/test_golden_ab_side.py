"""tools/golden_ab_side.py: launching the golden A/B child in a tree.

subprocess.run is monkeypatched: no scene ever runs here."""
import json
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from engine import paths
from tools import dev_sdk  # reads SDK source as reference data (spec 2026-11-11 decision 5)
from tools import golden_ab_side as side


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_child_env_points_at_resolved_roots(tmp_path):
    env = side.child_env({"KEEP": "1"}, tmp_path / "a")
    assert env["KEEP"] == "1"
    assert env[paths.ENV_VARS["game"]] == str(paths.game_root())  # paths-guard: ENV_VARS key
    assert env["DAUNTLESS_SDK_DIR"] == str(dev_sdk.sdk_root())
    assert Path(env[paths.DATA_DIR_ENV]).is_dir()
    assert side.child_env({}, tmp_path / "b")[paths.DATA_DIR_ENV] \
        != env[paths.DATA_DIR_ENV]


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


def test_child_env_uses_given_data_dir(tmp_path):
    env = side.child_env({}, data_dir=tmp_path)
    assert env[paths.DATA_DIR_ENV] == str(tmp_path)
    mods = Path(env["DAUNTLESS_MODS_DIR"])
    assert mods.is_dir() and mods.parent == tmp_path


def test_child_env_overrides_inherited_mods_dir(tmp_path):
    env = side.child_env({"DAUNTLESS_MODS_DIR": "/real/mods"}, tmp_path)
    assert env["DAUNTLESS_MODS_DIR"] != "/real/mods"


def test_inherited_dauntless_env_skips_what_the_tool_sets():
    base = {"DAUNTLESS_PASSIVE_STATE": "0", "PATH": "/bin",
            "DAUNTLESS_MODS_DIR": "/m", "DAUNTLESS_DATA_DIR": "/d",
            paths.ENV_VARS["game"]: "/g", "DAUNTLESS_SDK_DIR": "/s"}  # paths-guard: ENV_VARS key
    assert side.inherited_dauntless_env(base) == ["DAUNTLESS_PASSIVE_STATE=0"]
    assert side.inherited_dauntless_env({"PATH": "/bin"}) == []


def test_check_base_usable_names_oldest_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(side, "oldest_usable_commit", lambda: "abc1234")
    assert "abc1234" in side.check_base_usable(tmp_path)


def test_oldest_usable_commit_in_this_repo_is_a_hash():
    got = side.oldest_usable_commit()
    assert got is None or len(got) >= 7


def test_child_row_writer_round_trips(tmp_path):
    from tests.helpers import golden_ab_child as child
    for rows in ([], [[1, ["a", 0.5]], [2, []]]):
        out = tmp_path / "r.z"
        child._write_rows(str(out), rows)
        assert json.loads(zlib.decompress(out.read_bytes())) == rows


def test_child_fails_instead_of_skipping_when_out_is_set(monkeypatch, tmp_path):
    from tests.helpers import bc_assets, golden_ab_child as child
    monkeypatch.setenv("GOLDEN_AB_OUT", str(tmp_path / "o"))
    monkeypatch.delenv("GOLDEN_AB_LIST", raising=False)
    monkeypatch.setattr(bc_assets, "require_game_dir",
                        lambda rel: pytest.skip("BC assets not available: x/"))
    with pytest.raises(pytest.fail.Exception, match="BC assets not available"):
        child.test_child()
