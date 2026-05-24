# native/src/host/CMakeLists.txt — renderer host binary + pybind11 module.

# Shared source — both targets compile this file. The PYBIND11_MODULE macro
# generates PyInit__dauntless_host, used by both consumers.
set(HOST_BINDINGS_SOURCES
    host_bindings.cc
)

# Python extension module (.so / .pyd / .dylib) for pytest.
pybind11_add_module(_dauntless_host MODULE ${HOST_BINDINGS_SOURCES})
target_compile_features(_dauntless_host PRIVATE cxx_std_20)
target_link_libraries(_dauntless_host PRIVATE renderer scenegraph assets dauntless_audio)
set_target_properties(_dauntless_host PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python"
)

# Host executable. Statically links the same bindings translation unit, then
# host_main registers the init function via PyImport_AppendInittab before
# Py_InitializeEx. Output lands directly at ${CMAKE_BINARY_DIR}/dauntless so
# the run command is `./build/dauntless` from the project root.
add_executable(dauntless
    host_main.cc
    ${HOST_BINDINGS_SOURCES}
)

target_link_libraries(dauntless
    PRIVATE
        Python3::Python
        pybind11::embed
        renderer
        scenegraph
        assets
        dauntless_audio
)

target_compile_features(dauntless PRIVATE cxx_std_20)
target_include_directories(dauntless PRIVATE .)

set_target_properties(dauntless PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

# Block parsers in libnif.a self-register via static initializers. Without
# force-load, the linker drops object files that aren't otherwise referenced
# and the registrations never run — the NIF parser then walks files and fails
# with "no NiNode root in NIF file" because no block types are recognized.
# Mirrors the pattern in native/tests/{,assets/}CMakeLists.txt for the test
# targets.
if(APPLE)
    target_link_options(_dauntless_host PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
    target_link_options(dauntless PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(_dauntless_host PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
    target_link_options(dauntless PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
