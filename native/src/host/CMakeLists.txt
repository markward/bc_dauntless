# native/src/host/CMakeLists.txt — renderer host binary + pybind11 module.

# Shared source — both targets compile this file. The PYBIND11_MODULE macro
# generates PyInit__open_stbc_host, used by both consumers.
set(HOST_BINDINGS_SOURCES
    host_bindings.cc
)

# Python extension module (.so / .pyd / .dylib) for pytest.
pybind11_add_module(_open_stbc_host MODULE ${HOST_BINDINGS_SOURCES})
target_compile_features(_open_stbc_host PRIVATE cxx_std_20)
target_link_libraries(_open_stbc_host PRIVATE renderer)
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
        renderer
)

target_compile_features(open_stbc_host PRIVATE cxx_std_20)
target_include_directories(open_stbc_host PRIVATE .)

set_target_properties(open_stbc_host PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
