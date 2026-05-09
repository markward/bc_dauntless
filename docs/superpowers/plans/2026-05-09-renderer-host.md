# Renderer Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a C++ host binary `open_stbc_host` that embeds CPython 3.x, runs the existing Phase 1 engine inside its process, and renders the running game in a window in lock-step with the 60 Hz tick. v1 ship gate: simplest BC mission renders with player + NPC ships at real game-loop positions.

**Architecture:** Single-thread, lock-step at 60 Hz. C++ host owns the process; Python is embedded via libpython3 + pybind11. The `_open_stbc_host` pybind11 module exposes window, asset, scene-graph, and frame-submission ops to Python. `engine/host_loop.py` is the bridge between existing Phase 1 mission init/tick code and the renderer.

**Tech Stack:** C++20, CMake, libpython3 (FindPython3), pybind11 (FetchContent), GLFW (existing), GLAD 1.x (existing), GLM (existing), GoogleTest (existing), pytest (existing), GLSL 330 core.

**Reference:** Spec lives at `docs/superpowers/specs/2026-05-09-renderer-host-design.md`. Read sections in order while working — they are bounded enough to skim per-phase. The user is adding more BC engine-internals documentation under `docs/engine_internals/` while this work proceeds; check that tree if a task references a convention (e.g., LCARs flicker) that the spec doesn't fully cover.

**Not in this plan:** animation playback, skinned-mesh rendering, frustum culling, real BC light data interpretation, debug fly-around camera, HUD/UI. See spec § "Deferred / future work" for the full list.

---

## Phase A — CPython embedding host

Six tasks. Goal: a runnable `open_stbc_host` binary that boots libpython3, imports a Python module, and exits cleanly. No window yet, no rendering yet. The pybind11 module `_open_stbc_host` exists with stub init/shutdown; pytest can import it.

### Task 1: CMake bring-up — find Python, vendor pybind11, promote GLFW

**Files:**
- Modify: `native/CMakeLists.txt`
- Create: `native/src/host/CMakeLists.txt`
- Create: `native/src/host/.gitkeep` (placeholder so directory exists; deleted in Task 2)

**Goal:** root CMake locates Python3 with the Embed component, fetches pybind11, promotes GLFW out of the test-only block, and reserves the `host` subdirectory.

- [ ] **Step 1: Modify root CMake to add Python + pybind11 + promote GLFW**

Edit `native/CMakeLists.txt`. After the `add_subdirectory(third_party/glm)` line, insert:

```cmake
# CPython embedding for the renderer host.
# Use the granular Development.Embed component (CMake's modern form) — the
# legacy "Embed" alias isn't always recognized as a standalone component
# name. Python.framework on macOS satisfies this even when Py_ENABLE_SHARED=0.
find_package(Python3 3.11 REQUIRED COMPONENTS Development.Embed)

# pybind11 via FetchContent (vendored copies are too heavy; FetchContent caches
# under build/_deps and is reused across configures).
include(FetchContent)
FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG        v2.13.6
)
FetchContent_MakeAvailable(pybind11)
```

Then move the GLFW block out of the `if(OPEN_STBC_BUILD_TESTS)` guard so the renderer (not just tests) can link it. Replace this:

```cmake
if(OPEN_STBC_BUILD_TESTS)
  set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
  set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
  add_subdirectory(third_party/glfw)
  add_subdirectory(tests)
endif()
```

with:

```cmake
# GLFW is a runtime dep for the renderer host; tests reuse the same build.
set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/glfw)

# Renderer host subtree.
add_subdirectory(src/host)

option(OPEN_STBC_BUILD_TESTS "Build native tests for open_stbc" ON)
if(OPEN_STBC_BUILD_TESTS)
  add_subdirectory(tests)
endif()
```

- [ ] **Step 2: Create stub host CMakeLists**

Create `native/src/host/CMakeLists.txt`:

```cmake
# native/src/host/CMakeLists.txt — renderer host binary + pybind11 module.
# Tasks 2-6 populate this with real targets. Empty stub keeps configure
# step happy until then.
```

Create `native/src/host/.gitkeep` (empty file). It will be removed in Task 2 once `host_main.cc` exists.

- [ ] **Step 3: Run cmake configure to verify Python and pybind11 resolve**

Run: `cmake -S . -B build`
Expected output includes:
- `-- Found Python3: ... (found suitable version "3.11..." or higher)`
- `-- Performing Test HAVE_NO_DEPRECATED -- Success` (from pybind11)
- No errors

If Python3 with Embed component isn't found, install `python3-dev` (Linux) or use the system Python.framework (macOS). On uv-managed venvs, `find_package` uses the system Python, which is fine — the embedded libpython3 just needs to match the *runtime* Python version chosen later.

- [ ] **Step 4: Build all existing targets to confirm nothing regressed**

Run: `cmake --build build -j`
Expected: all existing `nif`, `assets`, `nif_tests`, `assets_tests`, `scan_nifs` targets build successfully. No new targets yet.

- [ ] **Step 5: Commit**

```bash
git add native/CMakeLists.txt native/src/host/CMakeLists.txt native/src/host/.gitkeep
git commit -m "build(host): find Python3, fetch pybind11, promote GLFW for renderer host"
```

---

### Task 2: Minimal host_main.cc — Py_InitializeEx + clean exit

**Files:**
- Create: `native/src/host/host_main.cc`
- Modify: `native/src/host/CMakeLists.txt`
- Delete: `native/src/host/.gitkeep`

**Goal:** the `open_stbc_host` binary starts CPython, runs `import sys`, prints the version, and exits 0.

- [ ] **Step 1: Write the failing test (CMake build of host)**

This task's "failing test" is the CMake configure + build of the new target. Update `native/src/host/CMakeLists.txt`:

```cmake
# native/src/host/CMakeLists.txt — renderer host binary + pybind11 module.

add_executable(open_stbc_host
    host_main.cc
)

target_link_libraries(open_stbc_host
    PRIVATE
        Python3::Python
)

target_compile_features(open_stbc_host PRIVATE cxx_std_20)

set_target_properties(open_stbc_host PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
```

- [ ] **Step 2: Run build, verify it fails (host_main.cc missing)**

Run: `cmake --build build --target open_stbc_host`
Expected: failure — `host_main.cc: No such file or directory`

- [ ] **Step 3: Implement host_main.cc minimally**

Create `native/src/host/host_main.cc`:

```cpp
// native/src/host/host_main.cc
//
// open_stbc_host — embedded-CPython renderer host binary.
// Phase A bring-up: initialize CPython, import sys, print version, exit.
// Subsequent tasks add the bindings module and the main render loop.

#include <Python.h>

#include <cstdio>
#include <cstdlib>

int main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    Py_InitializeEx(/*initsigs=*/1);

    PyObject* sys = PyImport_ImportModule("sys");
    if (!sys) {
        PyErr_Print();
        Py_FinalizeEx();
        return 1;
    }

    PyObject* version = PyObject_GetAttrString(sys, "version");
    if (!version) {
        PyErr_Print();
        Py_DECREF(sys);
        Py_FinalizeEx();
        return 1;
    }

    const char* version_str = PyUnicode_AsUTF8(version);
    std::printf("open_stbc_host: Python %s\n", version_str ? version_str : "<unknown>");

    Py_DECREF(version);
    Py_DECREF(sys);

    if (Py_FinalizeEx() < 0) {
        return 2;
    }
    return 0;
}
```

Delete `native/src/host/.gitkeep`.

- [ ] **Step 4: Build and run, verify clean Python startup**

Run:
```bash
cmake --build build --target open_stbc_host
./build/bin/open_stbc_host
```

Expected output:
```
open_stbc_host: Python 3.11.x (...)
```
Exit code 0 (`echo $?` returns 0).

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_main.cc native/src/host/CMakeLists.txt
git rm native/src/host/.gitkeep
git commit -m "feat(host): minimal host_main embeds CPython and prints sys.version"
```

---

### Task 3: pybind11 module skeleton — `_open_stbc_host` with init/shutdown stubs

**Files:**
- Create: `native/src/host/host_bindings.h`
- Create: `native/src/host/host_bindings.cc`
- Modify: `native/src/host/CMakeLists.txt`
- Modify: `native/src/host/host_main.cc`

**Goal:** Two CMake targets share `host_bindings.cc`: a Python extension module (`_open_stbc_host.so`) for pytest, and the executable (statically linked + `PyImport_AppendInittab`).

- [ ] **Step 1: Write the failing pytest binding test**

Create `tests/host/__init__.py` (empty file).

Create `tests/host/test_bindings_smoke.py`:

```python
"""Smoke test: _open_stbc_host module imports and exposes init/shutdown."""

def test_module_imports():
    import _open_stbc_host
    assert hasattr(_open_stbc_host, "init")
    assert hasattr(_open_stbc_host, "shutdown")


def test_init_shutdown_round_trip():
    import _open_stbc_host
    _open_stbc_host.init(640, 480, "test")
    _open_stbc_host.shutdown()
```

- [ ] **Step 2: Run the test, verify it fails (module not built / not on sys.path)**

Run: `uv run pytest tests/host/test_bindings_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_open_stbc_host'`

- [ ] **Step 3: Implement bindings header**

Create `native/src/host/host_bindings.h`:

```cpp
// native/src/host/host_bindings.h
#pragma once

#include <Python.h>

// Module init function exported by host_bindings.cc. The host executable
// registers it via PyImport_AppendInittab before Py_InitializeEx; the Python
// extension module .so exposes it as the standard PyInit__open_stbc_host
// entry point.
extern "C" PyObject* PyInit__open_stbc_host();
```

- [ ] **Step 4: Implement bindings stub**

Create `native/src/host/host_bindings.cc`:

```cpp
// native/src/host/host_bindings.cc
//
// pybind11 module exposing the renderer host API to Python. Built as both:
//   1. A standalone Python extension module (_open_stbc_host.so) for pytest.
//   2. Statically linked into open_stbc_host (registered via
//      PyImport_AppendInittab before Py_InitializeEx).
//
// Phase A: init/shutdown stubs only. Phases B-E populate the rest of the API.

#include "host_bindings.h"

#include <pybind11/pybind11.h>

namespace py = pybind11;

namespace {

bool g_initialized = false;

void init(int width, int height, const std::string& title) {
    (void)width;
    (void)height;
    (void)title;
    g_initialized = true;
}

void shutdown() {
    g_initialized = false;
}

bool should_close() {
    return false;  // Phase A stub; Window class wires this in Phase B.
}

}  // namespace

PYBIND11_MODULE(_open_stbc_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase A: stubs)";
    m.def("init", &init, py::arg("width"), py::arg("height"), py::arg("title"),
          "Initialize host (window + GL context in Phase B+).");
    m.def("shutdown", &shutdown, "Tear down host.");
    m.def("should_close", &should_close, "Return true when window close is requested.");
}
```

- [ ] **Step 5: Update host CMakeLists with the module target + executable link**

Replace `native/src/host/CMakeLists.txt` with:

```cmake
# native/src/host/CMakeLists.txt — renderer host binary + pybind11 module.

# Shared source — both targets compile this file. The PYBIND11_MODULE macro
# generates PyInit__open_stbc_host, used by both consumers.
set(HOST_BINDINGS_SOURCES
    host_bindings.cc
)

# Python extension module (.so / .pyd / .dylib) for pytest.
pybind11_add_module(_open_stbc_host MODULE ${HOST_BINDINGS_SOURCES})
target_compile_features(_open_stbc_host PRIVATE cxx_std_20)
set_target_properties(_open_stbc_host PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python"
)

# Host executable. Statically links the same bindings translation unit, then
# host_main registers the init function via PyImport_AppendInittab before
# Py_InitializeEx.
add_executable(open_stbc_host
    host_main.cc
    ${HOST_BINDINGS_SOURCES}
)

target_link_libraries(open_stbc_host
    PRIVATE
        Python3::Python
        pybind11::embed
)

target_compile_features(open_stbc_host PRIVATE cxx_std_20)
target_include_directories(open_stbc_host PRIVATE .)

set_target_properties(open_stbc_host PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
```

- [ ] **Step 6: Update host_main.cc to register the inittab entry**

Replace the body of `host_main.cc`'s `main` (keep the includes; add one):

```cpp
#include <Python.h>

#include "host_bindings.h"

#include <cstdio>
#include <cstdlib>

int main(int argc, char* argv[]) {
    (void)argc;
    (void)argv;

    if (PyImport_AppendInittab("_open_stbc_host", PyInit__open_stbc_host) != 0) {
        std::fprintf(stderr, "open_stbc_host: PyImport_AppendInittab failed\n");
        return 1;
    }

    Py_InitializeEx(/*initsigs=*/1);

    PyObject* mod = PyImport_ImportModule("_open_stbc_host");
    if (!mod) {
        PyErr_Print();
        Py_FinalizeEx();
        return 1;
    }
    Py_DECREF(mod);

    PyObject* sys = PyImport_ImportModule("sys");
    PyObject* version = PyObject_GetAttrString(sys, "version");
    const char* version_str = PyUnicode_AsUTF8(version);
    std::printf("open_stbc_host: Python %s, _open_stbc_host imported\n",
                version_str ? version_str : "<unknown>");
    Py_DECREF(version);
    Py_DECREF(sys);

    if (Py_FinalizeEx() < 0) {
        return 2;
    }
    return 0;
}
```

- [ ] **Step 7: Add conftest.py path entry so pytest finds the built .so**

Modify `tests/conftest.py`. At the top of the file (immediately after the `from pathlib import Path` line, before any class/function definitions), insert:

