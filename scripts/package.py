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
        README.txt, MODDING.txt     player docs, from docs/packaging/
        LICENSE.txt,                the repo's LICENSE and notices, verbatim
        THIRD_PARTY_NOTICES.txt
        licenses/                   each bundled component's license text
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

MACOS. On a Mac the same tree is staged as dist/BC Dauntless.app, with the
install root in Contents/Resources; the "macOS" section below explains that
layout. --zip writes BC-Dauntless-<version>-macos-arm64.zip.

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



def platform_tag(platform: str = sys.platform) -> str:
    """The OS-and-arch half of a published artefact's name."""
    return "macos-arm64" if platform == "darwin" else "windows-x64"


# Published artefacts are named for the build, so a downloaded zip identifies
# itself before anyone unpacks it.
PLATFORM = platform_tag()

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

# The player-facing documents, shipped at the install root as plain .txt so
# a double-click opens them in Notepad. Published name -> source. LICENSE and
# THIRD_PARTY_NOTICES are the repo's own files, copied byte for byte: the GPL
# text may not be edited, and one notices file cannot drift from another.
DIST_DOCS = {
    "README.txt": PROJECT_ROOT / "docs" / "packaging" / "README.txt",
    "MODDING.txt": PROJECT_ROOT / "docs" / "packaging" / "MODDING.txt",
    "LICENSE.txt": PROJECT_ROOT / "LICENSE",
    "THIRD_PARTY_NOTICES.txt": PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
}

# An unfilled blank in a player document. Staging refuses to ship one.
DOC_PLACEHOLDER = "[[TODO"

# Where the shipped license texts go. THIRD_PARTY_NOTICES names each file by
# this folder, and tests/unit/test_package_docs.py holds the two in step.
LICENSES_DIR = "licenses"


def python_license() -> Path:
    """The license file of the Python whose stdlib we bundle.

    Searched the way CPython's own license() builtin searches (site.py): the
    stdlib's parent, then the stdlib itself. On Windows that is
    <base_prefix>/LICENSE.txt, which also covers the libraries Python bundles.
    """
    stdlib = Path(os.__file__).resolve().parent
    for folder in (stdlib.parent, stdlib):
        for name in ("LICENSE.txt", "LICENSE"):
            if (folder / name).is_file():
                return folder / name
    raise SystemExit(f"[package] no Python license file beside {stdlib}")


def third_party_licenses() -> dict:
    """Published name (under licenses/) -> source, for everything we bundle.

    A function, not a constant: the Python entry depends on the interpreter
    running this script, and build/_deps exists only after a configure.
    """
    third = PROJECT_ROOT / "native" / "third_party"
    deps = BUILD / "_deps"
    return {
        "Python-LICENSE.txt": python_license(),
        "CEF-LICENSE.txt": deps / "cef-src" / "LICENSE.txt",
        "Chromium-CREDITS.html": deps / "cef-src" / "CREDITS.html",
        "OpenAL-Soft-COPYING.txt": deps / "openal_soft-src" / "COPYING",
        "pybind11-LICENSE.txt": deps / "pybind11-src" / "LICENSE",
        "nlohmann-json-LICENSE.txt": deps / "nlohmann_json-src" / "LICENSE.MIT",
        "GLFW-LICENSE.txt": third / "glfw" / "LICENSE.md",
        "GLAD-LICENSE.txt": third / "glad" / "LICENSE",
        "glm-LICENSE.txt": third / "glm" / "LICENSE",
        "stb-LICENSE.txt": third / "stb" / "LICENSE",
        "cgltf-LICENSE.txt": third / "cgltf" / "LICENSE",
        "dr_libs-LICENSE.txt": third / "dr_libs" / "LICENSE",
        "ThorVG-LICENSE.txt": third / "thorvg" / "LICENSE",
        "RapidJSON-LICENSE.txt": third / "thorvg" / "src" / "loaders" / "lottie" / "rapidjson" / "LICENSE",
        "Antonio-OFL.txt": (PROJECT_ROOT / "native" / "assets" / "ui-cef"
                            / "THIRD_PARTY" / "Antonio-OFL.txt"),
    }


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


