// native/src/host/host_bindings.h
#pragma once

#include <Python.h>

// Module init function exported by host_bindings.cc. The host executable
// registers it via PyImport_AppendInittab before Py_InitializeEx; the Python
// extension module .so exposes it as the standard PyInit__dauntless_host
// entry point.
extern "C" PyObject* PyInit__dauntless_host();