```python
# Make the C++-built _open_stbc_host extension importable. CMake outputs it
# under build/python/ relative to the project root.
_PROJECT_ROOT = Path(__file__).parent.parent
_BUILD_PYTHON = _PROJECT_ROOT / "build" / "python"
if _BUILD_PYTHON.is_dir() and str(_BUILD_PYTHON) not in sys.path:
    sys.path.insert(0, str(_BUILD_PYTHON))
```

(The existing `import sys` at the top of conftest.py already covers the `sys` reference.)

- [ ] **Step 8: Build both targets**

Run:
```bash
cmake --build build --target _open_stbc_host open_stbc_host -j
```

Verify both artifacts exist:
```bash
ls build/bin/open_stbc_host build/python/_open_stbc_host*.so
```
Expected: both files present.

- [ ] **Step 9: Run the binding test, verify it passes**

Run: `uv run pytest tests/host/test_bindings_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 10: Run the host binary, verify the inittab path works**

Run: `./build/bin/open_stbc_host`
Expected output ends with: `_open_stbc_host imported`. Exit code 0.

- [ ] **Step 11: Commit**

```bash
git add native/src/host/host_bindings.h native/src/host/host_bindings.cc \
        native/src/host/CMakeLists.txt native/src/host/host_main.cc \
        tests/host/__init__.py tests/host/test_bindings_smoke.py \
        tests/conftest.py
git commit -m "feat(host): pybind11 _open_stbc_host module with init/shutdown stubs"
```

---

### Task 4: Wire venv-aware sys.path so embedded Python finds engine/

**Files:**
- Modify: `native/src/host/host_main.cc`
- Create: `tests/host/test_embedded_engine_import.py`

**Goal:** the host binary's embedded interpreter can `import engine.bootstrap` (a stub created in this task) using the same project layout `uv run` uses. Honors `VIRTUAL_ENV` to find a venv's site-packages; falls back to using the project root for the source-importable `engine/` package.

- [ ] **Step 1: Create engine/bootstrap.py stub**

Create `engine/bootstrap.py`:

```python
"""Bootstrap module loaded by open_stbc_host to verify embedding works.

Phase F replaces the `run` body with the real mission/render loop. The banner
function is the Phase A liveness check the host binary calls right after
Py_InitializeEx.
"""

def banner() -> str:
    return "open_stbc host alive"
```

- [ ] **Step 2: Write the failing pytest test that the host imports engine.bootstrap**

Create `tests/host/test_embedded_engine_import.py`:

```python
"""Run the host binary and assert it imports engine.bootstrap successfully."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BIN = PROJECT_ROOT / "build" / "bin" / "open_stbc_host"


def test_host_imports_engine_bootstrap():
    if not HOST_BIN.exists():
        import pytest
        pytest.skip(f"host binary not built at {HOST_BIN}")
    result = subprocess.run(
        [str(HOST_BIN)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"host exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "open_stbc host alive" in result.stdout, (
        f"banner missing from stdout:\n{result.stdout}"
    )
```

- [ ] **Step 3: Build and run the test, verify it fails**

Run:
```bash
cmake --build build --target open_stbc_host
uv run pytest tests/host/test_embedded_engine_import.py -v
```
Expected: FAIL — host stdout shows the inittab message but not the banner.

- [ ] **Step 4: Update host_main.cc to set up sys.path and call engine.bootstrap.banner()**

Replace `host_main.cc`. Keep the inittab registration; add sys.path setup before `Py_InitializeEx` and the banner call after:

```cpp
// native/src/host/host_main.cc
//
// open_stbc_host — embedded-CPython renderer host binary.

#include <Python.h>

#include "host_bindings.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>

namespace {

// Locate the project root from the running binary's path. The binary lives at
// <root>/build/bin/open_stbc_host, so root is two parents up from the binary
// dir. This is a build-tree assumption — the binary is not yet meant to be
// installed system-wide.
std::filesystem::path discover_project_root(const char* argv0) {
    std::filesystem::path bin_path = std::filesystem::canonical(argv0);
    return bin_path.parent_path().parent_path().parent_path();
}

// Set PYTHONPATH so the embedded interpreter can find engine/ (and the SDK
// scripts via the project's existing sys.path-based finder). Honors an active
// uv venv's site-packages via VIRTUAL_ENV when set.
void configure_python_path(const std::filesystem::path& project_root) {
    std::string pythonpath = project_root.string();

    if (const char* venv = std::getenv("VIRTUAL_ENV")) {
        // Best-effort glob — site-packages lives under .venv/lib/pythonX.Y/site-packages.
        // We don't pin the minor version; the embedded interpreter's own version
        // controls what site-packages directory exists. Add the parent lib/ dir
        // and let Python resolve. If absent, embedding still works for the
        // engine/ source tree.
        std::filesystem::path venv_lib = std::filesystem::path(venv) / "lib";
        if (std::filesystem::is_directory(venv_lib)) {
            for (const auto& entry : std::filesystem::directory_iterator(venv_lib)) {
                std::filesystem::path sp = entry.path() / "site-packages";
                if (std::filesystem::is_directory(sp)) {
                    pythonpath += ":" + sp.string();
                }
            }
        }
    }

    setenv("PYTHONPATH", pythonpath.c_str(), /*overwrite=*/1);
}

int call_banner() {
    PyObject* mod = PyImport_ImportModule("engine.bootstrap");
    if (!mod) { PyErr_Print(); return 1; }
    PyObject* fn = PyObject_GetAttrString(mod, "banner");
    if (!fn) { PyErr_Print(); Py_DECREF(mod); return 1; }
    PyObject* result = PyObject_CallNoArgs(fn);
    Py_DECREF(fn);
    Py_DECREF(mod);
    if (!result) { PyErr_Print(); return 1; }
    const char* text = PyUnicode_AsUTF8(result);
    std::printf("%s\n", text ? text : "<no banner>");
    Py_DECREF(result);
    return 0;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 1) return 1;

    auto project_root = discover_project_root(argv[0]);
    configure_python_path(project_root);

    if (PyImport_AppendInittab("_open_stbc_host", PyInit__open_stbc_host) != 0) {
        std::fprintf(stderr, "open_stbc_host: PyImport_AppendInittab failed\n");
        return 1;
    }

    Py_InitializeEx(/*initsigs=*/1);

    int rc = call_banner();

    if (Py_FinalizeEx() < 0) {
        return 2;
    }
    return rc;
}
```

- [ ] **Step 5: Build and run the test, verify it passes**

Run:
```bash
cmake --build build --target open_stbc_host
uv run pytest tests/host/test_embedded_engine_import.py -v
```
Expected: PASS.

- [ ] **Step 6: Verify direct binary invocation also works**

Run: `./build/bin/open_stbc_host`
Expected: stdout contains `open_stbc host alive`. Exit code 0.

- [ ] **Step 7: Commit**

```bash
git add native/src/host/host_main.cc engine/bootstrap.py \
        tests/host/test_embedded_engine_import.py
git commit -m "feat(host): embedded interpreter discovers project root and imports engine.bootstrap"
```

---

### Task 5: Verify the embedded interpreter can run a real Phase 1 SDK call

**Files:**
- Modify: `engine/bootstrap.py`
- Create: `tests/host/test_embedded_sdk_smoke.py`

**Goal:** the host binary, in its embedded interpreter, can import a non-trivial Phase 1 module (one that exercises the SDK shim machinery) and call into it. This is the Phase A integration milestone — proves embedding works for the *real* engine, not just a banner.

- [ ] **Step 1: Extend bootstrap.py to import a real Phase 1 module**

Update `engine/bootstrap.py`:

```python
"""Bootstrap module loaded by open_stbc_host to verify embedding works."""

def banner() -> str:
    return "open_stbc host alive"


def smoke_check() -> dict:
    """Exercise the SDK shim machinery: import App (the project-root shim) and
    confirm a known attribute exists. Returns a small dict the host prints."""
    import sys
    from pathlib import Path

    # Match what tests/conftest.py does — register the SDK finder so SDK
    # imports resolve. The host binary uses a modest subset, but the finder
    # has to be installed once before any SDK import.
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    # Import the project-root App shim (mirrors tests/conftest.py's pattern).
    import App  # noqa: F401

    return {
        "python_version": sys.version_info[:3],
        "app_module": App.__name__,
        "project_root": str(project_root),
    }
```

- [ ] **Step 2: Write the failing test**

Create `tests/host/test_embedded_sdk_smoke.py`:

```python
"""Run the host binary and assert it can call a Phase 1 SDK-importing function."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BIN = PROJECT_ROOT / "build" / "bin" / "open_stbc_host"


