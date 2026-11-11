"""Missions and a `.pyc`-only mod load headless with NO SDK reachable.

Every developer machine has the BC SDK, and the test suite itself pins it
(tests/conftest.py sets DAUNTLESS_SDK_DIR and registers the SDK's
Custom/Tutorial sample as a fixture tree). So the "the game never reads the
SDK" claim (spec docs/superpowers/specs/2026-11-11-no-sdk-runtime-design.md)
can only be proved in a CHILD interpreter that never loads conftest:

* env: os.environ minus DAUNTLESS_SDK_DIR, DAUNTLESS_GAME_DIR set,
  DAUNTLESS_DATA_DIR a temp dir (no settings.json, so no [paths].sdk);
* cwd: a temp dir;
* the child first proves its own environment has no SDK: the developer SDK
  chain (tools/dev_sdk.sdk_root) must raise DevSdkMissing.

Provenance is asserted on `module.__spec__.origin` and on the code objects'
`co_filename`, never on `__file__` alone: SDK-loaded modules are bare
ModuleSpecs with no `__file__`, so a `__file__` check passes vacuously
(ruling R7). The dev SDK root is resolved HERE, in the parent, and handed to
the child, which refuses any module whose origin lies under it or spells an
SDK layout (`Build/scripts`).

The mod test reads the LC Intrepid pack from the project's gitignored mods/
and skips without it, like tests/unit/test_lc_intrepid_pyc_projectiles.py.
"""
import os
import subprocess
import sys

import pytest

from engine import mods, paths
from tools import dev_sdk

PROJECT_ROOT = paths.PROJECT_ROOT
INTREPID = PROJECT_ROOT / "mods" / "LC Intrepid Pack"
INTREPID_SCRIPTS = ("Tactical.Projectiles.ZZ_VoyPhoton",
                    "Tactical.Projectiles.ZZ_Tricobalt")
MISSIONS = ("Maelstrom.Episode1.E1M1.E1M1", "QuickBattle.QuickBattle")
TICKS = 120

