"""Stage a self-contained, no-terminal build into dist/.

    uv run python scripts/package.py            # stage, then smoke-check
    uv run python scripts/package.py --no-check # stage only

WHAT THIS IS NOT. It is not a second build tree. Nothing compiles here; the
project keeps ONE cmake tree at build/ (CLAUDE.md, "Build layout"). This
copies that tree's outputs, so it can never drift from the thing we test --
it is regenerated wholesale, never incrementally stale.

THE SHIPPED LAYOUT, and why it is shaped this way:

    dist/BC Dauntless/
        BC Dauntless.exe            GUI subsystem -- no terminal window
        dauntless-packaged.json     marker: engine/paths.py puts saves, config
                                    and logs under the player's own folders
        python312.dll               linked by the exe, so it must sit beside it
        libcef.dll, *.pak, locales/ the CEF runtime, likewise
        _dauntless_host*.pyd
        python/Lib, python/DLLs     the bundled stdlib (PYTHONHOME)
        engine/, *.py, tools/       the game's Python
        native/assets/              project-authored assets

The exe sits at the install ROOT, which is what a player expects to click.
That works because host_main.cc's discover_project_root searches upward from
the binary for the marker; only when there is none (a checkout) does it fall
back to "two parents up" for build/dauntless. Change one without the other
and the root silently resolves to the folder CONTAINING the install.

Everything the exe LINKS -- python312.dll, the CEF libraries, the extension
module -- has to be in the exe's own directory for the loader to find it, so
those stay flat at the root. Only the stdlib moves into python/, because a
whole Lib/ tree at the root would bury the handful of entries that matter.

NOT SHIPPED, deliberately: anything the player's machine writes --
settings.json, Options.cfg, Keybindings.cfg, saves/, cache/, mods/. The
engine creates those under the per-user folders; a copy here would be a file
the player edits and the next install overwrites.

BC's own content (game/, sdk/) is never copied. It is the player's, it is
found at runtime through engine/paths.py, and it is not ours to ship.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD = PROJECT_ROOT / "build"
DIST = PROJECT_ROOT / "dist"
APP_NAME = "BC Dauntless"

# Mirrors engine.paths.PACKAGED_MARKER and host_main.cc's kPackagedMarker.
PACKAGED_MARKER = "dauntless-packaged.json"

# Published artefacts are named for the build, so a downloaded zip identifies
# itself before anyone unpacks it.
PLATFORM = "windows-x64"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

# tools/ is a developer tree, but engine/ reaches into it at run time:
# host_loop._setup_sdk does `from tools import mission_harness` for the SDK
# loader, and that module imports tools.timeout_guard. Ship exactly those and
# nothing else -- the rest of tools/ is instrumentation for the ORIGINAL
# stbc.exe (tools/setup.py rewrites a BC install) and has no business in a
# player's copy.
#
# This is a layering smell, not a packaging one: the SDK finder is runtime
# machinery that happens to live under tools/. If it ever moves into engine/,
# delete this list. A real launch (launch_check) is what catches a new
# runtime import landing here, because --smoke-check never reaches _setup_sdk.
_RUNTIME_TOOLS = ("__init__.py", "mission_harness.py", "timeout_guard.py")

# Stdlib trees a game never imports. Dropping them is most of the weight:
# the full Lib/ is ~196 MB, and over half of that is the test corpus alone.
_STDLIB_SKIP = {
    "test", "tests", "idlelib", "tkinter", "turtledemo", "lib2to3",
    "ensurepip", "venv", "distutils", "pydoc_data", "__pycache__",
}
# Extension modules in DLLs/ that nothing in engine/ imports. tcl/tk alone is
# several megabytes and pulls in a GUI toolkit we already have a renderer for.
_DLL_SKIP_PREFIXES = ("_tkinter", "tcl", "tk", "_test", "_ctypes_test")


def git_commit() -> str:
    """The commit this build was staged from, or a plain admission of ignorance.

    A DIRTY tree reports "<sha>-dirty", never the bare sha. A build that
    quietly claims a commit whose code it does not contain is worse than one
    with no version at all: it sends whoever reads the bug report to the wrong
    source and costs them the time the version was supposed to save.
    """
    def _git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=str(PROJECT_ROOT),
                              capture_output=True, text=True,
                              timeout=30).stdout.strip()
    try:
        sha = _git("rev-parse", "--short", "HEAD")
        if not sha:
            return "unknown"
        # --porcelain reports anything uncommitted, staged or not, plus
        # untracked files. dist/ is gitignored, so whatever shows up is real.
        return f"{sha}-dirty" if _git("status", "--porcelain") else sha
    except Exception:
        return "unknown"


def build_info() -> dict:
    """What the marker records, and so what every log of this build reports."""
    from engine.version import VERSION
    return {
        "version": VERSION,
        "commit": git_commit(),
        "built": datetime.datetime.now(datetime.timezone.utc)
                 .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "platform": PLATFORM,
    }


def make_zip(app: Path) -> Path:
    """Zip the staged install for publishing.

    Every entry is nested under the install folder, so unpacking cannot
    scatter twenty-odd DLLs across someone's Downloads.
    """
    from engine.version import VERSION
    target = DIST / f"BC-Dauntless-{VERSION}-{PLATFORM}.zip"
    if target.exists():
        target.unlink()
    _say(f"zipping -> {target.name} (a few minutes; it is mostly libcef)")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for item in sorted(app.rglob("*")):
            if item.is_file():
                zf.write(item, str(Path(APP_NAME) / item.relative_to(app)))
    return target


def _say(msg: str) -> None:
    print(f"[package] {msg}", flush=True)


def _copytree(src: Path, dest: Path, ignore=_IGNORE) -> None:
    shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=True)


def python_home() -> Path:
    """The interpreter whose stdlib we bundle.

    sys.base_prefix, not sys.prefix: inside a venv, prefix is the venv (which
    has no Lib/ of its own) and base_prefix is the real installation.
    """
    return Path(sys.base_prefix)


def stage_python(bin_dir: Path) -> None:
    """Bundle the interpreter so the install needs no Python on the machine.

    host_main.cc points PYTHONHOME at bin/, which makes CPython look for
    Lib/ and DLLs/ exactly here.
    """
    home = python_home()
    ver = f"python{sys.version_info.major}{sys.version_info.minor}"
    # The DLLs the exe links go beside the exe; the stdlib goes under python/.
    stdlib_dir = bin_dir / "python"

    dll = home / f"{ver}.dll"
    if not dll.is_file():
        raise SystemExit(
            f"[package] no {dll.name} at {home}. The bundled runtime must be a "
            "normal CPython install (sys.base_prefix); nothing to copy from.")
    shutil.copy2(dll, bin_dir / dll.name)
    for extra in ("python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        src = home / extra
        if src.is_file():
            shutil.copy2(src, bin_dir / extra)

    lib_src = home / "Lib"
    lib_dest = stdlib_dir / "Lib"
    if not lib_src.is_dir():
        raise SystemExit(f"[package] no stdlib at {lib_src}")
    _copytree(lib_src, lib_dest,
              ignore=shutil.ignore_patterns(*_STDLIB_SKIP, "*.pyc", "*.pyo"))

    dlls_src = home / "DLLs"
    if dlls_src.is_dir():
        dlls_dest = stdlib_dir / "DLLs"
        dlls_dest.mkdir(parents=True, exist_ok=True)
        for item in dlls_src.iterdir():
            if item.is_file() and not item.name.lower().startswith(
                    _DLL_SKIP_PREFIXES):
                shutil.copy2(item, dlls_dest / item.name)


def _pe_subsystem_offset(data: bytearray) -> int:
    """Byte offset of the PE optional header's Subsystem field."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise SystemExit("[package] not a PE image: no PE signature")
    return pe + 0x5C