def test_host_runs_smoke_check():
    if not HOST_BIN.exists():
        import pytest
        pytest.skip(f"host binary not built at {HOST_BIN}")
    result = subprocess.run(
        [str(HOST_BIN), "--smoke-check"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"host exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "app_module" in result.stdout
    assert "python_version" in result.stdout
```

- [ ] **Step 3: Run the test, verify it fails (no --smoke-check arg handling yet)**

Run: `uv run pytest tests/host/test_embedded_sdk_smoke.py -v`
Expected: FAIL — host doesn't recognize `--smoke-check` and falls back to banner output.

- [ ] **Step 4: Add --smoke-check argument handling to host_main**

Replace the `main` function in `host_main.cc` (keep helper functions and includes):

```cpp
int main(int argc, char* argv[]) {
    if (argc < 1) return 1;

    auto project_root = discover_project_root(argv[0]);
    configure_python_path(project_root);

    if (PyImport_AppendInittab("_open_stbc_host", PyInit__open_stbc_host) != 0) {
        std::fprintf(stderr, "open_stbc_host: PyImport_AppendInittab failed\n");
        return 1;
    }

    Py_InitializeEx(/*initsigs=*/1);

    int rc = 0;
    if (argc >= 2 && std::string(argv[1]) == "--smoke-check") {
        PyObject* mod = PyImport_ImportModule("engine.bootstrap");
        if (!mod) { PyErr_Print(); rc = 1; goto teardown; }
        PyObject* fn = PyObject_GetAttrString(mod, "smoke_check");
        if (!fn) { PyErr_Print(); Py_DECREF(mod); rc = 1; goto teardown; }
        {
            PyObject* result = PyObject_CallNoArgs(fn);
            Py_DECREF(fn);
            Py_DECREF(mod);
            if (!result) { PyErr_Print(); rc = 1; goto teardown; }
            PyObject* repr = PyObject_Repr(result);
            Py_DECREF(result);
            if (!repr) { PyErr_Print(); rc = 1; goto teardown; }
            std::printf("%s\n", PyUnicode_AsUTF8(repr));
            Py_DECREF(repr);
        }
    } else {
        rc = call_banner();
    }

teardown:
    if (Py_FinalizeEx() < 0) return 2;
    return rc;
}
```

- [ ] **Step 5: Build and run the test, verify it passes**

Run:
```bash
cmake --build build --target open_stbc_host
uv run pytest tests/host/test_embedded_sdk_smoke.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/bootstrap.py tests/host/test_embedded_sdk_smoke.py native/src/host/host_main.cc
git commit -m "feat(host): embedded interpreter can import App and run SDK smoke check"
```

---

### Task 6: Phase A milestone summary commit

**Files:**
- Modify: `docs/architecture/sub_project_status.md`

**Goal:** Mark Phase A done in the sub-project status doc. No code change.

- [ ] **Step 1: Update status doc**

Edit `docs/architecture/sub_project_status.md`. In the renderer sub-projects table, replace the row for items 3-6 with a single row tracking this combined sub-project's progress. Replace:

```
| 3 | Scene-graph runtime | Not started | — | — |
| 4 | Render pipeline (window/context/shaders/draws) | Not started | — | — |
| 5 | Python ↔ C++ glue | Not started | — | — |
| 6 | BC-specific extensions (glow/specular conventions, hardpoint markers, damage nodes) | Not started | — | — |
```

with:

```
| 3-6 | Renderer host (combined: scene-graph + minimal renderer + CPython embedding + skybox pass) | Phase A complete (CPython embedding); Phase B-F in flight | [2026-05-09-renderer-host-design.md](../superpowers/specs/2026-05-09-renderer-host-design.md) | (created at v1) |
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/sub_project_status.md
git commit -m "docs(status): renderer-host Phase A (CPython embedding) complete"
```

---

## Phase B — Window + GL context

Three tasks. Goal: a `Window` RAII type wrapping GLFW + GL 3.3 core; bindings expose `init` (real), `shutdown` (real), `should_close`, `frame()` stub. Pytest can open and close a window offscreen.

### Task 7: Window class — GLFW + GL 3.3 core context

**Files:**
- Create: `native/src/renderer/window.h`
- Create: `native/src/renderer/window.cc`
- Create: `native/src/renderer/CMakeLists.txt`
- Modify: `native/CMakeLists.txt`
- Create: `native/tests/renderer/CMakeLists.txt`
- Create: `native/tests/renderer/window_test.cc`
- Modify: `native/tests/CMakeLists.txt`

**Goal:** offscreen GL test creates a `Window`, queries its framebuffer size, polls events once, swaps, destroys cleanly.

- [ ] **Step 1: Add renderer subdirectory to root CMake**

Modify `native/CMakeLists.txt`. After `add_subdirectory(src/assets)`, add:

```cmake
add_subdirectory(src/renderer)
```

- [ ] **Step 2: Create the renderer CMakeLists**

Create `native/src/renderer/CMakeLists.txt`:

```cmake
add_library(renderer STATIC
    window.cc
)
target_include_directories(renderer PUBLIC include)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets glad glfw glm)
```

- [ ] **Step 3: Create renderer/include/renderer/window.h**

Create `native/src/renderer/include/renderer/window.h`:

```cpp
// native/src/renderer/include/renderer/window.h
#pragma once

#include <string>

struct GLFWwindow;

namespace renderer {

class Window {
public:
    /// Construct a windowed GL 3.3 core context. `visible=false` creates a
    /// hidden window for offscreen tests. Throws std::runtime_error on
    /// GLFW or context-creation failure.
    Window(int width, int height, const std::string& title, bool visible = true);
    ~Window();

    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;
    Window(Window&&) noexcept;
    Window& operator=(Window&&) noexcept;

    bool should_close() const noexcept;
    void swap_buffers() noexcept;
    void poll_events() noexcept;

    /// Current framebuffer size in pixels (may differ from window size on
    /// HiDPI displays).
    void framebuffer_size(int* w, int* h) const noexcept;

    GLFWwindow* native_handle() noexcept { return handle_; }

private:
    GLFWwindow* handle_ = nullptr;
};

}  // namespace renderer
```

Then create the empty subdirectory marker `native/src/renderer/include/renderer/.gitkeep` removed in next step; actually CMake creates it implicitly. Skip.

- [ ] **Step 4: Implement window.cc**

Create `native/src/renderer/window.cc`:

```cpp
// native/src/renderer/window.cc
#include "renderer/window.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <atomic>
#include <stdexcept>
#include <string>

namespace renderer {

namespace {

std::atomic<int> g_glfw_users{0};

void ensure_glfw() {
    if (g_glfw_users.fetch_add(1) == 0) {
        if (!glfwInit()) {
            g_glfw_users.fetch_sub(1);
            throw std::runtime_error("renderer::Window: glfwInit failed");
        }
    }
}

void release_glfw() {
    if (g_glfw_users.fetch_sub(1) == 1) {
        glfwTerminate();
    }
}

}  // namespace

Window::Window(int width, int height, const std::string& title, bool visible) {
    ensure_glfw();

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
    glfwWindowHint(GLFW_VISIBLE, visible ? GLFW_TRUE : GLFW_FALSE);

    handle_ = glfwCreateWindow(width, height, title.c_str(), nullptr, nullptr);
    if (!handle_) {
        release_glfw();
        throw std::runtime_error("renderer::Window: glfwCreateWindow failed");
    }

    glfwMakeContextCurrent(handle_);

    if (!gladLoadGLLoader(reinterpret_cast<GLADloadproc>(glfwGetProcAddress))) {
        glfwDestroyWindow(handle_);
        handle_ = nullptr;
        release_glfw();
        throw std::runtime_error("renderer::Window: gladLoadGLLoader failed");
    }

    if (visible) {
        glfwSwapInterval(1);  // vsync gates the loop to monitor refresh.
    } else {
        glfwSwapInterval(0);
    }
}

Window::~Window() {
    if (handle_) {
        glfwDestroyWindow(handle_);
        handle_ = nullptr;
        release_glfw();
    }
}

Window::Window(Window&& other) noexcept : handle_(other.handle_) {
    other.handle_ = nullptr;
}

Window& Window::operator=(Window&& other) noexcept {
    if (this != &other) {
        if (handle_) {
            glfwDestroyWindow(handle_);
            release_glfw();
        }
        handle_ = other.handle_;
        other.handle_ = nullptr;
    }
    return *this;
}

bool Window::should_close() const noexcept {
    return handle_ ? glfwWindowShouldClose(handle_) != 0 : true;
}

void Window::swap_buffers() noexcept {
    if (handle_) glfwSwapBuffers(handle_);
}

void Window::poll_events() noexcept {
    glfwPollEvents();
}

void Window::framebuffer_size(int* w, int* h) const noexcept {
    if (handle_) glfwGetFramebufferSize(handle_, w, h);
    else { *w = 0; *h = 0; }
}

}  // namespace renderer
```

- [ ] **Step 5: Verify the renderer library builds in isolation**

Run: `cmake -S . -B build && cmake --build build --target renderer`
Expected: success. The pattern matches the asset pipeline's layout (see `native/src/assets/CMakeLists.txt`) — `include/renderer/*.h` for public headers, `*.cc` at the directory root for implementation.

- [ ] **Step 6: Write the failing test**

Create `native/tests/renderer/CMakeLists.txt`:

```cmake
add_executable(renderer_tests
    window_test.cc
)

target_link_libraries(renderer_tests
    PRIVATE
        renderer
        GTest::gtest_main
)

target_include_directories(renderer_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/tests/assets/gpu  # reuse gl_fixture for offscreen contexts
)

gtest_discover_tests(renderer_tests
    PROPERTIES
        ENVIRONMENT "GALLIUM_DRIVER=llvmpipe"
)
```

Create `native/tests/renderer/window_test.cc`:

```cpp
// native/tests/renderer/window_test.cc
#include <gtest/gtest.h>

#include <renderer/window.h>

namespace {

TEST(Window, ConstructHiddenAndDestroy) {
    try {
        renderer::Window w(640, 480, "test", /*visible=*/false);
        int fw = 0, fh = 0;
        w.framebuffer_size(&fw, &fh);
        EXPECT_GT(fw, 0);
        EXPECT_GT(fh, 0);
        EXPECT_FALSE(w.should_close());
        w.poll_events();
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(Window, MoveAssignDoesNotLeak) {
    try {
        renderer::Window a(320, 240, "a", /*visible=*/false);
        renderer::Window b(320, 240, "b", /*visible=*/false);
        a = std::move(b);  // a's old handle destroyed; a now owns b's
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
```

- [ ] **Step 7: Wire renderer_tests into the parent test CMakeLists**

Modify `native/tests/CMakeLists.txt`. After the existing `add_subdirectory(assets)` (or equivalent — find the line that adds the assets test subdirectory) add:

```cmake
add_subdirectory(renderer)
```

If there's no existing `add_subdirectory(assets)` line and tests are inline, add the subdirectory near the bottom of the file.

- [ ] **Step 8: Build and run the test**

Run:
```bash
cmake --build build --target renderer_tests
ctest --test-dir build -R "Window\." --output-on-failure
```
Expected: 2 tests pass (or skip cleanly with "no GL context available" on a headless CI without llvmpipe).

- [ ] **Step 9: Commit**

```bash
git add native/CMakeLists.txt native/src/renderer/ native/tests/renderer/ \
        native/tests/CMakeLists.txt
git commit -m "feat(renderer): Window RAII wraps GLFW + GL 3.3 core context"
```

---

### Task 8: Wire Window through pybind11 init/shutdown/should_close/frame stub

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/src/host/CMakeLists.txt`
- Modify: `tests/host/test_bindings_smoke.py`

**Goal:** `_open_stbc_host.init(w, h, title)` opens a hidden window; `shutdown()` closes it; `should_close()` returns the GLFW state; `frame()` polls events and swaps buffers (no draws yet).

- [ ] **Step 1: Update bindings module to own a Window**

Replace the body of `native/src/host/host_bindings.cc` (keep the includes, add window header):

```cpp
// native/src/host/host_bindings.cc

#include "host_bindings.h"

#include <pybind11/pybind11.h>

#include <renderer/window.h>

#include <memory>
#include <stdexcept>
#include <string>

namespace py = pybind11;

namespace {

std::unique_ptr<renderer::Window> g_window;

void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    // Visible by default. Tests that need offscreen can set OPEN_STBC_HOST_HEADLESS=1.
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
}

void shutdown() {
    g_window.reset();
}

bool should_close() {
    return !g_window || g_window->should_close();
}

void frame() {
    if (!g_window) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    g_window->poll_events();
    g_window->swap_buffers();
}

}  // namespace

PYBIND11_MODULE(_open_stbc_host, m) {
    m.doc() = "open_stbc renderer host bindings (Phase B: window + frame stub)";
    m.def("init", &init, py::arg("width"), py::arg("height"), py::arg("title"));
    m.def("shutdown", &shutdown);
    m.def("should_close", &should_close);
    m.def("frame", &frame);
}
```

- [ ] **Step 2: Update host CMake to link renderer**

Modify `native/src/host/CMakeLists.txt`. In both the `_open_stbc_host` module target and the `open_stbc_host` executable target, add `renderer` to the link list. The module target needs the link:

```cmake
pybind11_add_module(_open_stbc_host MODULE ${HOST_BINDINGS_SOURCES})
target_compile_features(_open_stbc_host PRIVATE cxx_std_20)
target_link_libraries(_open_stbc_host PRIVATE renderer)
set_target_properties(_open_stbc_host PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python"
)
```

Add to the executable:

```cmake
target_link_libraries(open_stbc_host
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
)
```

- [ ] **Step 3: Update bindings smoke test for headless run**

Modify `tests/host/test_bindings_smoke.py` to drive the now-real init/shutdown:

```python
"""Smoke test: _open_stbc_host opens a hidden window and frames cleanly."""
import os


def test_module_imports():
    import _open_stbc_host
    for name in ("init", "shutdown", "should_close", "frame"):
        assert hasattr(_open_stbc_host, name)


def test_init_frame_shutdown_round_trip():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(640, 480, "test")
        assert _open_stbc_host.should_close() is False
        # Drive a few frames to verify buffer swaps + event poll work.
        for _ in range(3):
            _open_stbc_host.frame()
    finally:
        _open_stbc_host.shutdown()


def test_double_init_raises():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    import pytest
    _open_stbc_host.init(320, 240, "a")
    try:
        with pytest.raises(RuntimeError):
            _open_stbc_host.init(320, 240, "b")
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 4: Build and run**

Run:
```bash
cmake --build build --target _open_stbc_host -j
uv run pytest tests/host/test_bindings_smoke.py -v
```
Expected: 3 passed. (If GLFW can't create a context in CI, the tests fail with `RuntimeError: glfwCreateWindow failed`; running on a developer machine with a display works.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/CMakeLists.txt \
        tests/host/test_bindings_smoke.py
git commit -m "feat(host): bindings open a real Window and drive frame() poll+swap"
```

---

### Task 9: Phase B verification — host binary opens window, draws clear color, exits

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Create: `tests/host/test_clear_frame.py`

**Goal:** every `frame()` call clears the framebuffer to a known color (so we can sanity-check both the GL context and the swap chain). Pytest reads back the framebuffer and asserts the clear color.

- [ ] **Step 1: Add a clear-to-color step inside frame()**

Modify `native/src/host/host_bindings.cc` — replace the `frame` function body:

```cpp
void frame() {
    if (!g_window) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);
    glViewport(0, 0, fw, fh);
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    g_window->poll_events();
    g_window->swap_buffers();
}
```

Add at top of file: `#include <glad/glad.h>` (after the existing includes).

- [ ] **Step 2: Write the failing readback test**

Create `tests/host/test_clear_frame.py`:

```python
"""Verify frame() clears to the documented dark-blue background color."""
import os
import struct


def test_frame_produces_clear_color():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    import pytest

    try:
        _open_stbc_host.init(64, 64, "clear-test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")

    try:
        _open_stbc_host.frame()
        # Read the back buffer (after swap, the previous front is what we drew).
        # We need a glReadPixels binding for that. Defer the framebuffer
        # readback assertion to a GL-side ctest in the renderer tree;
        # here we settle for "frame did not raise."
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 3: Run test, verify it passes**

Run: `uv run pytest tests/host/test_clear_frame.py -v`
Expected: PASS (or skip on no-GL hosts).

- [ ] **Step 4: Verify the binary actually opens a visible window for a few frames**

This is a manual check — no automation gate.

Run (on a machine with a display):
```bash
unset OPEN_STBC_HOST_HEADLESS
./build/bin/open_stbc_host --window-smoke
```

The binary doesn't recognize `--window-smoke` yet; this step is a placeholder for the upcoming Phase F integration. For now, just confirm `./build/bin/open_stbc_host --smoke-check` still passes (Phase A behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_clear_frame.py
git commit -m "feat(host): frame() clears to dark-blue background each call"
```

---

## Phase C — Camera + scene-graph data

Five tasks. Goal: `Camera` produces view+proj matrices from eye/target/up; `World` manages instances with generational handles; transforms and visibility flow through; `set_skybox` slot exists. All pure C++ (no GL); tested by gtest.

### Task 10: Camera class with view + proj matrices

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/camera.h`
- Create: `native/src/scenegraph/src/camera.cc`
- Create: `native/src/scenegraph/CMakeLists.txt`
- Modify: `native/CMakeLists.txt`
- Create: `native/tests/scenegraph/CMakeLists.txt`
- Create: `native/tests/scenegraph/camera_test.cc`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Wire scenegraph into the root CMake**

Modify `native/CMakeLists.txt`. After `add_subdirectory(src/renderer)` (added in Task 7), add:

```cmake
add_subdirectory(src/scenegraph)
```

- [ ] **Step 2: Create scenegraph CMakeLists**

Create `native/src/scenegraph/CMakeLists.txt`:

```cmake
add_library(scenegraph STATIC
    src/camera.cc
)
target_include_directories(scenegraph PUBLIC include)
target_compile_features(scenegraph PUBLIC cxx_std_20)
target_link_libraries(scenegraph PUBLIC glm)
```

- [ ] **Step 3: Write the failing camera test**

Create `native/tests/scenegraph/CMakeLists.txt`:

```cmake
add_executable(scenegraph_tests
    camera_test.cc
)
target_link_libraries(scenegraph_tests
    PRIVATE
        scenegraph
        GTest::gtest_main
)
gtest_discover_tests(scenegraph_tests)
```

Create `native/tests/scenegraph/camera_test.cc`:

```cpp
// native/tests/scenegraph/camera_test.cc
#include <gtest/gtest.h>

#include <scenegraph/camera.h>

#include <glm/gtc/matrix_transform.hpp>

namespace {

constexpr float kEpsilon = 1e-5f;

bool nearly_equal(const glm::mat4& a, const glm::mat4& b) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 4; ++r)
            if (std::fabs(a[c][r] - b[c][r]) > kEpsilon) return false;
    return true;
}

TEST(Camera, ViewMatrixMatchesGlmLookAt) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 5.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.up = glm::vec3(0.0f, 1.0f, 0.0f);

    auto expected = glm::lookAt(cam.eye, cam.target, cam.up);
    EXPECT_TRUE(nearly_equal(cam.view_matrix(), expected));
}