def zip_name(version: str, platform: str) -> str:
    return f"BC-Dauntless-{version}-{platform}.zip"


def app_binary(app: Path, platform: str = sys.platform) -> Path:
    """The executable a player (and the smoke checks) launch."""
    if platform == "darwin":
        return app / "Contents" / "MacOS" / APP_NAME
    return app / f"{APP_NAME}.exe"


def make_zip(app: Path) -> Path:
    """Zip the staged install for publishing.

    Every entry is nested under the install folder, so unpacking cannot
    scatter twenty-odd DLLs across someone's Downloads.
    """
    from engine.version import VERSION
    target = DIST / zip_name(VERSION, PLATFORM)
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


def unfinished_docs() -> list:
    """Published names of the player documents that still hold a placeholder."""
    return [name for name, src in DIST_DOCS.items()
            if DOC_PLACEHOLDER in src.read_text(encoding="utf-8")]


def stage_docs(app: Path) -> None:
    for name, src in DIST_DOCS.items():
        if not src.is_file():
            raise SystemExit(f"[package] missing player document {src}")
        shutil.copy2(src, app / name)
    _say(f"docs    -> {', '.join(DIST_DOCS)}")

    # Every bundled component's license text. MIT, BSD and zlib all require
    # it in a binary distribution; a missing one is a release we may not ship.
    licenses = app / LICENSES_DIR
    licenses.mkdir(exist_ok=True)
    for name, src in third_party_licenses().items():
        if not src.is_file():
            raise SystemExit(f"[package] missing license text {src}")
        shutil.copy2(src, licenses / name)
    _say(f"licenses -> {LICENSES_DIR}/ ({len(third_party_licenses())} files)")


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
    stage_game_python(app)

    # 5. What the player reads first: README, modding guide, license, notices.
    stage_docs(app)

    # 6. The marker.
    write_marker(app)
    return app


def stage_game_python(root: Path) -> None:
    """engine/, the root shims, native/assets and the runtime tools."""
    _copytree(PROJECT_ROOT / "engine", root / "engine")
    for shim in sorted(PROJECT_ROOT.glob("*.py")):
        shutil.copy2(shim, root / shim.name)
    _copytree(PROJECT_ROOT / "native" / "assets", root / "native" / "assets")
    tools_dest = root / "tools"
    tools_dest.mkdir(parents=True, exist_ok=True)
    for name in _RUNTIME_TOOLS:
        src = PROJECT_ROOT / "tools" / name
        if not src.is_file():
            raise SystemExit(f"[package] missing runtime module {src}")
        shutil.copy2(src, tools_dest / name)
    _say("engine/, root shims, native/assets and runtime tools staged")


def write_marker(root: Path) -> None:
    """The marker. Its presence is the whole switch: engine/paths.py sends
    writes to the player's folders, and host_main.cc binds Python to the
    bundled runtime instead of a developer venv. Its CONTENTS are this
    build's identity -- engine/version.py reads them back and puts them in
    the log, which is the only way a bug report against a published zip
    can be traced to the commit that produced it."""
    (root / PACKAGED_MARKER).write_text(
        json.dumps(build_info(), indent=2) + "\n", encoding="utf-8", newline="\n")


