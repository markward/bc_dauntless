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