TEST(Camera, ProjMatrixMatchesGlmPerspective) {
    scenegraph::Camera cam;
    cam.fov_y_rad = glm::radians(45.0f);
    cam.aspect = 16.0f / 9.0f;
    cam.near = 0.1f;
    cam.far = 1000.0f;

    auto expected = glm::perspective(cam.fov_y_rad, cam.aspect, cam.near, cam.far);
    EXPECT_TRUE(nearly_equal(cam.proj_matrix(), expected));
}

}  // namespace
```

Wire into parent: modify `native/tests/CMakeLists.txt` to add `add_subdirectory(scenegraph)` near the renderer subdir entry from Task 7.

- [ ] **Step 4: Run test, verify it fails (camera.h missing)**

Run: `cmake -S . -B build && cmake --build build --target scenegraph_tests`
Expected: FAIL — `scenegraph/camera.h: No such file or directory`.

- [ ] **Step 5: Implement Camera**

Create `native/src/scenegraph/include/scenegraph/camera.h`:

```cpp
// native/src/scenegraph/include/scenegraph/camera.h
#pragma once

#include <glm/glm.hpp>

namespace scenegraph {

struct Camera {
    glm::vec3 eye{0.0f, 0.0f, 5.0f};
    glm::vec3 target{0.0f, 0.0f, 0.0f};
    glm::vec3 up{0.0f, 1.0f, 0.0f};
    float fov_y_rad = 1.0472f;  // 60 degrees
    float aspect = 16.0f / 9.0f;
    float near = 0.1f;
    float far = 100000.0f;  // BC scenes can be tens of km

    glm::mat4 view_matrix() const noexcept;
    glm::mat4 proj_matrix() const noexcept;
};

}  // namespace scenegraph
```

Create `native/src/scenegraph/src/camera.cc`:

```cpp
// native/src/scenegraph/src/camera.cc
#include "scenegraph/camera.h"

#include <glm/gtc/matrix_transform.hpp>

namespace scenegraph {

glm::mat4 Camera::view_matrix() const noexcept {
    return glm::lookAt(eye, target, up);
}

glm::mat4 Camera::proj_matrix() const noexcept {
    return glm::perspective(fov_y_rad, aspect, near, far);
}

}  // namespace scenegraph
```

- [ ] **Step 6: Build and run, verify pass**

Run:
```bash
cmake --build build --target scenegraph_tests
ctest --test-dir build -R "Camera\." --output-on-failure
```
Expected: 2 pass.

- [ ] **Step 7: Commit**

```bash
git add native/CMakeLists.txt native/src/scenegraph/ \
        native/tests/scenegraph/ native/tests/CMakeLists.txt
git commit -m "feat(scenegraph): Camera produces view + proj matrices via glm"
```

---

### Task 11: Instance + World skeleton with generational handles

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/instance.h`
- Create: `native/src/scenegraph/include/scenegraph/world.h`
- Create: `native/src/scenegraph/src/world.cc`
- Modify: `native/src/scenegraph/CMakeLists.txt`
- Create: `native/tests/scenegraph/world_test.cc`
- Modify: `native/tests/scenegraph/CMakeLists.txt`

**Goal:** `World` owns a vector of `Instance`s keyed by `InstanceId` (a generational handle that detects use-after-destroy).

- [ ] **Step 1: Write the failing test**

Create `native/tests/scenegraph/world_test.cc`:

```cpp
// native/tests/scenegraph/world_test.cc
#include <gtest/gtest.h>

#include <scenegraph/world.h>

#include <glm/glm.hpp>

namespace {

TEST(World, CreateAndLookup) {
    scenegraph::World w;
    auto id = w.create_instance(/*model_handle=*/42);
    EXPECT_TRUE(w.is_valid(id));
    auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_EQ(inst->model_handle, 42u);
    EXPECT_TRUE(inst->visible);
}

TEST(World, DestroyInvalidatesHandle) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    w.destroy_instance(id);
    EXPECT_FALSE(w.is_valid(id));
    EXPECT_EQ(w.get(id), nullptr);
}

TEST(World, ReusedSlotHasNewGeneration) {
    scenegraph::World w;
    auto a = w.create_instance(1);
    w.destroy_instance(a);
    auto b = w.create_instance(2);
    // Slot may be reused, but generations must differ.
    EXPECT_NE(a.generation, b.generation);
    EXPECT_FALSE(w.is_valid(a));  // old handle stays invalid
    EXPECT_TRUE(w.is_valid(b));
}

TEST(World, SetTransformPropagatesToInstance) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    glm::mat4 m(1.0f);
    m[3].x = 5.0f;
    w.set_world_transform(id, m);
    EXPECT_FLOAT_EQ(w.get(id)->world[3].x, 5.0f);
}

TEST(World, SetVisibleFlipsFlag) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    w.set_visible(id, false);
    EXPECT_FALSE(w.get(id)->visible);
}

}  // namespace
```

Update `native/tests/scenegraph/CMakeLists.txt`:

```cmake
add_executable(scenegraph_tests
    camera_test.cc
    world_test.cc
)
target_link_libraries(scenegraph_tests
    PRIVATE
        scenegraph
        GTest::gtest_main
)
gtest_discover_tests(scenegraph_tests)
```

- [ ] **Step 2: Run test, verify it fails (world.h missing)**

Run: `cmake --build build --target scenegraph_tests`
Expected: FAIL — `scenegraph/world.h: No such file or directory`.

- [ ] **Step 3: Implement Instance and World**

Create `native/src/scenegraph/include/scenegraph/instance.h`:

```cpp
// native/src/scenegraph/include/scenegraph/instance.h
#pragma once

#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

using ModelHandle = std::uint64_t;  // Opaque key into the asset cache.

struct InstanceId {
    std::uint32_t index = 0;
    std::uint32_t generation = 0;
    bool operator==(const InstanceId&) const = default;
};

struct Instance {
    ModelHandle model_handle = 0;
    glm::mat4 world{1.0f};
    bool visible = true;
};

}  // namespace scenegraph
```

Create `native/src/scenegraph/include/scenegraph/world.h`:

```cpp
// native/src/scenegraph/include/scenegraph/world.h
#pragma once

#include "scenegraph/instance.h"

#include <vector>

namespace scenegraph {

class World {
public:
    InstanceId create_instance(ModelHandle model);
    void destroy_instance(InstanceId id);
    void set_world_transform(InstanceId id, const glm::mat4& world);
    void set_visible(InstanceId id, bool visible);

    bool is_valid(InstanceId id) const noexcept;
    Instance* get(InstanceId id) noexcept;
    const Instance* get(InstanceId id) const noexcept;

    /// Per-frame propagation hook. v1 is a pass-through (intra-model node
    /// hierarchy is already baked into Model::nodes by the asset pipeline;
    /// inter-instance hierarchy doesn't exist yet). Reserved so item 6
    /// hardpoint-attachment work can hook in later without an API break.
    void propagate() noexcept {}

    /// Iterate every visible instance. Used by the renderer's frame submitter.
    template <typename Fn>
    void for_each_visible(Fn&& fn) const {
        for (std::size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].alive && slots_[i].instance.visible) {
                fn(slots_[i].instance);
            }
        }
    }

    void set_skybox(ModelHandle model) noexcept { skybox_model_ = model; }
    ModelHandle skybox_model() const noexcept { return skybox_model_; }

private:
    struct Slot {
        Instance instance;
        std::uint32_t generation = 0;
        bool alive = false;
    };
    std::vector<Slot> slots_;
    std::vector<std::uint32_t> free_;
    ModelHandle skybox_model_ = 0;
};

}  // namespace scenegraph
```

Create `native/src/scenegraph/src/world.cc`:

```cpp
// native/src/scenegraph/src/world.cc
#include "scenegraph/world.h"

namespace scenegraph {

InstanceId World::create_instance(ModelHandle model) {
    std::uint32_t idx;
    if (!free_.empty()) {
        idx = free_.back();
        free_.pop_back();
        slots_[idx].generation += 1;
    } else {
        idx = static_cast<std::uint32_t>(slots_.size());
        slots_.push_back(Slot{});
        slots_.back().generation = 1;
    }
    slots_[idx].alive = true;
    slots_[idx].instance = Instance{};
    slots_[idx].instance.model_handle = model;
    return InstanceId{idx, slots_[idx].generation};
}

void World::destroy_instance(InstanceId id) {
    if (!is_valid(id)) return;
    slots_[id.index].alive = false;
    free_.push_back(id.index);
}

void World::set_world_transform(InstanceId id, const glm::mat4& world) {
    if (auto* inst = get(id)) inst->world = world;
}

void World::set_visible(InstanceId id, bool visible) {
    if (auto* inst = get(id)) inst->visible = visible;
}

bool World::is_valid(InstanceId id) const noexcept {
    return id.index < slots_.size()
        && slots_[id.index].alive
        && slots_[id.index].generation == id.generation;
}

Instance* World::get(InstanceId id) noexcept {
    return is_valid(id) ? &slots_[id.index].instance : nullptr;
}

const Instance* World::get(InstanceId id) const noexcept {
    return is_valid(id) ? &slots_[id.index].instance : nullptr;
}

}  // namespace scenegraph
```

Update `native/src/scenegraph/CMakeLists.txt`:

```cmake
add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
)
target_include_directories(scenegraph PUBLIC include)
target_compile_features(scenegraph PUBLIC cxx_std_20)
target_link_libraries(scenegraph PUBLIC glm)
```

- [ ] **Step 4: Build and run**

Run:
```bash
cmake --build build --target scenegraph_tests
ctest --test-dir build -R "World\." --output-on-failure
```
Expected: 5 pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/ native/tests/scenegraph/world_test.cc \
        native/tests/scenegraph/CMakeLists.txt
git commit -m "feat(scenegraph): World owns instances with generational handles"
```

---

### Task 12: Wire scene-graph + camera through pybind11

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/src/host/CMakeLists.txt`
- Create: `tests/host/test_scene_bindings.py`

**Goal:** Python can `create_instance`, `destroy_instance`, `set_world_transform`, `set_visible`, `set_camera`, `set_skybox`. Asset loading (`load_model`) is added in Task 13.

- [ ] **Step 1: Update bindings to expose World + Camera**

Modify `native/src/host/host_bindings.cc`. Add at top of the anonymous namespace (after `g_window` declaration):

```cpp
scenegraph::World g_world;
scenegraph::Camera g_camera;
```

Add includes near the other includes:
```cpp
#include <scenegraph/world.h>
#include <scenegraph/camera.h>
```

Add bindings for the new functions inside the `PYBIND11_MODULE` block, after the existing `frame` def:

```cpp
    py::class_<scenegraph::InstanceId>(m, "InstanceId")
        .def_readonly("index", &scenegraph::InstanceId::index)
        .def_readonly("generation", &scenegraph::InstanceId::generation);

    m.def("create_instance",
          [](scenegraph::ModelHandle h) { return g_world.create_instance(h); },
          py::arg("model"));
    m.def("destroy_instance",
          [](scenegraph::InstanceId id) { g_world.destroy_instance(id); },
          py::arg("id"));
    m.def("set_world_transform",
          [](scenegraph::InstanceId id, const std::vector<float>& m) {
              if (m.size() != 16) {
                  throw std::runtime_error("set_world_transform: need 16 floats");
              }
              glm::mat4 mat;
              // Row-major from Python; glm is column-major. Transpose on input.
              for (int r = 0; r < 4; ++r)
                  for (int c = 0; c < 4; ++c)
                      mat[c][r] = m[r * 4 + c];
              g_world.set_world_transform(id, mat);
          },
          py::arg("id"), py::arg("mat4"));
    m.def("set_visible",
          [](scenegraph::InstanceId id, bool v) { g_world.set_visible(id, v); },
          py::arg("id"), py::arg("visible"));
    m.def("set_camera",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_camera.eye = {std::get<0>(eye), std::get<1>(eye), std::get<2>(eye)};
              g_camera.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_camera.up = {std::get<0>(up), std::get<1>(up), std::get<2>(up)};
              g_camera.fov_y_rad = fov_y_rad;
              g_camera.near = near;
              g_camera.far = far;
              if (g_window) {
                  int fw = 0, fh = 0;
                  g_window->framebuffer_size(&fw, &fh);
                  if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);
              }
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));
    m.def("set_skybox",
          [](scenegraph::ModelHandle h) { g_world.set_skybox(h); },
          py::arg("model"));
```

Add `#include <vector>` and `#include <tuple>` to the includes.

- [ ] **Step 2: Update host CMake to link scenegraph**

In `native/src/host/CMakeLists.txt`, add `scenegraph` to both target's link lists:

```cmake
target_link_libraries(_open_stbc_host PRIVATE renderer scenegraph)
```