def make_gui_subsystem(exe: Path) -> None:
    """Flip the PE subsystem from CONSOLE (3) to GUI (2), in place.

    This is why there is no second build tree and no second compile: the
    console and GUI binaries differ only in this field. The CRT entry point
    (mainCRTStartup) is valid under both subsystems -- Windows simply does
    not allocate a console for 2 -- so the same objects serve both. The dev
    binary at build/ stays CONSOLE, where a terminal is wanted.

    Verified empirically before this script existed: a flipped copy booted
    with no console and no redirected handles, initialised CEF and rendered.
    """
    data = bytearray(exe.read_bytes())
    off = _pe_subsystem_offset(data)
    subsystem = struct.unpack_from("<H", data, off)[0]
    if subsystem == 2:
        return
    if subsystem != 3:
        raise SystemExit(
            f"[package] unexpected PE subsystem {subsystem} (want 3=CONSOLE)")
    struct.pack_into("<H", data, off, 2)
    exe.write_bytes(bytes(data))


def stage(dest: Path) -> Path:
    app = dest / APP_NAME
    if app.exists():
        _say(f"removing previous {app.relative_to(PROJECT_ROOT)}")
        shutil.rmtree(app)
    # The exe lives at the install root, so "bin_dir" and the app root are the
    # same directory; the name is kept for the staging helpers below.
    bin_dir = app
    bin_dir.mkdir(parents=True)

    exe_src = BUILD / "dauntless.exe"
    if not exe_src.is_file():
        raise SystemExit(
            "[package] build/dauntless.exe is missing -- build first:\n"
            "  cmake --build build -j")

    # 1. The binary, as a GUI-subsystem copy.
    exe_dest = bin_dir / f"{APP_NAME}.exe"
    shutil.copy2(exe_src, exe_dest)
    make_gui_subsystem(exe_dest)
    _say(f"binary -> {exe_dest.name} (GUI subsystem, install root)")

    # 2. The CEF runtime and the extension module. The build already places
    #    these beside dauntless.exe, which is the layout CEF needs, so copy
    #    from there rather than from _deps -- _deps holds the SDK, not the
    #    arrangement the loader expects.
    runtime = 0
    for item in BUILD.iterdir():
        if item.is_file() and item.suffix.lower() in {".dll", ".pak", ".bin", ".dat"}:
            shutil.copy2(item, bin_dir / item.name)
            runtime += 1
    for sub in ("locales", "swiftshader"):
        src = BUILD / sub
        if src.is_dir():
            _copytree(src, bin_dir / sub)
    pyd = sorted((BUILD / "python").glob("_dauntless_host*.pyd"))
    if not pyd:
        raise SystemExit("[package] no _dauntless_host*.pyd in build/python")
    shutil.copy2(pyd[0], bin_dir / pyd[0].name)
    _say(f"runtime -> {runtime} libraries + {pyd[0].name}")

    # 3. The bundled interpreter.
    stage_python(bin_dir)
    _say(f"python  -> python/ (stdlib from {python_home()})")

    # 4. The game's Python and the project-authored assets.
    _copytree(PROJECT_ROOT / "engine", app / "engine")
    for shim in sorted(PROJECT_ROOT.glob("*.py")):
        shutil.copy2(shim, app / shim.name)
    _copytree(PROJECT_ROOT / "native" / "assets", app / "native" / "assets")
    tools_dest = app / "tools"
    tools_dest.mkdir(parents=True, exist_ok=True)
    for name in _RUNTIME_TOOLS:
        src = PROJECT_ROOT / "tools" / name
        if not src.is_file():
            raise SystemExit(f"[package] missing runtime module {src}")
        shutil.copy2(src, tools_dest / name)
    _say("engine/, root shims, native/assets and runtime tools staged")

    # 5. The marker. Its presence is the whole switch: engine/paths.py sends
    #    writes to the player's folders, and host_main.cc binds Python to the
    #    bundled runtime instead of a developer venv. Its CONTENTS are this
    #    build's identity -- engine/version.py reads them back and puts them in
    #    the log, which is the only way a bug report against a published zip
    #    can be traced to the commit that produced it.
    (app / PACKAGED_MARKER).write_text(
        json.dumps(build_info(), indent=2) + "\n", encoding="utf-8", newline="\n")
    return app


