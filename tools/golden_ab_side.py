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


class ChildError(Exception):
    def __init__(self, tail: str):
        super().__init__(tail)
        self.tail = tail


def child_env(base_env: dict, data_dir=None) -> dict:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from engine import paths
    env = dict(base_env)
    env[paths.ENV_VARS["game"]] = str(paths.game_root())  # paths-guard: ENV_VARS key
    env[paths.ENV_VARS["sdk"]] = str(paths.sdk_root())  # paths-guard: ENV_VARS key
    env[paths.DATA_DIR_ENV] = (str(data_dir) if data_dir is not None
                               else tempfile.mkdtemp(prefix="golden_ab_data"))
    return env


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


def check_base_usable(tree: Path):
    path = Path(tree) / "tests/helpers/golden_fight.py"
    if not path.is_file():
        return "base tree has no tests/helpers/golden_fight.py"
    text = path.read_text()
    for piece in ("def run_scene", "SCENES ="):
        if piece not in text:
            return "base tests/helpers/golden_fight.py lacks %r" % piece
    return None