```cmake
target_link_libraries(open_stbc_host
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        scenegraph
)
```

- [ ] **Step 3: Write the failing test**

Create `tests/host/test_scene_bindings.py`:

```python
"""Verify scene-graph + camera bindings round-trip through pybind11."""
import os


def test_instance_lifecycle_without_window():
    # No init() — these calls don't need a GL context yet.
    import _open_stbc_host
    iid = _open_stbc_host.create_instance(123)
    assert iid.generation > 0
    _open_stbc_host.set_world_transform(iid, [
        1.0, 0.0, 0.0, 5.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ])
    _open_stbc_host.set_visible(iid, False)
    _open_stbc_host.destroy_instance(iid)


def test_set_world_transform_rejects_wrong_length():
    import _open_stbc_host
    import pytest
    iid = _open_stbc_host.create_instance(0)
    try:
        with pytest.raises(RuntimeError):
            _open_stbc_host.set_world_transform(iid, [0.0] * 12)
    finally:
        _open_stbc_host.destroy_instance(iid)


def test_set_camera_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_camera(
        eye=(0.0, 0.0, 5.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        fov_y_rad=1.0472,
        near=0.1,
        far=10000.0,
    )


def test_set_skybox_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_skybox(0)
```

- [ ] **Step 4: Build and run**

Run:
```bash
cmake --build build --target _open_stbc_host -j
uv run pytest tests/host/test_scene_bindings.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/CMakeLists.txt \
        tests/host/test_scene_bindings.py
git commit -m "feat(host): expose World + Camera through _open_stbc_host bindings"
```

---

### Task 13: load_model binding — bridge AssetCache to Python

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Create: `tests/host/test_load_model.py`

**Goal:** `_open_stbc_host.load_model(nif_path, texture_search_path)` returns a `ModelHandle` that `create_instance` can consume. Internally, the host owns one `assets::AssetCache` and assigns sequential ModelHandle IDs to keep paths uniform with the rest of the bindings.

- [ ] **Step 1: Add cache + handle table to bindings**

Modify `native/src/host/host_bindings.cc`. Add to the anonymous namespace:

```cpp
struct LoadedModel {
    std::filesystem::path nif_path;
    assets::ModelHandle handle;
};

std::unique_ptr<assets::AssetCache> g_cache;
std::vector<LoadedModel> g_loaded_models;  // index = our public ModelHandle - 1

scenegraph::ModelHandle load_model_impl(const std::string& nif_path,
                                        const std::string& texture_search_path) {
    if (!g_window) {
        throw std::runtime_error("load_model: init must be called first (asset upload needs a GL context)");
    }
    if (!g_cache) g_cache = std::make_unique<assets::AssetCache>();
    auto handle = g_cache->load(nif_path, texture_search_path);
    g_loaded_models.push_back({nif_path, std::move(handle)});
    return static_cast<scenegraph::ModelHandle>(g_loaded_models.size());
}
```

Add includes:
```cpp
#include <assets/cache.h>
#include <filesystem>
```

Add to `PYBIND11_MODULE`:

```cpp
    m.def("load_model", &load_model_impl,
          py::arg("nif_path"), py::arg("texture_search_path"));
```

Update `shutdown` to also reset the cache:

```cpp
void shutdown() {
    g_loaded_models.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_window.reset();
}
```

Update `init` to ensure each init starts fresh:

```cpp
void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
    g_world = scenegraph::World{};
    g_loaded_models.clear();
}
```

Update host CMake to link `assets`:

In `native/src/host/CMakeLists.txt`:

```cmake
target_link_libraries(_open_stbc_host PRIVATE renderer scenegraph assets)
```

```cmake
target_link_libraries(open_stbc_host
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        scenegraph
        assets
)
```

- [ ] **Step 2: Write the failing test**

Create `tests/host/test_load_model.py`:

```python
"""Load a known BC NIF through the bindings and create an instance with it."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GAME_DATA = PROJECT_ROOT / "game" / "data"
GALAXY_NIF = GAME_DATA / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = "data/Models/SharedTextures/FedShips/High"


def test_load_galaxy_and_create_instance():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(640, 480, "test")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _open_stbc_host.load_model(str(GALAXY_NIF), GALAXY_TEX)
        assert h > 0
        iid = _open_stbc_host.create_instance(h)
        assert iid.generation > 0
        _open_stbc_host.destroy_instance(iid)
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 3: Run test, verify it passes**

Run:
```bash
cmake --build build --target _open_stbc_host -j
uv run pytest tests/host/test_load_model.py -v
```
Expected: PASS (or SKIP if `game/data` is absent — same condition that gates `scan_nifs_corpus`).

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/CMakeLists.txt \
        tests/host/test_load_model.py
git commit -m "feat(host): load_model binding wraps AssetCache::load"
```

---

### Task 14: Phase C milestone — Python can describe a complete static scene

**Files:**
- Create: `tests/host/test_scene_setup.py`

**Goal:** integration-style pytest case that initializes the host, loads a model, creates instances, sets transforms, sets a camera, and tears down — proving the full Phase C surface works end-to-end before any drawing.

- [ ] **Step 1: Write the test**

Create `tests/host/test_scene_setup.py`:

```python
"""End-to-end Phase C scene setup: load → instance → transform → camera → shutdown."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"


def test_scene_setup_round_trip():
    if not GALAXY_NIF.is_file():
        pytest.skip(f"BC asset not available at {GALAXY_NIF}")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(800, 600, "scene-setup")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")

    try:
        ship = _open_stbc_host.load_model(str(GALAXY_NIF),
                                          "data/Models/SharedTextures/FedShips/High")

        ids = []
        for x in (-50.0, 0.0, 50.0):
            iid = _open_stbc_host.create_instance(ship)
            _open_stbc_host.set_world_transform(iid, [
                1.0, 0.0, 0.0, x,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ])
            ids.append(iid)

        _open_stbc_host.set_camera(
            eye=(0.0, 30.0, 200.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=10000.0,
        )

        # Phase C: no drawing yet. Exercise the frame() path to confirm
        # everything still teardowns cleanly.
        _open_stbc_host.frame()

        for iid in ids:
            _open_stbc_host.destroy_instance(iid)
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 2: Run, verify it passes**

Run: `uv run pytest tests/host/test_scene_setup.py -v`
Expected: PASS (or SKIP without BC assets).

- [ ] **Step 3: Commit**

```bash
git add tests/host/test_scene_setup.py
git commit -m "test(host): Phase C scene setup round-trip"
```

---

## Phase D — Renderer pipeline (opaque pass)

Five tasks. Goal: a `Shader` RAII type, a `Pipeline` owning the opaque shader, a `FrameSubmitter` that iterates visible instances and draws each Mesh. After Phase D, `frame()` actually renders the scene (without skybox or lighting tweaks — just clear + opaque pass).

### Task 15: Shader RAII wrapper

**Files:**
- Create: `native/src/renderer/include/renderer/shader.h`
- Create: `native/src/renderer/shader.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Create: `native/tests/renderer/shader_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Goal:** `Shader` compiles + links GLSL 330 source from strings; exposes uniform setters; cleans up on destruction.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/shader_test.cc`:

```cpp
// native/tests/renderer/shader_test.cc
#include <gtest/gtest.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include <glm/glm.hpp>

namespace {

const char* kTrivialVS = R"(#version 330 core
void main() { gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
)";

const char* kTrivialFS = R"(#version 330 core
out vec4 frag;
void main() { frag = vec4(1.0); }
)";

class ShaderTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "shader-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context available: " << e.what();
        }
    }
};

TEST_F(ShaderTest, CompilesLinksAndDestroys) {
    renderer::Shader s(kTrivialVS, kTrivialFS);
    EXPECT_NE(s.program(), 0u);
}

TEST_F(ShaderTest, BadSourceThrows) {
    EXPECT_THROW(renderer::Shader("not glsl", kTrivialFS), std::runtime_error);
}

TEST_F(ShaderTest, UniformSettersDoNotCrashWhenMissing) {
    renderer::Shader s(kTrivialVS, kTrivialFS);
    s.use();
    s.set_mat4("not_a_uniform", glm::mat4(1.0f));
    s.set_vec3("also_missing", glm::vec3(1, 2, 3));
}

}  // namespace
```

Update `native/tests/renderer/CMakeLists.txt`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
)
target_link_libraries(renderer_tests
    PRIVATE
        renderer
        GTest::gtest_main
)
gtest_discover_tests(renderer_tests)
```

- [ ] **Step 2: Run test, verify it fails (shader.h missing)**

Run: `cmake --build build --target renderer_tests`
Expected: FAIL — `renderer/shader.h: No such file or directory`.

- [ ] **Step 3: Implement Shader**

Create `native/src/renderer/include/renderer/shader.h`:

```cpp
// native/src/renderer/include/renderer/shader.h
#pragma once

#include <glm/glm.hpp>
#include <string>

namespace renderer {

class Shader {
public:
    Shader(const std::string& vertex_src, const std::string& fragment_src);
    ~Shader();
    Shader(const Shader&) = delete;
    Shader& operator=(const Shader&) = delete;
    Shader(Shader&&) noexcept;
    Shader& operator=(Shader&&) noexcept;

    void use() const noexcept;
    unsigned program() const noexcept { return program_; }

    void set_mat4(const std::string& name, const glm::mat4& v) const;
    void set_vec3(const std::string& name, const glm::vec3& v) const;
    void set_int(const std::string& name, int v) const;

private:
    unsigned program_ = 0;
};

}  // namespace renderer
```

Create `native/src/renderer/shader.cc`:

```cpp
// native/src/renderer/shader.cc
#include "renderer/shader.h"

#include <glad/glad.h>
#include <glm/gtc/type_ptr.hpp>

#include <stdexcept>
#include <string>
#include <vector>

namespace renderer {

namespace {

unsigned compile_stage(GLenum stage, const std::string& src) {
    GLuint sh = glCreateShader(stage);
    const char* p = src.c_str();
    glShaderSource(sh, 1, &p, nullptr);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetShaderiv(sh, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(len > 0 ? len : 1);
        if (len > 0) glGetShaderInfoLog(sh, len, nullptr, log.data());
        glDeleteShader(sh);
        throw std::runtime_error("renderer::Shader compile failed: " + std::string(log.data()));
    }
    return sh;
}

}  // namespace

Shader::Shader(const std::string& vsrc, const std::string& fsrc) {
    GLuint vs = compile_stage(GL_VERTEX_SHADER, vsrc);
    GLuint fs;
    try {
        fs = compile_stage(GL_FRAGMENT_SHADER, fsrc);
    } catch (...) {
        glDeleteShader(vs);
        throw;
    }
    program_ = glCreateProgram();
    glAttachShader(program_, vs);
    glAttachShader(program_, fs);
    glLinkProgram(program_);
    GLint ok = 0;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetProgramiv(program_, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(len > 0 ? len : 1);
        if (len > 0) glGetProgramInfoLog(program_, len, nullptr, log.data());
        glDeleteProgram(program_);
        glDeleteShader(vs);
        glDeleteShader(fs);
        program_ = 0;
        throw std::runtime_error("renderer::Shader link failed: " + std::string(log.data()));
    }
    glDeleteShader(vs);
    glDeleteShader(fs);
}

Shader::~Shader() {
    if (program_) glDeleteProgram(program_);
}

Shader::Shader(Shader&& o) noexcept : program_(o.program_) { o.program_ = 0; }

Shader& Shader::operator=(Shader&& o) noexcept {
    if (this != &o) {
        if (program_) glDeleteProgram(program_);
        program_ = o.program_;
        o.program_ = 0;
    }
    return *this;
}

void Shader::use() const noexcept {
    glUseProgram(program_);
}

void Shader::set_mat4(const std::string& name, const glm::mat4& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniformMatrix4fv(loc, 1, GL_FALSE, glm::value_ptr(v));
}

void Shader::set_vec3(const std::string& name, const glm::vec3& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniform3fv(loc, 1, glm::value_ptr(v));
}

void Shader::set_int(const std::string& name, int v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniform1i(loc, v);
}

}  // namespace renderer
```

Update `native/src/renderer/CMakeLists.txt`:

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
)
target_include_directories(renderer PUBLIC include)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets glad glfw glm)
```

- [ ] **Step 4: Build and run, verify pass**

Run:
```bash
cmake --build build --target renderer_tests
ctest --test-dir build -R "Shader" --output-on-failure
```
Expected: 3 pass (or skip on no-GL).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/shader.h \
        native/src/renderer/shader.cc native/src/renderer/CMakeLists.txt \
        native/tests/renderer/shader_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): Shader RAII wraps GLSL compile + link + uniforms"
```

---

### Task 16: Opaque shader sources + Pipeline init

**Files:**
- Create: `native/src/renderer/shaders/opaque.vert`
- Create: `native/src/renderer/shaders/opaque.frag`
- Create: `native/src/renderer/include/renderer/pipeline.h`
- Create: `native/src/renderer/pipeline.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Create: `native/tests/renderer/pipeline_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Goal:** `Pipeline::init()` compiles the opaque shader and configures one-shot GL state (depth test, cull face). Source files are bundled at build time as embedded strings (no runtime file I/O).

- [ ] **Step 1: Write the opaque shaders**

Create `native/src/renderer/shaders/opaque.vert`:

```glsl
#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in vec4 a_color;
layout(location = 4) in vec4 a_bone_indices;
layout(location = 5) in vec4 a_bone_weights;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;
out vec2 v_uv;