# --- macOS ------------------------------------------------------------------
#
#     dist/BC Dauntless.app/Contents/
#         Info.plist
#         MacOS/BC Dauntless              the game (CEF helpers are separate)
#         Frameworks/libpython3.11.dylib  linked via @rpath
#         Frameworks/Chromium Embedded Framework.framework
#         Frameworks/BC Dauntless Helper*.app   CEF's helper processes
#         Resources/                      the install root: the marker,
#                                         engine/, shims, tools/, native/assets,
#                                         python/lib/python3.11 (PYTHONHOME),
#                                         docs, licenses/, the icon
#
# The root lives in Contents/Resources, not beside the binary: a bundle's
# MacOS/ holds code only, and host_main.cc finds the marker there through
# platform::app_bundle_resources. CEF needs real Helper apps once it runs
# from a bundle -- Chromium derives "<name> Helper (GPU).app" etc. from the
# plain helper's path -- and each is a copy of the game binary (one
# executable, many CEF roles, exactly as in a checkout), with LSUIElement so
# helpers never show in the Dock. Every copy links libpython through two
# rpaths, ../Frameworks for the game and ../../.. for a helper.
#
# Signing is ad hoc (no Apple Developer identity), so the app is not
# notarised: the README tells players how to open it the first time.

BUNDLE_ID = "com.markward.bcdauntless"
_HELPER_SUFFIXES = ("", " (Alerts)", " (GPU)", " (Plugin)", " (Renderer)")
_RPATHS = ("@executable_path/../Frameworks", "@executable_path/../../..")
_CEF_FRAMEWORK = "Chromium Embedded Framework.framework"
# Only for building extensions, or packages a game never imports.
_MACOS_STDLIB_SKIP = {"site-packages", f"config-{sys.version_info.major}."
                      f"{sys.version_info.minor}-darwin"}
_ICON = PROJECT_ROOT / "native" / "assets" / "icons" / "dauntless.ico"


def macos_helper_names() -> list:
    return [f"{APP_NAME} Helper{suffix}" for suffix in _HELPER_SUFFIXES]


def info_plist(name: str, version: str, min_os: str,
               icon: str | None = None) -> dict:
    """The Info.plist of the game (icon given) or one of its CEF helpers."""
    helper = name != APP_NAME
    slug = name[len(APP_NAME):].strip().lower()
    for ch in "()":
        slug = slug.replace(ch, "")
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": name,
        "CFBundleIdentifier": (f"{BUNDLE_ID}." + ".".join(slug.split())
                               if helper else BUNDLE_ID),
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": name,
        "CFBundleDisplayName": name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": min_os,
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
    }
    if helper:
        plist["LSUIElement"] = True
    if icon:
        plist["CFBundleIconFile"] = icon
    return plist


def linked_libpython(otool_l: str) -> Path:
    """The libpython a binary links, from `otool -L` output."""
    for line in otool_l.splitlines()[1:]:
        lib = line.strip().split(" (compatibility")[0]
        if Path(lib).name.startswith("libpython"):
            return Path(lib)
    raise SystemExit("[package] the binary links no libpython; nothing to bundle")


def macos_min_version(otool_load_commands: str) -> str:
    """LC_BUILD_VERSION's minos, from `otool -l` output."""
    for line in otool_load_commands.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "minos":
            return parts[1]
    raise SystemExit("[package] no LC_BUILD_VERSION minos in the binary")


# The oldest macOS the app declares. The binary's own deployment target is
# CEF's 12.0, but the statically linked OpenAL was built against the macOS 26
# SDK (the linker warns), so nothing older is known to run it. Ruled 2026-11-04:
# 0.2.x requires macOS 26. Lower this only after building OpenAL for an older
# target and launching the app on that macOS.
MACOS_FLOOR = "26.0"


def declared_min_macos(binary_minos: str) -> str:
    """LSMinimumSystemVersion: the higher of the binary's minos and the floor."""
    key = lambda v: tuple(int(p) for p in v.split("."))
    return max(binary_minos, MACOS_FLOOR, key=key)


