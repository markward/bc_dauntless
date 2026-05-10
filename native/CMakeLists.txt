cmake_minimum_required(VERSION 3.20)
# Native subtree of open_stbc: Phase 2 C++ engine.

# C++20 across the whole subtree.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Emit compile_commands.json so clangd / IDE pickers find include paths.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Warnings — treat as project-wide default.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  add_compile_options(-Wall -Wextra -Wpedantic -Wno-unused-parameter)
endif()

# Third-party vendored libraries.
add_subdirectory(third_party/stb)
add_subdirectory(third_party/glad)
add_subdirectory(third_party/glm)

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

# RmlUi — HTML/CSS UI framework. Samples/tests off so RmlUi only builds RmlCore;
# we compile the GLFW+GL3 backends ourselves in native/src/ui so they pick up
# our existing glad + glfw targets rather than any system copies.
FetchContent_Declare(
    RmlUi
    GIT_REPOSITORY https://github.com/mikke89/RmlUi.git
    GIT_TAG        6.0
)
set(RMLUI_SAMPLES       OFF   CACHE BOOL   "" FORCE)
set(RMLUI_TESTS         OFF   CACHE BOOL   "" FORCE)
set(RMLUI_LOTTIE_PLUGIN OFF   CACHE BOOL   "" FORCE)
FetchContent_MakeAvailable(RmlUi)

# Public libraries.
add_subdirectory(src/nif)
add_subdirectory(src/assets)

# enable_testing() must precede any add_subdirectory whose CMakeLists registers
# add_test (scan_nifs registers its corpus-coverage test conditionally).
enable_testing()

# Diagnostic tools that consume the public library.
add_subdirectory(tools/scan_nifs)

# GLFW is a runtime dep for the renderer host; tests reuse the same build.
set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/glfw)

# Renderer library (window + GL context wrapper).
add_subdirectory(src/renderer)

# UI library (RmlUi integration + HUD).
add_subdirectory(src/ui)

# Scene-graph data + math (pure C++, no GL).
add_subdirectory(src/scenegraph)

# Renderer host subtree.
add_subdirectory(src/host)

option(OPEN_STBC_BUILD_TESTS "Build native tests for open_stbc" ON)
if(OPEN_STBC_BUILD_TESTS)
  add_subdirectory(tests)
endif()