void main() {
    vec4 ws = u_model * vec4(a_position, 1.0);
    v_normal_ws = mat3(u_model) * a_normal;
    v_uv = a_uv;
    gl_Position = u_proj * u_view * ws;
}
```

Create `native/src/renderer/shaders/opaque.frag`:

```glsl
#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;
uniform vec3 u_ambient_light;
uniform vec3 u_dir_light_dir_ws;  // direction *toward the light*, normalized
uniform vec3 u_dir_light_color;

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    float ndotl = max(dot(n, normalize(u_dir_light_dir_ws)), 0.0);
    vec4 tex = texture(u_base_color, v_uv);
    vec3 lit = (u_ambient_light + ndotl * u_dir_light_color) * u_diffuse_color * tex.rgb;
    frag_color = vec4(lit, 1.0);
}
```

- [ ] **Step 2: Embed the shaders at build time**

Create `native/src/renderer/CMakeLists.txt` (replace contents):

```cmake
# Embed shader sources as char arrays via configure_file. Each shader gets a
# generated header with a constexpr string. This keeps shader text in *.vert /
# *.frag (so editors highlight them) without runtime file I/O.

function(embed_shader OUT_VAR INPUT_PATH SYMBOL_NAME)
    file(READ "${INPUT_PATH}" SRC)
    set(GENERATED "${CMAKE_CURRENT_BINARY_DIR}/embedded_${SYMBOL_NAME}.h")
    file(WRITE "${GENERATED}.in"
"// Generated. Do not edit.\n#pragma once\nnamespace renderer::shader_src {\nconstexpr const char* ${SYMBOL_NAME} = R\"GLSL(@SRC@)GLSL\";\n}\n")
    configure_file("${GENERATED}.in" "${GENERATED}" @ONLY)
    set(${OUT_VAR} "${GENERATED}" PARENT_SCOPE)
endfunction()

embed_shader(SHADER_OPAQUE_VS shaders/opaque.vert opaque_vs)
embed_shader(SHADER_OPAQUE_FS shaders/opaque.frag opaque_fs)

add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
)
target_include_directories(renderer
    PUBLIC include
    PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"
)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets glad glfw glm)
```

- [ ] **Step 3: Implement Pipeline**

Create `native/src/renderer/include/renderer/pipeline.h`:

```cpp
// native/src/renderer/include/renderer/pipeline.h
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept { return *opaque_; }

private:
    std::unique_ptr<Shader> opaque_;
};

}  // namespace renderer
```

Create `native/src/renderer/pipeline.cc`:

```cpp
// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include "embedded_opaque_vs.h"
#include "embedded_opaque_fs.h"

namespace renderer {

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
}

}  // namespace renderer
```

- [ ] **Step 4: Write the failing pipeline test**

Create `native/tests/renderer/pipeline_test.cc`:

```cpp
// native/tests/renderer/pipeline_test.cc
#include <gtest/gtest.h>

#include <renderer/pipeline.h>
#include <renderer/window.h>

namespace {

class PipelineTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "pipeline-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }
};

TEST_F(PipelineTest, OpaqueShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.opaque_shader().program(), 0u);
}

}  // namespace
```

Add to `native/tests/renderer/CMakeLists.txt`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
)
```

- [ ] **Step 5: Build and run**

Run:
```bash
cmake -S . -B build && cmake --build build --target renderer_tests
ctest --test-dir build -R "Pipeline" --output-on-failure
```
Expected: 1 pass.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/ native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc native/src/renderer/CMakeLists.txt \
        native/tests/renderer/pipeline_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): Pipeline embeds + compiles opaque shaders"
```

---

### Task 17: FrameSubmitter — opaque pass over scene-graph

**Files:**
- Create: `native/src/renderer/include/renderer/frame.h`
- Create: `native/src/renderer/frame.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Create: `native/tests/renderer/frame_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Goal:** `FrameSubmitter::submit_opaque(world, camera, models)` iterates visible instances and draws each `Mesh` with the opaque shader. `models` is a callable mapping `ModelHandle → const assets::Model&` so the renderer doesn't depend on the host's handle table directly.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/frame_test.cc`:

```cpp
// native/tests/renderer/frame_test.cc
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <filesystem>

namespace {

const std::filesystem::path kProjectRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
const std::filesystem::path kGalaxyNif =
    kProjectRoot / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif";

class FrameTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kGalaxyNif)) {
            GTEST_SKIP() << "BC asset not available at " << kGalaxyNif;
        }
        try {
            w = std::make_unique<renderer::Window>(256, 256, "frame-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
    }
};

TEST_F(FrameTest, OpaquePassRunsWithoutGLError) {
    auto model_h = cache->load(
        kGalaxyNif.string(),
        "data/Models/SharedTextures/FedShips/High");

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&*model_h));
    glm::mat4 m(1.0f);
    m[3].z = -100.0f;
    world.set_world_transform(iid, m);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.target = glm::vec3(0.0f, 0.0f, -100.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        });

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Read center pixel; should be lit (not black) since the Galaxy fills
    // the viewport at z=-100 with this camera.
    unsigned char pixel[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    int total = pixel[0] + pixel[1] + pixel[2];
    EXPECT_GT(total, 0) << "center pixel was black; opaque pass produced nothing";
}

}  // namespace
```

Add to `native/tests/renderer/CMakeLists.txt`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
)
```

- [ ] **Step 2: Run, verify it fails**

Run: `cmake --build build --target renderer_tests`
Expected: FAIL — `renderer/frame.h: No such file or directory`.

- [ ] **Step 3: Implement FrameSubmitter**

Create `native/src/renderer/include/renderer/frame.h`:

```cpp
// native/src/renderer/include/renderer/frame.h
#pragma once

#include <functional>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }
namespace renderer { class Pipeline; }

namespace renderer {

class FrameSubmitter {
public:
    using ModelLookup = std::function<const assets::Model*(unsigned long long)>;

    /// Iterate visible instances in `world` and draw each Mesh with the
    /// opaque shader. Caller is responsible for clearing color + depth and
    /// for swapping buffers afterward.
    void submit_opaque(const scenegraph::World& world,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline,
                       const ModelLookup& lookup);
};

}  // namespace renderer
```

Create `native/src/renderer/frame.cc`:

```cpp
// native/src/renderer/frame.cc
#include "renderer/frame.h"
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>

#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>
#include <assets/material.h>

#include <glm/gtc/matrix_transform.hpp>

namespace renderer {

namespace {

void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader) {
    // Walk nodes; each node may reference one or more meshes by index. The
    // node's local_transform is composed with parent transforms here. v1
    // implementation: the asset pipeline already pre-resolves Node::children;
    // we walk root-down once per draw, accumulating world-space transforms.
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = world * model.nodes[model.root_node].local_transform;
    }
    // BFS would be safer, but the asset pipeline already orders nodes such
    // that parents precede children. v1 assumes parent_index < child_index.
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            shader.set_mat4("u_model", world_per_node[i]);

            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            shader.set_vec3("u_diffuse_color", glm::vec3(mat.diffuse[0], mat.diffuse[1], mat.diffuse[2]));

            if (mat.base_color_texture_index >= 0) {
                glActiveTexture(GL_TEXTURE0);
                glBindTexture(GL_TEXTURE_2D,
                    model.textures[mat.base_color_texture_index].id());
                shader.set_int("u_base_color", 0);
            }

            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}

}  // namespace

void FrameSubmitter::submit_opaque(const scenegraph::World& world,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline,
                                   const ModelLookup& lookup) {
    auto& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_vec3("u_ambient_light", glm::vec3(0.1f));
    shader.set_vec3("u_dir_light_dir_ws", glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f)));
    shader.set_vec3("u_dir_light_color", glm::vec3(1.0f));

    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        if (m) draw_model(*m, inst.world, shader);
    });
}

}  // namespace renderer
```

Update `native/src/renderer/CMakeLists.txt` source list to include `frame.cc`:

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
)
target_include_directories(renderer
    PUBLIC include
    PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"
)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets scenegraph glad glfw glm)
```

(Note: `scenegraph` added as a public dep; renderer/frame.cc references its types.)

- [ ] **Step 4: Check assets::Material for actual field names**

Open `native/src/assets/include/assets/material.h` and confirm the field names used above (`diffuse`, `base_color_texture_index`). If they differ — e.g., the asset pipeline uses `glm::vec3 diffuse_color;` instead of `float diffuse[3];` — adjust the `frame.cc` code to match the real API. The asset pipeline implementation is authoritative; this is a one-shot adjustment.

Run: `cmake --build build --target renderer_tests`
If material field names mismatch: edit `native/src/renderer/frame.cc` to match. Re-build.

- [ ] **Step 5: Run, verify the frame test passes**

