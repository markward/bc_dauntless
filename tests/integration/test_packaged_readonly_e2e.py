"""A packaged build writes only to the per-user folders (plan Task 13).

Builds a read-only install from this checkout (tests/helpers/packaged_layout),
then runs real engine code from it in a child interpreter with HOME pointed at
a temp dir. Every user-data write must land under the per-OS folders, the log
tee must capture stderr, no bytecode may be written, and the install's tree
digest must not change.

Windows (Ruling 2): the driver replaces paths._windows_known_folder with a
function returning None, so the APPDATA / LOCALAPPDATA fallback (under the temp
home) is used and the developer's real AppData is never touched. The package
is therefore imported by hand on win32, because `import engine` starts the log
tee, which asks for the log folder before any patch could be applied.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine import paths
from tests.helpers import packaged_layout

DRIVER = r'''
import json, os, sys, types, importlib.util
install, result_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, install)
build_python = os.path.join(install, "build", "python")
if os.environ.get("E2E_BUILD_PYTHON"):
    sys.path.append(os.environ["E2E_BUILD_PYTHON"])

if sys.platform == "win32":
    pkg = types.ModuleType("engine")
    pkg.__path__ = [os.path.join(install, "engine")]
    pkg.__file__ = os.path.join(install, "engine", "__init__.py")
    sys.modules["engine"] = pkg
    from engine import paths as _paths
    _paths._windows_known_folder = lambda name: None
    with open(pkg.__file__, encoding="utf-8") as fh:
        exec(compile(fh.read(), pkg.__file__, "exec"), pkg.__dict__)

import engine
from engine import paths, mods
result = {"engine_file": engine.__file__, "packaged": paths.is_packaged(),
          "dont_write_bytecode": sys.dont_write_bytecode, "skipped": []}

from engine.settings_store import SettingsStore
SettingsStore().set("e2e", "key", 1)

from engine import bridge_selection
bridge_selection.load_bridge_pins().store.set("e2e", "key", "x")

from engine.quickbattle import presets, scenario
presets.load_presets().save("e2e preset", scenario.default_scenario())

from engine.appc.config_mapping import TGConfigMapping
cfg = TGConfigMapping()
cfg.SetStringValue("E2E", "key", "v")
result["options_cfg"] = cfg.SaveConfigFile("Options.cfg")

from engine.input_map import InputMap
result["input_map"] = InputMap().save()

from engine.appc.save_load import SaveLoadManager
from engine.core.game import Game, Episode, Mission, _set_current_game
episode = Episode()
episode.SetCurrentMission(Mission())
game = Game()
game.SetCurrentEpisode(episode)
_set_current_game(game)
mgr = SaveLoadManager()
result["save_to_file"] = mgr.SaveToFile("saves//Captain Save-E1M1Test.BCS")
mgr._current_mission_module = lambda: "Maelstrom.Episode1.E1M1"
result["save_mission_state"] = mgr.SaveMissionState()
result["load_missing"] = mgr.LoadFromFile("saves//Missing-E1M1Nothing.BCS")

from engine.ui import icon_tracer, weapon_icons, damage_icons
for mod, sub in ((weapon_icons, "weapons"), (damage_icons, "damage")):
    if not icon_tracer._potrace_available():
        result["skipped"].append(sub + ": potrace not installed")
        continue
    num = sorted(mod.ICON_REGISTRY)[0]
    spec = mod.ICON_REGISTRY[num]
    if not os.path.isfile(str(mod._game_icon_file(os.path.splitext(spec.tga)[0]))):
        result["skipped"].append(sub + ": source TGA %s not found" % spec.tga)
        continue
    mod._CURATED_DIR = os.path.join(install, "no-curated-svgs")
    mod.reset_cache()
    result[sub + "_icon"] = [num, mod.icon_svg_for_num(num) is not None]

from engine.core import stub_telemetry
stub_telemetry.persist_run()

result["structure_parts_cache_root"] = str(paths.structure_parts_cache_root())
result["mods_root"] = str(mods.mods_root())
sys.stderr.write("E2E-STDERR-MARKER-LINE\n")
with open(result_path, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
'''


def _inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def test_packaged_build_writes_only_to_user_folders(tmp_path):
    install = packaged_layout.build(tmp_path / "install")
    home = tmp_path / "home"
    home.mkdir()
    result_path = tmp_path / "result.json"
    build_python = paths.PROJECT_ROOT / "build" / "python"
    game_root, sdk_root = paths.game_root(), paths.sdk_root()

    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("XDG_", "PYTHON", "DAUNTLESS_"))
           and k not in ("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE")}
    env.update(HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"),
               DAUNTLESS_GAME_DIR=str(game_root),
               DAUNTLESS_SDK_DIR=str(sdk_root))
    if build_python.is_dir():
        env["E2E_BUILD_PYTHON"] = str(build_python)
    assert "DAUNTLESS_DATA_DIR" not in env and "DAUNTLESS_MODS_DIR" not in env

    before = packaged_layout.tree_digest(install)
    packaged_layout.make_readonly(install)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", DRIVER, str(install), str(result_path)],
            cwd=install, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        after = packaged_layout.tree_digest(install)
    finally:
        packaged_layout.restore_writable(install)

    output = proc.stdout
    assert proc.returncode == 0, output
    assert "[dauntless] could not write" not in output, output
    assert after == before, "the install folder changed"

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert _inside(result["engine_file"], install), result["engine_file"]
    assert result["packaged"] is True
    assert result["dont_write_bytecode"] is True
    assert not list(Path(install).rglob("__pycache__"))

    dirs = paths.os_user_dirs(home=home) if sys.platform != "win32" else \
        paths.os_user_dirs(platform="win32", home=home, env=env,
                           known_folder=lambda name: None)
    expected = [
        dirs["config"] / "settings.json",
        dirs["config"] / "bridges.json",
        dirs["config"] / "quickbattle_presets.json",
        dirs["config"] / "Options.cfg",
        dirs["config"] / "Keybindings.cfg",
        dirs["saves"] / "Captain Save-E1M1Test.BCS",
        dirs["saves"] / "missions" / "Maelstrom.Episode1.E1M1.json",
        dirs["logs"] / "stub_hits.jsonl",
        dirs["logs"] / "dauntless.log",
    ]
    for key in ("options_cfg", "input_map", "save_to_file", "save_mission_state"):
        assert result[key] == 1, (key, result[key])
    assert result["load_missing"] == 0
    for path in expected:
        assert path.is_file(), "missing %s" % path
        assert not _inside(path, install)

    log = (dirs["logs"] / "dauntless.log").read_text(encoding="utf-8")
    assert "E2E-STDERR-MARKER-LINE" in log

    assert (Path(result["structure_parts_cache_root"])
            == dirs["cache"] / "structure_parts")
    assert Path(result["mods_root"]) == dirs["mods"]

    for sub in ("weapons", "damage"):
        if sub + "_icon" in result:
            num, ok = result[sub + "_icon"]
            assert ok
            assert (dirs["cache"] / "icons" / sub / ("%d.svg" % num)).is_file()

    # Nothing outside the temp home and the (read-only) install was written.
    stray = [p for p in tmp_path.rglob("*")
             if not _inside(p, install) and not _inside(p, home)
             and p != result_path]
    assert stray == []

    if result["skipped"]:
        pytest.skip("icon sub-check skipped (everything else passed): "
                    + "; ".join(result["skipped"]))