def _run(*cmd: str) -> str:
    proc = subprocess.run(list(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"[package] {' '.join(cmd)} failed:\n{proc.stderr}")
    return proc.stdout


def stage_macos_python(resources: Path, frameworks: Path, exe: Path) -> None:
    """Bundle libpython and the trimmed stdlib, and point `exe` at them.

    The stdlib must come from the same interpreter the binary links, or the
    bundled libpython would run another version's Lib/.
    """
    linked = linked_libpython(_run("otool", "-L", str(exe)))
    home = python_home()
    if linked.parent != home / "lib":
        raise SystemExit(
            f"[package] build/dauntless links {linked}, but this script runs "
            f"{home}; run it with the interpreter the build linked")
    dylib = frameworks / linked.name
    shutil.copy2(linked, dylib)
    dylib.chmod(0o755)
    _run("install_name_tool", "-id", f"@rpath/{linked.name}", str(dylib))
    rpath_args = [arg for rp in _RPATHS for arg in ("-add_rpath", rp)]
    _run("install_name_tool", "-change", str(linked), f"@rpath/{linked.name}",
         *rpath_args, str(exe))

    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib_src = home / "lib" / ver
    lib_dest = resources / "python" / "lib" / ver
    if not lib_src.is_dir():
        raise SystemExit(f"[package] no stdlib at {lib_src}")
    _copytree(lib_src, lib_dest, ignore=shutil.ignore_patterns(
        *_STDLIB_SKIP, *_MACOS_STDLIB_SKIP, "*.pyc", "*.pyo"))
    for item in (lib_dest / "lib-dynload").glob("*"):
        if item.name.lower().startswith(_DLL_SKIP_PREFIXES):
            item.unlink()


def precompile(root: Path) -> None:
    """Ship bytecode, so the first run never writes into the signed bundle.

    The interpreter imports the stdlib (and engine.paths) before engine/
    sets sys.dont_write_bytecode, and a write there would break the seal.
    Unchecked-hash .pyc files stay valid whatever mtimes the unzip gives.
    """
    import compileall
    import py_compile
    if not compileall.compile_dir(
            str(root), quiet=1, workers=0,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH):
        raise SystemExit("[package] byte-compiling the bundle failed")


def write_plist(path: Path, plist: dict) -> None:
    import plistlib
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump(plist, fh)


def stage_macos_icon(resources: Path) -> str | None:
    """dauntless.icns from the generated Windows .ico; None without Pillow."""
    try:
        from PIL import Image
    except ImportError:
        _say("NOTE: no Pillow -- the app ships without an icon")
        return None
    with Image.open(_ICON) as ico:
        ico.size = max(ico.info.get("sizes", {ico.size}))
        ico.load()
        ico.save(resources / "dauntless.icns")
    return "dauntless"


def _codesign(path: Path) -> None:
    _run("codesign", "--force", "--sign", "-", "--timestamp=none", str(path))


def sign_macos_app(app: Path) -> None:
    """Ad-hoc sign inside-out: libraries, framework, helpers, then the app."""
    frameworks = app / "Contents" / "Frameworks"
    cef = frameworks / _CEF_FRAMEWORK
    for lib in sorted((cef / "Libraries").glob("*.dylib")):
        _codesign(lib)
    _codesign(cef)
    for dylib in sorted(frameworks.glob("*.dylib")):
        _codesign(dylib)
    for name in macos_helper_names():
        _codesign(frameworks / f"{name}.app")
    _codesign(app)
    _run("codesign", "--verify", "--deep", "--strict", str(app))


def stage_macos(dest: Path) -> Path:
    from engine.version import VERSION
    app = dest / f"{APP_NAME}.app"
    if app.exists():
        _say(f"removing previous {app.relative_to(PROJECT_ROOT)}")
        shutil.rmtree(app)
    contents = app / "Contents"
    macos_dir, frameworks = contents / "MacOS", contents / "Frameworks"
    resources = contents / "Resources"
    for folder in (macos_dir, frameworks, resources):
        folder.mkdir(parents=True)

    exe_src = BUILD / "dauntless"
    if not exe_src.is_file():
        raise SystemExit("[package] build/dauntless is missing -- build first:\n"
                         "  cmake --build build -j")
    min_os = declared_min_macos(macos_min_version(_run("otool", "-l", str(exe_src))))

    # 1. The binary and the interpreter it links.
    exe = macos_dir / APP_NAME
    shutil.copy2(exe_src, exe)
    stage_macos_python(resources, frameworks, exe)
    _say(f"binary + python -> {exe.name}, libpython (minimum macOS {min_os})")

    # 2. CEF: the framework (the build only symlinks it) and the helpers,
    #    each a copy of the already-relinked binary.
    cef_src = (BUILD / "Frameworks" / _CEF_FRAMEWORK).resolve()
    if not cef_src.is_dir():
        raise SystemExit(f"[package] no CEF framework at {cef_src}")
    _copytree(cef_src, frameworks / _CEF_FRAMEWORK)
    for name in macos_helper_names():
        helper = frameworks / f"{name}.app" / "Contents"
        (helper / "MacOS").mkdir(parents=True)
        shutil.copy2(exe, helper / "MacOS" / name)
        write_plist(helper / "Info.plist", info_plist(name, VERSION, min_os))
    _say(f"cef     -> framework + {len(_HELPER_SUFFIXES)} helper apps")

    # 3. The install root: the game's Python, docs, licences, marker.
    stage_game_python(resources)
    stage_docs(resources)
    write_marker(resources)
    precompile(resources)
    icon = stage_macos_icon(resources)
    write_plist(contents / "Info.plist",
                info_plist(APP_NAME, VERSION, min_os, icon=icon))

    # 4. Ad-hoc signature: install_name_tool broke the linker's, and an
    #    unsigned arm64 binary is killed on launch.
    sign_macos_app(app)
    _say("signed  -> ad hoc (not notarised)")
    return app


def make_macos_zip(app: Path) -> Path:
    """Zip the .app with ditto (keeps modes and the signature intact), plus
    the player documents beside it so nobody has to open the bundle."""
    from engine.version import VERSION
    target = DIST / zip_name(VERSION, PLATFORM)
    if target.exists():
        target.unlink()
    _say(f"zipping -> {target.name}")
    _run("ditto", "-c", "-k", "--norsrc", "--noextattr", "--noqtn",
         "--keepParent", str(app), str(target))
    resources = app / "Contents" / "Resources"
    with zipfile.ZipFile(target, "a", zipfile.ZIP_DEFLATED) as zf:
        for name in DIST_DOCS:
            zf.write(resources / name, name)
    return target


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
    exe = app_binary(app)
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
    exe = app_binary(app)
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

    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("[package] this script stages a Windows or macOS "
                         "build only")

    # Like a dirty tree: fine to stage for testing, never fine to publish.
    unfinished = unfinished_docs()
    if unfinished and args.zip:
        raise SystemExit(f"[package] refusing --zip: {', '.join(unfinished)} "
                         f"still hold {DOC_PLACEHOLDER} placeholders")

    macos = sys.platform == "darwin"
    app = stage_macos(DIST) if macos else stage(DIST)
    root = app / "Contents" / "Resources" if macos else app
    info = json.loads((root / PACKAGED_MARKER).read_text(encoding="utf-8"))
    _say(f"staged {app.relative_to(PROJECT_ROOT)} ({tree_size_mb(app)} MB)")
    _say(f"identity: {info['version']}  {info['commit']}  {info['built']}")
    if str(info["commit"]).endswith("-dirty"):
        # Loud, because the whole point of stamping a commit is that someone
        # can get back to the code, and a dirty build defeats that.
        _say("NOTE: staged from a DIRTY tree -- fine for testing, do not "
             "publish it")
    if unfinished:
        _say(f"NOTE: {', '.join(unfinished)} still hold {DOC_PLACEHOLDER} "
             "placeholders -- fine for testing, do not publish it")

    if not args.no_check:
        rc = smoke_check(app)
        if rc != 0:
            return rc
        rc = launch_check(app)
        if rc != 0:
            return rc
    if args.zip:
        target = make_macos_zip(app) if macos else make_zip(app)
        _say(f"wrote {target.relative_to(PROJECT_ROOT)} "
             f"({round(target.stat().st_size / (1024 * 1024))} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