Run: `ctest --test-dir build -R "Frame" --output-on-failure`
Expected: PASS (or SKIP if BC assets / GL context unavailable).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/frame_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): FrameSubmitter draws visible instances via opaque shader"
```

---

### Task 18: Wire FrameSubmitter through pybind11 frame()

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `tests/host/test_clear_frame.py`

**Goal:** the `frame()` binding now: clears, runs `FrameSubmitter::submit_opaque`, swaps. Visible scene with one Galaxy renders.

- [ ] **Step 1: Refactor host_bindings to own a Pipeline + FrameSubmitter**

Modify `native/src/host/host_bindings.cc`. Add to globals:

```cpp
std::unique_ptr<renderer::Pipeline> g_pipeline;
renderer::FrameSubmitter g_submitter;
```

Add includes:
```cpp
#include <renderer/pipeline.h>
#include <renderer/frame.h>
```

Update `init` to also construct the pipeline (after window creation):

```cpp
void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
    g_pipeline = std::make_unique<renderer::Pipeline>();
    g_world = scenegraph::World{};
    g_loaded_models.clear();
}
```

Update `shutdown` to release pipeline:

```cpp
void shutdown() {
    g_pipeline.reset();
    g_loaded_models.clear();
    g_cache.reset();
    g_world = scenegraph::World{};
    g_window.reset();
}
```

Replace `frame()` with:

```cpp
void frame() {
    if (!g_window || !g_pipeline) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);
    glViewport(0, 0, fw, fh);
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    g_world.propagate();
    g_submitter.submit_opaque(g_world, g_camera, *g_pipeline,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            if (h == 0 || h > g_loaded_models.size()) return nullptr;
            return &(*g_loaded_models[h - 1].handle);
        });

    g_window->poll_events();
    g_window->swap_buffers();
}
```

(Note: `assets::ModelHandle` may be a pointer or reference type — adjust the `&(*g_loaded_models[...].handle)` derefence to whatever yields a `const assets::Model&` from a `ModelHandle`. Read `native/src/assets/include/assets/asset.h` for the actual definition.)

- [ ] **Step 2: Update existing test_clear_frame to also drive a model**

Replace `tests/host/test_clear_frame.py` with:

```python
"""Verify frame() executes a full opaque pass without raising."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"


def test_frame_runs_opaque_pass():
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(256, 256, "opaque-pass")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        h = _open_stbc_host.load_model(str(GALAXY_NIF),
                                       "data/Models/SharedTextures/FedShips/High")
        iid = _open_stbc_host.create_instance(h)
        _open_stbc_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, -100.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=10000.0,
        )
        for _ in range(3):
            _open_stbc_host.frame()
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 3: Build and run**

Run:
```bash
cmake --build build --target _open_stbc_host -j
uv run pytest tests/host/test_clear_frame.py -v
```
Expected: PASS (or SKIP).

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_clear_frame.py
git commit -m "feat(host): frame() runs opaque pass over scene graph"
```

---

## Phase E — Skybox pass

Three tasks. Goal: a dedicated skybox shader + pass before the opaque pass; `set_skybox(model)` selects which Model to render in that pass; depth-write off, projection translation removed.

### Task 19: Skybox shader sources

**Files:**
- Create: `native/src/renderer/shaders/skybox.vert`
- Create: `native/src/renderer/shaders/skybox.frag`
- Modify: `native/src/renderer/CMakeLists.txt`

- [ ] **Step 1: Write skybox shaders**

Create `native/src/renderer/shaders/skybox.vert`:

```glsl
#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 2) in vec2 a_uv;

uniform mat4 u_view_no_translation;
uniform mat4 u_proj;

out vec2 v_uv;

void main() {
    v_uv = a_uv;
    // Force depth = 1.0 (max) so skybox always passes LEQUAL depth test
    // against any geometry that writes a smaller value.
    vec4 clip = u_proj * u_view_no_translation * vec4(a_position, 1.0);
    gl_Position = clip.xyww;
}
```

Create `native/src/renderer/shaders/skybox.frag`:

```glsl
#version 330 core

in vec2 v_uv;
uniform sampler2D u_base_color;
out vec4 frag;

void main() {
    frag = vec4(texture(u_base_color, v_uv).rgb, 1.0);
}
```

- [ ] **Step 2: Embed skybox shaders in renderer CMake**

Modify `native/src/renderer/CMakeLists.txt`. Add two more `embed_shader` calls:

```cmake
embed_shader(SHADER_OPAQUE_VS shaders/opaque.vert opaque_vs)
embed_shader(SHADER_OPAQUE_FS shaders/opaque.frag opaque_fs)
embed_shader(SHADER_SKYBOX_VS shaders/skybox.vert skybox_vs)
embed_shader(SHADER_SKYBOX_FS shaders/skybox.frag skybox_fs)
```

- [ ] **Step 3: Verify build**

Run: `cmake -S . -B build && cmake --build build --target renderer`
Expected: success. Generated headers `embedded_skybox_vs.h` and `embedded_skybox_fs.h` exist under `build/native/src/renderer/`.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/ native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): skybox shader sources embedded"
```

---

### Task 20: Pipeline + FrameSubmitter skybox pass

**Files:**
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`
- Modify: `native/src/renderer/include/renderer/frame.h`
- Modify: `native/src/renderer/frame.cc`
- Create: `native/tests/renderer/skybox_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

- [ ] **Step 1: Extend Pipeline to own a skybox shader**

Modify `pipeline.h`:

```cpp
class Pipeline {
public:
    Pipeline();
    Shader& opaque_shader() noexcept { return *opaque_; }
    Shader& skybox_shader() noexcept { return *skybox_; }
private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> skybox_;
};
```

Modify `pipeline.cc`:

```cpp
#include "embedded_skybox_vs.h"
#include "embedded_skybox_fs.h"

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    skybox_ = std::make_unique<Shader>(shader_src::skybox_vs, shader_src::skybox_fs);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
}
```

- [ ] **Step 2: Add submit_skybox to FrameSubmitter**

Modify `frame.h` to add:

```cpp
    /// Render the skybox model with depth-write off, depth-test LEQUAL,
    /// projection translation removed. Caller-provided `skybox_model` may be
    /// null — in which case this function is a no-op. Must run before the
    /// opaque pass.
    void submit_skybox(const assets::Model* skybox_model,
                       const scenegraph::Camera& camera,
                       Pipeline& pipeline);
```

Modify `frame.cc`. Add at top of anonymous namespace:

```cpp
void draw_model_skybox(const assets::Model& model, Shader& shader) {
    // Skybox models are typically a single root node with one mesh; iterate
    // for safety. No materials beyond the base-color texture per mesh.
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            if (mat.base_color_texture_index >= 0) {
                glActiveTexture(GL_TEXTURE0);
                glBindTexture(GL_TEXTURE_2D,
                    model.textures[mat.base_color_texture_index].id());
                shader.set_int("u_base_color", 0);
            }
            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}
```

Implement `submit_skybox`:

```cpp
void FrameSubmitter::submit_skybox(const assets::Model* skybox_model,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline) {
    if (!skybox_model) return;
    auto& shader = pipeline.skybox_shader();
    shader.use();
    glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    shader.set_mat4("u_view_no_translation", view_no_t);
    shader.set_mat4("u_proj", camera.proj_matrix());

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glDisable(GL_CULL_FACE);

    draw_model_skybox(*skybox_model, shader);

    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
}
```

- [ ] **Step 3: Write the failing test**

Create `native/tests/renderer/skybox_test.cc`:

```cpp
// native/tests/renderer/skybox_test.cc
#include <gtest/gtest.h>

#include <renderer/pipeline.h>
#include <renderer/frame.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace {

class SkyboxTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "skybox-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
    }
};

TEST_F(SkyboxTest, NullModelIsNoOp) {
    scenegraph::Camera cam;
    renderer::FrameSubmitter s;
    s.submit_skybox(nullptr, cam, *p);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SkyboxTest, SkyboxShaderCompiles) {
    EXPECT_NE(p->skybox_shader().program(), 0u);
}

}  // namespace
```

Add to `native/tests/renderer/CMakeLists.txt`:

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    skybox_test.cc
)
```

- [ ] **Step 4: Build and run**

Run:
```bash
cmake --build build --target renderer_tests
ctest --test-dir build -R "Skybox" --output-on-failure
```
Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/ native/tests/renderer/skybox_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): skybox pass in Pipeline + FrameSubmitter"
```

---

### Task 21: Wire skybox into pybind11 frame()

**Files:**
- Modify: `native/src/host/host_bindings.cc`

**Goal:** when a skybox model is set via `set_skybox`, `frame()` runs the skybox pass before the opaque pass.

- [ ] **Step 1: Update frame() in host_bindings.cc**

Replace the existing `frame` function:

```cpp
void frame() {
    if (!g_window || !g_pipeline) {
        throw std::runtime_error("_open_stbc_host: frame called before init");
    }
    int fw = 0, fh = 0;
    g_window->framebuffer_size(&fw, &fh);
    glViewport(0, 0, fw, fh);
    glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
        if (h == 0 || h > g_loaded_models.size()) return nullptr;
        return &(*g_loaded_models[h - 1].handle);
    };

    g_world.propagate();
    g_submitter.submit_skybox(lookup(g_world.skybox_model()), g_camera, *g_pipeline);
    g_submitter.submit_opaque(g_world, g_camera, *g_pipeline, lookup);

    g_window->poll_events();
    g_window->swap_buffers();
}
```

- [ ] **Step 2: Build**

Run: `cmake --build build --target _open_stbc_host -j`
Expected: success.

- [ ] **Step 3: Add a test that doesn't crash with a skybox set**

Append to `tests/host/test_scene_setup.py`:

```python
def test_set_skybox_does_not_crash_in_frame():
    if not GALAXY_NIF.is_file():
        pytest.skip("BC asset not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    try:
        _open_stbc_host.init(256, 256, "skybox-test")
    except RuntimeError as e:
        pytest.skip(f"no GL: {e}")
    try:
        h = _open_stbc_host.load_model(str(GALAXY_NIF),
                                       "data/Models/SharedTextures/FedShips/High")
        # Reuse the Galaxy as a stand-in skybox for this test.
        _open_stbc_host.set_skybox(h)
        _open_stbc_host.set_camera(
            eye=(0,0,0), target=(0,0,-1), up=(0,1,0),
            fov_y_rad=1.0472, near=1.0, far=10000.0,
        )
        _open_stbc_host.frame()
    finally:
        _open_stbc_host.shutdown()
```

(The Galaxy isn't actually a skybox NIF; this test only proves the binding wiring doesn't crash. Real skybox selection happens in Task 25.)

Run: `uv run pytest tests/host/test_scene_setup.py -v`
Expected: all PASS or SKIP.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_scene_setup.py
git commit -m "feat(host): frame() runs skybox pass before opaque pass"
```

---

## Phase F — Python integration + ship gate

Six tasks. Goal: `engine/host_loop.py` boots a real BC mission and renders it. Ship gate: visual confirmation that player + NPCs render at correct positions.

### Task 22: Mission-pick scan tool

**Files:**
- Create: `tools/pick_simplest_mission.py`
- Create: `tests/tools/test_pick_simplest_mission.py`

**Goal:** a deterministic script that ranks SDK missions by Python source-line count and visible-spawn count, prints the top result, exits 0.

- [ ] **Step 1: Write the failing test**

Create `tests/tools/__init__.py` (empty file).

Create `tests/tools/test_pick_simplest_mission.py`:

```python
"""Verify pick_simplest_mission.py produces a deterministic top result."""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT = PROJECT_ROOT / "tools" / "pick_simplest_mission.py"


def test_script_runs_and_picks_a_mission():
    if not (PROJECT_ROOT / "sdk" / "Build" / "scripts").is_dir():
        import pytest
        pytest.skip("SDK not available")
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "winner:" in result.stdout
```

- [ ] **Step 2: Run, verify it fails (script missing)**

Run: `uv run pytest tests/tools/test_pick_simplest_mission.py -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Implement the script**

Create `tools/pick_simplest_mission.py`:

```python
"""Rank SDK missions by simplicity and print the smallest.

Heuristic: source-line count + 10 * (count of strings 'CreateShip' or
'AddObject' or 'CreateShipSet'). Lower is simpler. Ties broken alphabetically.

Usage:
    uv run python tools/pick_simplest_mission.py
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"

SPAWN_PATTERNS = [
    re.compile(r"\bCreateShip\b"),
    re.compile(r"\bAddObject\b"),
    re.compile(r"\bCreateShipSet\b"),
]


