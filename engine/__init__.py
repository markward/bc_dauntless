"""Dauntless engine package.

Importing this package prepares the process to load the ``_dauntless_host``
extension module. Keep it cheap — this runs before every ``engine.*`` import.
"""
import os
import sys
from pathlib import Path

# Windows: _dauntless_host.pyd links libcef.dll, and the build copies CEF's
# Release/ next to dauntless.exe in build/ -- NOT beside the .pyd in
# build/python/. Since Python 3.8 the loader no longer searches PATH for an
# extension's dependent DLLs, so without this every `import _dauntless_host`
# fails with "DLL load failed while importing _dauntless_host: The specified
# module could not be found."
#
# This lives here because engine/__init__ is the one module every engine.*
# consumer loads first -- including subprocesses spawned by tests, which never
# see tests/conftest.py. conftest.py repeats it for tests that import the
# extension directly without importing engine at all.
#
# The handle must be kept alive: add_dll_directory removes the directory again
# when the returned object is closed or garbage collected.
_dll_directory_handle = None

if sys.platform == "win32":
    _build_dir = Path(__file__).resolve().parent.parent / "build"
    if _build_dir.is_dir():
        try:
            _dll_directory_handle = os.add_dll_directory(str(_build_dir))
        except OSError:
            # A missing or unreadable build/ is not fatal here: the import of
            # _dauntless_host will fail with its own, clearer message.
            pass

# The extension itself lives in build/python/. Under build/dauntless it is a
# built-in (registered via PyImport_AppendInittab before Py_Initialize), and
# under pytest tests/conftest.py adds this directory -- but a bare
# `uv run python tools/foo.py` has neither, and engine.settings_store imports
# it transitively through engine.dev_mode. Built-ins still win over sys.path,
# so this is inert in the host binary.
_build_python = Path(__file__).resolve().parent.parent / "build" / "python"
if _build_python.is_dir() and str(_build_python) not in sys.path:
    sys.path.insert(0, str(_build_python))


# Packaged builds (spec 2026-10-16 per-user data dirs, §5.4 P15 and §5.5):
# never write bytecode into the install, and tee fds 1/2 to the rotated log.
# This is the earliest Python the host runs (host_main.cc imports
# engine.bootstrap / engine.host_loop right after Py_InitializeEx and
# publishing sys.argv, so --data-dir is visible), which is what lets a boot
# failure land in the log. engine.paths has to be imported to read the
# marker, so its own bytecode predates the switch; the shipped zip carries
# precompiled .pyc files (§9). A checkout does neither, and nothing here may
# raise out of `import engine`.
def _packaged_boot() -> None:
    try:
        from engine import paths
        if not paths.is_packaged():
            return
        sys.dont_write_bytecode = True
        from engine import log_tee
        log_tee.start(paths.log_file_path())
    except Exception as exc:  # noqa: BLE001 -- boot must go on without a log
        try:
            os.write(2, ("dauntless: packaged boot setup failed (%r)\n"
                         % (exc,)).encode("utf-8", "replace"))
        except OSError:
            pass


_packaged_boot()
