// native/src/host/host_main.cc
//
// open_stbc — embedded-CPython renderer host binary.

#include <Python.h>

#include "host_bindings.h"

#ifdef DAUNTLESS_ENABLE_CEF
#include "ui_cef/cef_lifecycle.h"
#endif

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>

namespace {

// Locate the project root from the running binary's path. The binary lives at
// <root>/build/dauntless, so root is two parents up from the binary's
// canonical path. This is a build-tree assumption — the binary is not yet
// meant to be installed system-wide.
std::filesystem::path discover_project_root(const char* argv0) {
    std::filesystem::path bin_path = std::filesystem::canonical(argv0);
    return bin_path.parent_path().parent_path();
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

int run_host_loop() {
    PyObject* mod = PyImport_ImportModule("engine.host_loop");
    if (!mod) { PyErr_Print(); return 1; }
    PyObject* fn = PyObject_GetAttrString(mod, "run");
    if (!fn) { PyErr_Print(); Py_DECREF(mod); return 1; }
    PyObject* result = PyObject_CallNoArgs(fn);
    Py_DECREF(fn);
    Py_DECREF(mod);
    if (!result) { PyErr_Print(); return 1; }
    int rc = 0;
    if (PyLong_Check(result)) {
        rc = static_cast<int>(PyLong_AsLong(result));
    }
    Py_DECREF(result);
    return rc;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 1) return 1;

#ifdef DAUNTLESS_ENABLE_CEF
    // CEF spawns helper subprocesses by re-running this binary. The
    // subprocess role is encoded in argv; CefExecuteProcess detects it
    // and runs the appropriate event loop, returning the exit code we
    // must propagate. A return value of -1 means "main browser process,
    // keep going with normal startup."
    {
        const int subprocess_rc = dauntless::ui_cef::dispatch_subprocess(argc, argv);
        if (subprocess_rc >= 0) return subprocess_rc;
    }
#endif

    auto project_root = discover_project_root(argv[0]);
    configure_python_path(project_root);

    if (PyImport_AppendInittab("_dauntless_host", PyInit__dauntless_host) != 0) {
        std::fprintf(stderr, "open_stbc: PyImport_AppendInittab failed\n");
        return 1;
    }

    Py_InitializeEx(/*initsigs=*/1);

    int rc = 0;
    std::string mode = (argc >= 2) ? std::string(argv[1]) : "";
    if (mode == "--smoke-check") {
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
    } else if (mode == "--banner") {
        rc = call_banner();
    } else {
        // Default: run the visible ship gate via engine.host_loop.run().
        rc = run_host_loop();
    }

teardown:
    if (Py_FinalizeEx() < 0) return 2;
    return rc;
}