# The child. argv: mode, game root, dev SDK root, then the mode's names.
CHILD = r'''
import os, sys, types
from pathlib import Path

mode, game_root, sdk_root = sys.argv[1], sys.argv[2], sys.argv[3]
names = sys.argv[4:]

# 1. This environment really has no SDK: env var gone, no settings.json,
#    and the in-project SDK folder (if a checkout has one) taken out of the
#    chain -- the game never calls dev_sdk; any SDK layout it reached anyway
#    is caught by the provenance check below.
assert "DAUNTLESS_SDK_DIR" not in os.environ
from tools import dev_sdk
dev_sdk.PROJECT_ROOT = Path(os.getcwd())
try:
    found = dev_sdk.sdk_root()
except dev_sdk.DevSdkMissing:
    pass
else:
    raise AssertionError("the child can still reach an SDK: %s" % found)

# 2. Boot the way the game does: resolve the game root (no store), check
#    the install, install the loader, install the mods.
from engine import paths, stock_scripts, mods
from engine.settings_store import SettingsStore
empty = SettingsStore(Path(os.getcwd()) / "no-settings.json")
empty.load()
resolution = stock_scripts.checked(paths.resolve(argv=[], store=empty))
assert resolution.ok, paths.describe_failure(resolution)
assert Path(resolution.game) == Path(game_root), resolution.game
paths.configure(resolution)

import tools.gameloop_harness as gh
import tools.mission_harness as mh
mh.setup_sdk()
mods.install(argv=[])

FORBIDDEN = os.path.realpath(sdk_root).lower().rstrip(os.sep) + os.sep
LAYOUTS = ("Build/scripts", "Build" + os.sep + "scripts")


def _bad(where):
    if not where:
        return False
    real = os.path.realpath(where).lower()
    return real.startswith(FORBIDDEN) or any(l in where for l in LAYOUTS)


def check_provenance(label):
    """No loaded module came from the SDK, by spec origin, __file__, or any
    module-level function's code co_filename."""
    seen = 0
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        spec = getattr(mod, "__spec__", None)
        where = [getattr(spec, "origin", None), getattr(mod, "__file__", None)]
        for value in list(vars(mod).values()) if hasattr(mod, "__dict__") else ():
            if isinstance(value, types.FunctionType):
                where.append(value.__code__.co_filename)
        for w in where:
            if isinstance(w, str):
                seen += 1
                if _bad(w):
                    raise AssertionError("%s: %s came from the SDK: %s"
                                         % (label, name, w))
    assert seen, label


def under_game(origin):
    return os.path.realpath(origin).lower().startswith(
        os.path.realpath(game_root).lower().rstrip(os.sep) + os.sep)


if mode == "missions":
    for mission in names:
        before_purge = {}
        real_purge = mh.purge_run_modules

        def _snapshot_then_purge(mission=mission, real_purge=real_purge):
            # run_mission_with_loop purges the run's modules in `finally`:
            # check provenance while they are still loaded.
            check_provenance(mission)
            mod = sys.modules.get(mission)
            before_purge["origin"] = getattr(
                getattr(mod, "__spec__", None), "origin", None)
            real_purge()

        mh.purge_run_modules = _snapshot_then_purge
        try:
            status, exc, ticks = gh.run_mission_with_loop(mission, n_ticks=__TICKS__)
        finally:
            mh.purge_run_modules = real_purge
        assert (status, ticks) == ("pass", __TICKS__), (mission, status, ticks, exc)
        origin = before_purge.get("origin")
        assert origin and under_game(origin), (mission, origin)
        assert origin.lower().endswith(".pyc"), (mission, origin)
    check_provenance("after the missions")

elif mode == "mod":
    import importlib
    import App  # noqa: F401  (SDK shim import order)
    from engine.appc import weapon_subsystems
    pack = names[0]
    for name in names[1:]:
        mod = importlib.import_module(name)
        origin = mod.__spec__.origin
        assert origin.lower().endswith(".pyc"), (name, origin)
        assert os.path.realpath(origin).startswith(os.path.realpath(pack)), (
            name, origin)
        # ...and the launch resolver hands back THIS module, not the photon.
        assert weapon_subsystems._resolve_projectile_module(name) is mod, name
    check_provenance("after the mod modules")

else:
    raise SystemExit("unknown mode %r" % mode)

print("OK")
'''.replace("__TICKS__", str(TICKS))


def _run_child(tmp_path, mode, *names, mods_dir=None):
    sdk_root = dev_sdk.sdk_root()   # the parent CAN see it; the child must not
    game_root = paths.game_root()
    env = dict(os.environ)
    env.pop(dev_sdk.ENV_VAR, None)
    env[paths.ENV_VARS["game"]] = str(game_root)  # paths-guard: ENV_VARS kind label
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env[paths.DATA_DIR_ENV] = str(data_dir)
    if mods_dir is None:
        env.pop(mods.ENV_VAR, None)
    else:
        env[mods.ENV_VAR] = str(mods_dir)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.setdefault("OPEN_STBC_AUDIO", "0")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    return subprocess.run(
        [sys.executable, "-c", CHILD, mode, str(game_root), str(sdk_root),
         *names],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


def _assert_ok(proc):
    assert proc.returncode == 0, (
        f"child exited {proc.returncode}\n--- stdout ---\n{proc.stdout[-4000:]}"
        f"\n--- stderr ---\n{proc.stderr[-8000:]}")
    assert "OK" in proc.stdout.splitlines(), proc.stdout[-4000:]


def test_missions_load_and_tick_with_no_sdk_anywhere(tmp_path):
    _assert_ok(_run_child(tmp_path, "missions", *MISSIONS))


def test_a_mod_pyc_override_loads_with_no_sdk(tmp_path):
    probe = INTREPID / "scripts" / "Tactical" / "Projectiles" / "ZZ_VoyPhoton.pyc"
    if not probe.is_file():
        pytest.skip("LC Intrepid Pack not installed in mods/")
    _assert_ok(_run_child(tmp_path, "mod", str(INTREPID), *INTREPID_SCRIPTS,
                          mods_dir=PROJECT_ROOT / "mods"))
