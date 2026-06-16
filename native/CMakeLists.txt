cmake_minimum_required(VERSION 3.20)
# Native subtree of dauntless: Phase 2 C++ engine.

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
add_subdirectory(third_party/dr_libs)
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


# OpenAL Soft for audio output. Library-only build; no examples or utils.
# CMAKE_POLICY_VERSION_MINIMUM=3.5 is required because CMake 4.x removed
# compatibility with cmake_minimum_required < 3.5 and openal-soft 1.23.1
# still declares that floor.
set(LIBTYPE STATIC CACHE STRING "" FORCE)
set(ALSOFT_UTILS OFF CACHE BOOL "" FORCE)
set(ALSOFT_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ALSOFT_TESTS OFF CACHE BOOL "" FORCE)
set(ALSOFT_INSTALL OFF CACHE BOOL "" FORCE)
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "" FORCE)
FetchContent_Declare(
    openal_soft
    GIT_REPOSITORY https://github.com/kcat/openal-soft.git
    GIT_TAG        1.23.1
)
FetchContent_MakeAvailable(openal_soft)

option(DAUNTLESS_BUILD_TESTS "Build native tests for dauntless" ON)

option(DAUNTLESS_ENABLE_CEF "Build with CEF-backed UI overlay" ON)

if(DAUNTLESS_ENABLE_CEF)
    include(FetchContent)

    # Per-platform CEF tarball selection. Spotify's CDN hosts the Minimal
    # distribution. Version pinned: bumping is a deliberate, separate task.
    # Only macosarm64's SHA256 is filled in — Windows/Linux SHA256s must be
    # added when those platforms are first validated (see spec §11).
    set(CEF_VERSION "144.0.25+g27ce504+chromium-144.0.7559.250")
    if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
        set(CEF_PLATFORM "macosarm64")
        set(CEF_SHA256 "541a2e38234ef0c99e40e7f6fc8e895be6dde8293b84c7d0490897eb54062ece")
    elseif(APPLE)
        set(CEF_PLATFORM "macosx64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Intel macOS
    elseif(WIN32)
        set(CEF_PLATFORM "windows64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Windows
    elseif(UNIX)
        set(CEF_PLATFORM "linux64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Linux
    else()
        message(FATAL_ERROR "DAUNTLESS_ENABLE_CEF: unsupported platform")
    endif()

    # URL-encode the '+' characters in the version string (Spotify CDN serves
    # the file by its literal name on disk, which uses '+').
    string(REPLACE "+" "%2B" CEF_VERSION_URL "${CEF_VERSION}")
    set(CEF_URL "https://cef-builds.spotifycdn.com/cef_binary_${CEF_VERSION_URL}_${CEF_PLATFORM}_minimal.tar.bz2")

    if(CEF_SHA256)
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            URL_HASH SHA256=${CEF_SHA256}
            SOURCE_SUBDIR cmake  # skip the CEF SDK's sample-driver CMakeLists
        )
    else()
        message(WARNING "DAUNTLESS_ENABLE_CEF: no SHA256 pinned for ${CEF_PLATFORM} — integrity check skipped")
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            SOURCE_SUBDIR cmake
        )
    endif()
    FetchContent_MakeAvailable(cef)

    set(CEF_ROOT "${cef_SOURCE_DIR}" CACHE INTERNAL "")
    list(APPEND CMAKE_MODULE_PATH "${CEF_ROOT}/cmake")
    find_package(CEF REQUIRED)

    # CEF ships libcef_dll/ as source; consumers must compile it into their
    # project. Force STATIC: CEF's add_library() honors BUILD_SHARED_LIBS,
    # which openal-soft turns ON globally. Combined with CEF's
    # -fvisibility=hidden flags that would hide every wrapper symbol
    # (CefExecuteProcess, CefInitialize, ...) and downstream linking fails
    # with "undefined symbol". Static sidesteps visibility entirely.
    set(_dauntless_saved_BUILD_SHARED_LIBS ${BUILD_SHARED_LIBS})
    set(BUILD_SHARED_LIBS OFF)
    add_subdirectory("${CEF_ROOT}/libcef_dll" libcef_dll_wrapper)
    set(BUILD_SHARED_LIBS ${_dauntless_saved_BUILD_SHARED_LIBS})

    # Project-wide -Wpedantic collides with CEF's -Werror inside
    # libcef_dll_wrapper (CEF's logging headers use GNU token-pasting via
    # `, ##__VA_ARGS__`). Suppress only that warning on the wrapper.
    if(TARGET libcef_dll_wrapper)
        target_compile_options(libcef_dll_wrapper PRIVATE
            -Wno-gnu-zero-variadic-macro-arguments)
    endif()

    message(STATUS "CEF SDK at: ${CEF_ROOT}")
    message(STATUS "CEF version: ${CEF_VERSION}")
endif()

# Public libraries.
add_subdirectory(src/nif)
add_subdirectory(src/assets)
add_subdirectory(src/audio)

# enable_testing() must precede any add_subdirectory whose CMakeLists registers
# add_test (scan_nifs registers its corpus-coverage test conditionally).
enable_testing()

# Diagnostic tools that consume the public library.
add_subdirectory(tools/scan_nifs)
add_subdirectory(tools/probe_shape_transforms)
add_subdirectory(tools/probe_animation_keys)
add_subdirectory(tools/probe_block_inventory)
add_subdirectory(tools/probe_bound_radius)
add_subdirectory(tools/probe_texture_stages)
add_subdirectory(tools/probe_officer_pose)
add_subdirectory(tools/dump_bridge_assets)
add_subdirectory(tools/dump_nif_tree)
add_subdirectory(tools/inspect_flip)
add_subdirectory(tools/inspect_tex_props)

# GLFW is a runtime dep for the renderer host; tests reuse the same build.
set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/glfw)

# Renderer library (window + GL context wrapper).
add_subdirectory(src/renderer)


# Scene-graph data + math (pure C++, no GL).
add_subdirectory(src/scenegraph)

# Voxel hull-damage foundation.
add_subdirectory(src/voxel)

# Renderer host subtree.
add_subdirectory(src/host)

if(DAUNTLESS_ENABLE_CEF)
    add_subdirectory(src/ui_cef)
endif()

if(DAUNTLESS_BUILD_TESTS)
  add_subdirectory(tests)
endif()