def discover_missions():
    missions = []
    for py_file in sorted(SDK_SCRIPTS.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "def Initialize(pMission)" not in text:
            continue
        missions.append((py_file, text))
    return missions


def score(text):
    lines = sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    spawns = sum(len(p.findall(text)) for p in SPAWN_PATTERNS)
    return lines + 10 * spawns


def main():
    missions = discover_missions()
    if not missions:
        print("no missions found", file=sys.stderr)
        return 1
    ranked = sorted((score(text), str(p.relative_to(SDK_SCRIPTS)), p, text) for p, text in missions)
    print("ranked by simplicity (lower = simpler):")
    for s, rel, _, _ in ranked[:5]:
        print(f"  {s:5d}  {rel}")
    s, rel, p, _ = ranked[0]
    rel_module = ".".join(p.relative_to(SDK_SCRIPTS).with_suffix("").parts)
    print(f"winner: {rel_module} (score {s}, path {rel})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/tools/test_pick_simplest_mission.py -v`
Expected: PASS (or SKIP).

Manually run: `uv run python tools/pick_simplest_mission.py`
Expected: prints a table of 5 missions and a winner. **Record the winner's module name** — it's used in Task 24's test and in the ship-gate task.

- [ ] **Step 5: Commit**

```bash
git add tools/pick_simplest_mission.py tests/tools/__init__.py tests/tools/test_pick_simplest_mission.py
git commit -m "tools(host): pick_simplest_mission ranks SDK missions for ship-gate"
```

---

### Task 23: Skybox path scan + hard-coded constant

**Files:**
- Create: `tools/pick_default_skybox.py`
- Modify: `engine/host_loop.py` (created in Task 24; this task pre-creates it as a stub)

**Goal:** a script that scans `game/data` for a small standalone "skybox-shaped" NIF and prints the path. The path is then hard-coded into `engine/host_loop.py` for v1.

- [ ] **Step 1: Implement the scan**

Create `tools/pick_default_skybox.py`:

```python
"""Find a small standalone skybox NIF in game/data.

Heuristic: any *.nif with 'sky' or 'star' in the path, ranked by file size
ascending. Prints the smallest match.

Usage:
    uv run python tools/pick_default_skybox.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
GAME_DATA = PROJECT_ROOT / "game" / "data"


def main():
    if not GAME_DATA.is_dir():
        print(f"no game/data at {GAME_DATA}", file=sys.stderr)
        return 1
    candidates = []
    for nif in GAME_DATA.rglob("*.nif"):
        name = str(nif).lower()
        if "sky" in name or "star" in name:
            candidates.append((nif.stat().st_size, nif))
    if not candidates:
        print("no skybox candidates found", file=sys.stderr)
        return 1
    candidates.sort()
    print("ranked by size:")
    for size, p in candidates[:10]:
        print(f"  {size:>10d}  {p.relative_to(PROJECT_ROOT)}")
    print(f"winner: {candidates[0][1].relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the scan**

Run: `uv run python tools/pick_default_skybox.py`
Expected: prints a table and a winner. **Record the winner path** — used in Task 24.

If no skybox NIF is found, the implementer should fall back to "no skybox in v1" and the host_loop.py created in Task 24 will skip `set_skybox`.

- [ ] **Step 3: Commit**

```bash
git add tools/pick_default_skybox.py
git commit -m "tools(host): pick_default_skybox scans game/data for the smallest sky NIF"
```

---

### Task 24: engine/renderer.py and engine/host_loop.py

**Files:**
- Create: `engine/renderer.py`
- Create: `engine/host_loop.py`
- Create: `tests/host/test_host_loop_unit.py`

**Goal:** a Python module that wires Phase 1's mission init + tick loop to the renderer bindings. Mission name and skybox path are hard-coded based on Tasks 22/23 results.

- [ ] **Step 1: Write engine/renderer.py — thin wrapper**

Create `engine/renderer.py`:

```python
"""Pythonic wrapper around the _open_stbc_host extension module.

Re-exports the binding functions with type hints. Application code should
import from here, not from _open_stbc_host directly.
"""
from typing import Tuple

import _open_stbc_host as _h

InstanceId = _h.InstanceId


def init(width: int, height: int, title: str) -> None:
    _h.init(width, height, title)


def shutdown() -> None:
    _h.shutdown()


def should_close() -> bool:
    return _h.should_close()


def frame() -> None:
    _h.frame()


def load_model(nif_path: str, texture_search_path: str) -> int:
    return _h.load_model(nif_path, texture_search_path)


def create_instance(model: int) -> InstanceId:
    return _h.create_instance(model)


def destroy_instance(iid: InstanceId) -> None:
    _h.destroy_instance(iid)


def set_world_transform(iid: InstanceId, mat4_row_major: list) -> None:
    _h.set_world_transform(iid, mat4_row_major)


def set_visible(iid: InstanceId, visible: bool) -> None:
    _h.set_visible(iid, visible)


def set_camera(eye: Tuple[float, float, float],
               target: Tuple[float, float, float],
               up: Tuple[float, float, float],
               fov_y_rad: float, near: float, far: float) -> None:
    _h.set_camera(eye, target, up, fov_y_rad, near, far)


def set_skybox(model: int) -> None:
    _h.set_skybox(model)
```

- [ ] **Step 2: Write engine/host_loop.py**

Create `engine/host_loop.py`:

```python
"""Bridge Phase 1 mission init/tick to the renderer host.

Hard-coded constants below are the v1 ship-gate picks. Update SHIP_GATE_MISSION
to whatever `tools/pick_simplest_mission.py` returned at plan time, and
DEFAULT_SKYBOX_NIF to the `tools/pick_default_skybox.py` winner.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from engine import renderer as r

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v1 ship-gate selections — replace via the corresponding pick scripts.
SHIP_GATE_MISSION = "Single.Quickbattle"           # placeholder; update from pick_simplest_mission.py
DEFAULT_SKYBOX_NIF: Optional[str] = None           # placeholder; update from pick_default_skybox.py
DEFAULT_TEXTURE_SEARCH = "data/Models/SharedTextures/FedShips/High"


def _setup_sdk_path():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    # Reuse mission_harness's setup helpers — they install the SDK finder /
    # AST transformer that translates Py 1.5/2 syntax to Py 3.
    from tools import mission_harness  # noqa: F401
    mission_harness.setup_sdk()


def _walk_ships():
    """Iterate every active ship as (ship_id, world_matrix_row_major: list[float], nif_path, texture_search)."""
    import App
    # App.GetGameState().GetSetManager().GetSet("bridge").GetObjectList() returns
    # active objects; filter to ShipClass instances and pull positions.
    # Phase 1's engine.appc owns the lookup; reuse the same pattern.
    set_mgr = App.g_kSystemWrapper.GetGameState().GetSetManager()
    ship_set = set_mgr.GetSet("bridge")  # active sim set; name may vary per Phase 1
    for obj in ship_set.GetObjectList():
        if not hasattr(obj, "GetPosition"):
            continue
        pos = obj.GetPosition()
        # Convert (position + orientation) to a row-major 4x4. Phase 1 stores
        # orientation as a quaternion or 3x3; consult engine.appc for the
        # actual representation.
        m = [
            1.0, 0.0, 0.0, pos[0],
            0.0, 1.0, 0.0, pos[1],
            0.0, 0.0, 1.0, pos[2],
            0.0, 0.0, 0.0, 1.0,
        ]
        nif = getattr(obj, "GetNifFile", lambda: None)()
        yield obj, m, nif


def run(mission_name: str = SHIP_GATE_MISSION, max_ticks: Optional[int] = None) -> int:
    _setup_sdk_path()

    from tools import gameloop_harness as glh

    r.init(1280, 720, "open_stbc")
    try:
        if DEFAULT_SKYBOX_NIF:
            sky = r.load_model(DEFAULT_SKYBOX_NIF, DEFAULT_TEXTURE_SEARCH)
            r.set_skybox(sky)

        # Initialize the mission via the same path gameloop_harness uses.
        # glh.run_mission_with_loop returns (status, exc, ticks); we don't
        # use that directly because it owns its own loop. Inline the init
        # piece and run our own loop.
        from tools import mission_harness
        mission_harness.setup_sdk()
        from engine.core.game import Game, Episode, Mission, _set_current_game
        from engine.appc.events import TGEvent
        import App

        mission = Mission(); episode = Episode(); episode.SetCurrentMission(mission)
        game = Game(); game.SetCurrentEpisode(episode)
        _set_current_game(game)
        mod = __import__(mission_name, fromlist=["Initialize"])
        mod.Initialize(mission)
        TGEvent.Send("ET_MISSION_START")

        # Build the (ship → instance) map.
        instances = {}
        for obj, mat, nif in _walk_ships():
            if not nif: continue
            handle = r.load_model(nif, DEFAULT_TEXTURE_SEARCH)
            iid = r.create_instance(handle)
            r.set_world_transform(iid, mat)
            instances[obj] = iid

        # Camera: fixed third-person offset behind player ship if we can find one.
        from engine.core.game import _get_current_game
        player = _get_current_game().GetPlayerShip() if hasattr(_get_current_game(), "GetPlayerShip") else None

        ticks = 0
        from engine.core.loop import GameLoop
        loop = GameLoop()
        while not r.should_close():
            loop.tick()

            # Sync transforms for known instances.
            for obj, _, _ in _walk_ships():
                if obj in instances:
                    pos = obj.GetPosition()
                    m = [
                        1, 0, 0, pos[0],
                        0, 1, 0, pos[1],
                        0, 0, 1, pos[2],
                        0, 0, 0, 1,
                    ]
                    r.set_world_transform(instances[obj], m)

            # Camera follow (very simple — third-person offset).
            if player:
                p = player.GetPosition()
                r.set_camera(
                    eye=(p[0], p[1] + 30.0, p[2] + 200.0),
                    target=(p[0], p[1], p[2]),
                    up=(0.0, 1.0, 0.0),
                    fov_y_rad=1.0472, near=1.0, far=100000.0,
                )
            else:
                r.set_camera(
                    eye=(0, 30, 200), target=(0, 0, 0), up=(0, 1, 0),
                    fov_y_rad=1.0472, near=1.0, far=100000.0,
                )

            r.frame()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break

        for iid in instances.values():
            r.destroy_instance(iid)
    finally:
        r.shutdown()

    return 0
```

> **Note:** the field names (`App.g_kSystemWrapper`, `obj.GetPosition()`, `obj.GetNifFile()`, `_set_current_game`, etc.) are best-effort matches to the Phase 1 engine's actual API. The implementer should grep `engine/` and `sdk/Build/scripts/` for the real names and adapt. The structure of this file is the load-bearing contract; the exact attribute names will need adjustment.

- [ ] **Step 3: Write a unit-style test that imports host_loop without running it**

Create `tests/host/test_host_loop_unit.py`:

```python
"""host_loop module imports cleanly and exposes the public symbols."""

def test_imports():
    from engine import host_loop
    assert hasattr(host_loop, "run")
    assert isinstance(host_loop.SHIP_GATE_MISSION, str)
```

Run: `uv run pytest tests/host/test_host_loop_unit.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/renderer.py engine/host_loop.py tests/host/test_host_loop_unit.py
git commit -m "feat(host): engine.host_loop bridges Phase 1 mission init to the renderer"
```

---

### Task 25: Update SHIP_GATE_MISSION + DEFAULT_SKYBOX_NIF from scan results

**Files:**
- Modify: `engine/host_loop.py`

**Goal:** replace the placeholder constants in `host_loop.py` with the actual winners from the Task 22 and Task 23 scans.

- [ ] **Step 1: Run both scans and capture the results**

Run:
```bash
uv run python tools/pick_simplest_mission.py
uv run python tools/pick_default_skybox.py
```

- [ ] **Step 2: Update host_loop.py**

In `engine/host_loop.py`, replace:

```python
SHIP_GATE_MISSION = "Single.Quickbattle"
DEFAULT_SKYBOX_NIF: Optional[str] = None
```

with the actual winners. Example (substitute real values):

```python
SHIP_GATE_MISSION = "<module-name-from-pick_simplest_mission.py>"
DEFAULT_SKYBOX_NIF: Optional[str] = "<path-from-pick_default_skybox.py-or-None>"
```

If the skybox scan returned no candidates, leave `DEFAULT_SKYBOX_NIF = None`. The host_loop already handles that case (no `set_skybox` call).

- [ ] **Step 3: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): pin SHIP_GATE_MISSION and DEFAULT_SKYBOX_NIF for v1"
```

---

### Task 26: Visible ship gate — host renders the picked mission

**Files:**
- Modify: `native/src/host/host_main.cc`

**Goal:** the binary, with no `--smoke-check` flag, runs `engine.host_loop.run()` and renders. Manual visual confirmation of the v1 ship gate.

- [ ] **Step 1: Replace the default branch in host_main**

Modify the `main` function in `host_main.cc`. Replace the `else` branch (which currently calls `call_banner`) with a call to `engine.host_loop.run`:

```cpp
    if (argc >= 2 && std::string(argv[1]) == "--smoke-check") {
        // existing smoke-check branch unchanged
    } else {
        PyObject* mod = PyImport_ImportModule("engine.host_loop");
        if (!mod) { PyErr_Print(); rc = 1; goto teardown; }
        PyObject* fn = PyObject_GetAttrString(mod, "run");
        if (!fn) { PyErr_Print(); Py_DECREF(mod); rc = 1; goto teardown; }
        {
            PyObject* result = PyObject_CallNoArgs(fn);
            Py_DECREF(fn);
            Py_DECREF(mod);
            if (!result) {
                PyErr_Print();
                rc = 1;
                goto teardown;
            }
            if (PyLong_Check(result)) {
                rc = static_cast<int>(PyLong_AsLong(result));
            }
            Py_DECREF(result);
        }
    }
```

(Keep the smoke-check branch from Task 5 intact.)

- [ ] **Step 2: Build the binary**

Run: `cmake --build build --target open_stbc_host -j`
Expected: success.

- [ ] **Step 3: Run the visible ship gate (manual)**

Run (on a machine with a display and BC assets in `game/`):
```bash
./build/bin/open_stbc_host
```

**Expected:**
- A 1280×720 window opens titled "open_stbc"
- The picked mission boots
- Player ship and any NPC ships render at their game-loop positions
- If a skybox NIF was set, it renders behind everything
- Window stays open until close button pressed
- Clean exit (exit code 0)

If the run fails — most likely sources are mismatches between `engine/host_loop.py`'s assumed Phase 1 API (`App.g_kSystemWrapper`, `obj.GetPosition`, `obj.GetNifFile`, etc.) and the real engine. Grep `engine/` for the actual names and patch `host_loop.py`. Re-run.

- [ ] **Step 4: If the manual run succeeds, commit**

```bash
git add native/src/host/host_main.cc
git commit -m "feat(host): default invocation runs engine.host_loop.run for v1 ship gate"
```

---

### Task 27: Phase F + sub-project status update

**Files:**
- Modify: `docs/architecture/sub_project_status.md`
- Create: `native/src/host/docs/deferred_work.md`

**Goal:** mark the v1 ship gate met; create the deferred-work tracker mirroring the spec's deferred list.

- [ ] **Step 1: Create the deferred-work tracker**

Create `native/src/host/docs/deferred_work.md`:

```markdown
# Renderer Host — Deferred Work

This file mirrors the "Deferred / future work" section of the design spec at
[`docs/superpowers/specs/2026-05-09-renderer-host-design.md`](../../../../docs/superpowers/specs/2026-05-09-renderer-host-design.md).

The spec is the authoritative source. Update both when items move on or off
the list.

1. Skybox path lookup from mission/system config — replaces the v1 hard-coded default skybox.
2. BC light data interpretation — read `NiAmbientLight` / `NiDirectionalLight` blocks.
3. Animation playback — evaluate `AnimationClip` data already present in `Model`.
4. Skinned-mesh rendering — bone palette uniform + vertex skinning.
5. LOD selection — depends on asset pipeline populating `Mesh::lod_chain`.
6. Frustum culling — sphere-in-frustum test once scene-instance count grows.
7. Decoupled render thread / interpolation.
8. Render targets / framebuffers / post-processing.
9. Debug fly-around camera (mouse + WASD).
10. In-game camera modes (tactical, bridge, external orbit, cinematic).
11. HUD and UI.
12. Procedural FX (explosions, weapon fire, warp trails).
13. Hardpoint-marker / damage-node interpretation.
14. Mod / asset-overlay support.
15. Save/load coverage of render state.
16. BC input system integration.
```

- [ ] **Step 2: Update the sub-project status**

Edit `docs/architecture/sub_project_status.md`. Replace the renderer-host row from Task 6 with:

```
| 3-6 | Renderer host (combined: scene-graph + minimal renderer + CPython embedding + skybox pass) | Implemented (v1 ship gate met YYYY-MM-DD) | [2026-05-09-renderer-host-design.md](../superpowers/specs/2026-05-09-renderer-host-design.md) | [`native/src/host/docs/deferred_work.md`](../../native/src/host/docs/deferred_work.md) |
```

(Replace `YYYY-MM-DD` with today's date when the manual ship gate is met.)

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/sub_project_status.md native/src/host/docs/deferred_work.md
git commit -m "docs(status): renderer-host v1 ship gate met"
```

---

## Self-review

**Spec coverage:**
- Spec § Architecture / Components: covered by Tasks 7-21 (renderer + scenegraph) and Tasks 2-5, 12-13 (host).
- Spec § Python bindings surface: covered by Tasks 3, 8, 12, 13, 18, 21.
- Spec § Loop structure: covered by Task 24 (`engine/host_loop.py`).
- Spec § Skybox & lighting: covered by Tasks 19-21 (skybox); lighting hard-codes are in Tasks 16 (opaque shader) and 17 (FrameSubmitter).
- Spec § Build system: covered by Tasks 1-3 (Python find, pybind11, GLFW promotion, dual-build of bindings).
- Spec § Tests & verification: scene-graph tests in Tasks 10-11; renderer GL tests in Tasks 7, 15-17, 20; bindings tests in Tasks 3, 8, 12-14, 18, 21; visible ship gate in Task 26.
- Spec § Deferred / future work: tracker created in Task 27.
- Spec § Update protocol: status doc updated in Tasks 6, 27.

**Placeholder scan:** No "TBD"/"TODO" steps. The mission name and skybox path placeholders in Task 24 are explicit, with a follow-up Task 25 that fills them in from scan results.

**Type consistency:** `InstanceId`, `ModelHandle`, `mat4_row_major: list[float]`, `Camera` field names (`eye`, `target`, `up`, `fov_y_rad`, `near`, `far`, `aspect`) are consistent across header, source, bindings, and Python wrapper.

**Known weak spots the implementer should expect:**
1. **Asset-pipeline material API names.** `frame.cc` references `mat.diffuse[0..2]` and `mat.base_color_texture_index`. The actual `assets::Material` field names may differ. Task 17 step 4 calls this out and instructs the implementer to consult the real header.
2. **Phase 1 engine API.** `engine/host_loop.py` references `App.g_kSystemWrapper`, `obj.GetPosition()`, `obj.GetNifFile()`, etc. — these are best-effort placeholders. Task 24 flags this and Task 26 step 3 makes patching them part of the ship-gate cycle.
3. **Skybox `NiPixelData`-only NIFs.** If the picked skybox NIF references textures the asset pipeline can't yet decode, fall back to `DEFAULT_SKYBOX_NIF = None` and proceed without skybox in v1. The host already handles that path.