def tree_size_mb(root: Path) -> int:
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return round(total / (1024 * 1024))


def smoke_check(app: Path) -> int:
    """Launch the staged build with a scrubbed environment.

    The scrub is the actual assertion. Clearing VIRTUAL_ENV, PYTHONHOME and
    PYTHONPATH means a pass cannot have come from this developer machine's
    Python: if the bundle were incomplete the interpreter would have nothing
    to fall back to.
    """
    exe = app / f"{APP_NAME}.exe"
    env = dict(os.environ)
    for var in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
                "DAUNTLESS_GAME_DIR", "DAUNTLESS_SDK_DIR"):
        env.pop(var, None)
    _say(f"smoke-check: {exe.name} --smoke-check (scrubbed environment)")
    try:
        proc = subprocess.run([str(exe), "--smoke-check"], env=env,
                              capture_output=True, text=True, timeout=180,
                              cwd=str(app))
    except subprocess.TimeoutExpired:
        _say("FAIL: --smoke-check timed out")
        return 1
    # Diagnostics come from stderr, never stdout (spec section 9).
    tail = (proc.stderr or "").strip().splitlines()[-15:]
    for line in tail:
        print("    " + line)
    if proc.returncode != 0:
        _say(f"FAIL: exit {proc.returncode}")
        return 1
    _say("smoke-check passed")
    return 0


