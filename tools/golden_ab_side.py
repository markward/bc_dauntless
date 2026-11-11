"""Run the golden A/B child (tests/helpers/golden_ab_child.py) in a source tree."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHILD_REL = Path("tests/helpers/golden_ab_child.py")
MODS_DIR_ENV = "DAUNTLESS_MODS_DIR"


class ChildError(Exception):
    def __init__(self, tail: str):
        super().__init__(tail)
        self.tail = tail


SDK_ENV = "DAUNTLESS_SDK_DIR"


def child_env(base_env: dict, data_dir) -> dict:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from engine import paths
    from tools import dev_sdk
    env = dict(base_env)
    env[paths.ENV_VARS["game"]] = str(paths.game_root())  # paths-guard: ENV_VARS key
    # The BASE commit may predate the no-SDK-runtime change and still read it
    # (spec 2026-11-11 decision 5), so hand it the developer's SDK root.
    env[SDK_ENV] = str(dev_sdk.sdk_root())
    env[paths.DATA_DIR_ENV] = str(data_dir)
    mods = Path(data_dir) / "no_mods"
    mods.mkdir(parents=True, exist_ok=True)
    env[MODS_DIR_ENV] = str(mods)
    return env


def inherited_dauntless_env(base_env: dict) -> list:
    """NAME=value for every DAUNTLESS_* variable the tool does not set itself."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from engine import paths
    own = {paths.ENV_VARS["game"], SDK_ENV,  # paths-guard: ENV_VARS key
           paths.DATA_DIR_ENV, MODS_DIR_ENV}
    return ["%s=%s" % (k, v) for k, v in sorted(base_env.items())
            if k.startswith("DAUNTLESS_") and k not in own]


def run_child(tree: Path, env: dict, out: Path) -> None:
    env = dict(env)
    env["GOLDEN_AB_OUT"] = str(out)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/helpers/golden_ab_child.py::test_child", "-q", "-x",
         "-p", "no:cacheprovider"],
        cwd=str(tree), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ChildError("%s\n%s" % (proc.stdout[-3000:], proc.stderr[-1500:]))


def list_scenes(tree: Path) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "scenes.json"
        env = child_env(os.environ, data_dir=tmp)
        env["GOLDEN_AB_LIST"] = "1"
        run_child(tree, env, out)
        return json.loads(out.read_text())


def run_scene_rows(tree: Path, scene: str) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "rows.z"
        env = child_env(os.environ, data_dir=tmp)
        env.pop("GOLDEN_AB_LIST", None)
        env["GOLDEN_AB_SCENE"] = scene
        run_child(tree, env, out)
        return json.loads(zlib.decompress(out.read_bytes()))


def install_child(tree: Path) -> None:
    dst = Path(tree) / CHILD_REL
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT_ROOT / CHILD_REL, dst)


def oldest_usable_commit():
    """Short hash of the first commit with `def run_scene` in golden_fight.py
    (it and `SCENES =` arrived together), or None if git can't say."""
    try:
        proc = subprocess.run(
            ["git", "log", "--reverse", "--format=%h", "-S" + "def run_scene",
             "--", "tests/helpers/golden_fight.py"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    except OSError:
        return None
    lines = proc.stdout.split() if proc.returncode == 0 else []
    return lines[0] if lines else None


def _too_old(what):
    oldest = oldest_usable_commit()
    hint = "; the oldest usable base is %s" % oldest if oldest else ""
    return "%s%s" % (what, hint)


def check_base_usable(tree: Path):
    path = Path(tree) / "tests/helpers/golden_fight.py"
    if not path.is_file():
        return _too_old("base tree has no tests/helpers/golden_fight.py")
    text = path.read_text()
    for piece in ("def run_scene", "SCENES ="):
        if piece not in text:
            return _too_old("base tests/helpers/golden_fight.py lacks %r" % piece)
    return None
