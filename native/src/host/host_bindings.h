// native/src/host/host_bindings.h
#pragma once

#include <Python.h>

// Module init function exported by host_bindings.cc. The host executable
// registers it via PyImport_AppendInittab before Py_InitializeEx; the Python
// extension module .so exposes it as the standard PyInit__dauntless_host
// entry point.
// PyMODINIT_FUNC, not a bare extern "C" declaration: PYBIND11_MODULE defines
// this symbol with the platform export attribute, and on Windows that is
// __declspec(dllexport). A plain declaration differs in linkage and MSVC
// rejects the definition as a redefinition (C2375). PyMODINIT_FUNC carries
// extern "C" plus the correct attribute on every platform.
PyMODINIT_FUNC PyInit__dauntless_host();