def launch_check(app: Path) -> int:
    """Start the staged game for real and require it to stay up.

    --smoke-check only proves the interpreter embeds; it returns before
    host_loop.run, so it cannot see a module the game imports on the way to a
    window. That is not hypothetical -- it is how `from tools import
    mission_harness` shipped missing from the first staged build. This
    launches the real thing and fails if it dies.

    stderr is redirected so a traceback is visible. That differs from a
    double-launch (which has no handles at all), and the no-console path is
    proven separately; what this checks is that the BUNDLE is complete.
    """
    exe = app / f"{APP_NAME}.exe"
    env = dict(os.environ)
    for var in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(var, None)
    log = app.parent / "launch-check.stderr.txt"
    _say("launch-check: starting the game (scrubbed environment)")
    with open(log, "w", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen([str(exe)], env=env, cwd=str(app),
                                stdout=subprocess.DEVNULL, stderr=err)
        try:
            # A failing boot dies within seconds; a working one runs until
            # something stops it, so reaching the timeout is a PASS.
            proc.wait(timeout=60)
            exited_early = True
        except subprocess.TimeoutExpired:
            exited_early = False
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
    text = log.read_text(encoding="utf-8", errors="replace")
    # An early exit is only a failure if it was not CLEAN. Exit 0 means the
    # game booted, ran and shut down properly -- which is what happens when
    # somebody closes the window while this is watching, and it had better not
    # read as a broken build. Only a non-zero code is a real boot failure.
    if exited_early and proc.returncode != 0:
        _say(f"FAIL: the game exited on its own (code {proc.returncode})")
        for line in text.strip().splitlines()[-20:]:
            print("    " + line)
        return 1
    if exited_early:
        _say("note: the game exited cleanly before the timeout (window closed)")
    if "Traceback" in text:
        _say("FAIL: the game stayed up but raised during boot")
        for line in text.strip().splitlines()[-20:]:
            print("    " + line)
        return 1
    log.unlink(missing_ok=True)
    _say("launch-check passed (booted, no traceback)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-check", action="store_true",
                    help="stage only; skip the launch smoke-check")
    ap.add_argument("--zip", action="store_true",
                    help="also write the publishable zip into dist/")
    args = ap.parse_args()

    if sys.platform != "win32":
        raise SystemExit("[package] this script currently stages a Windows "
                         "build only")

    app = stage(DIST)
    info = json.loads((app / PACKAGED_MARKER).read_text(encoding="utf-8"))
    _say(f"staged {app.relative_to(PROJECT_ROOT)} ({tree_size_mb(app)} MB)")
    _say(f"identity: {info['version']}  {info['commit']}  {info['built']}")
    if str(info["commit"]).endswith("-dirty"):
        # Loud, because the whole point of stamping a commit is that someone
        # can get back to the code, and a dirty build defeats that.
        _say("NOTE: staged from a DIRTY tree -- fine for testing, do not "
             "publish it")

    if not args.no_check:
        rc = smoke_check(app)
        if rc != 0:
            return rc
        rc = launch_check(app)
        if rc != 0:
            return rc
    if args.zip:
        target = make_zip(app)
        _say(f"wrote {target.relative_to(PROJECT_ROOT)} "
             f"({round(target.stat().st_size / (1024 * 1024))} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
