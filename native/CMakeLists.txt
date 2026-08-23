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
# Development.Embed → the executable embeds CPython (links the full libpython).
# Development.Module → headers-only target (Python3::Module) for static libs that
# get pulled into the pybind11 extension module; it must NOT link libpython, or a
# second libpython copy crashes a statically-linked interpreter (uv standalone).
find_package(Python3 3.11 REQUIRED COMPONENTS Development.Embed Development.Module)

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
    #
    # CEF_URL_HASH carries the algorithm as well as the digest, because the
    # authoritative source for these is cef-builds.spotifycdn.com/index.json,
    # which publishes SHA1. windows64 was downloaded, checked against that
    # SHA1, and its SHA256 computed from the verified bytes; linux64 is pinned
    # to the index's SHA1 directly (nobody has built it yet, and an unpinned
    # download is worse than a SHA1-pinned one).
    set(CEF_VERSION "144.0.25+g27ce504+chromium-144.0.7559.250")
    if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
        set(CEF_PLATFORM "macosarm64")
        set(CEF_URL_HASH "SHA256=541a2e38234ef0c99e40e7f6fc8e895be6dde8293b84c7d0490897eb54062ece")
    elseif(APPLE)
        set(CEF_PLATFORM "macosx64")
        set(CEF_URL_HASH "")  # TODO(plan-followup): fill when validating on Intel macOS
    elseif(WIN32)
        set(CEF_PLATFORM "windows64")
        set(CEF_URL_HASH "SHA256=c920a6bee3e9e14cabe8f2e0b541581cc1dedb3a82b0d3a69382903231c6a69d")
    elseif(UNIX)
        set(CEF_PLATFORM "linux64")
        set(CEF_URL_HASH "SHA1=9577dccdac9612c300029b3968ae87c537442b2f")
    else()
        message(FATAL_ERROR "DAUNTLESS_ENABLE_CEF: unsupported platform")
    endif()

    # URL-encode the '+' characters in the version string (Spotify CDN serves
    # the file by its literal name on disk, which uses '+').
    string(REPLACE "+" "%2B" CEF_VERSION_URL "${CEF_VERSION}")
    set(CEF_URL "https://cef-builds.spotifycdn.com/cef_binary_${CEF_VERSION_URL}_${CEF_PLATFORM}_minimal.tar.bz2")

    if(CEF_URL_HASH)
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            URL_HASH ${CEF_URL_HASH}
            SOURCE_SUBDIR cmake  # skip the CEF SDK's sample-driver CMakeLists
        )
    else()
        message(WARNING "DAUNTLESS_ENABLE_CEF: no hash pinned for ${CEF_PLATFORM} — integrity check skipped")
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            SOURCE_SUBDIR cmake
        )
    endif()
    FetchContent_MakeAvailable(cef)

    set(CEF_ROOT "${cef_SOURCE_DIR}" CACHE INTERNAL "")
    list(APPEND CMAKE_MODULE_PATH "${CEF_ROOT}/cmake")
    # CEF defaults libcef_dll_wrapper to the static CRT (/MT) on Windows. This
    # project must use the dynamic CRT (/MD) -- _dauntless_host is a Python
    # extension and has to share the interpreter's CRT -- and mixing the two in
    # one image is an LNK2038 hard error, not a warning. Set before
    # find_package(CEF): cef_variables.cmake bakes this into the flag lists at
    # include time.
    if(WIN32)
        set(CEF_RUNTIME_LIBRARY_FLAG "/MD" CACHE STRING
            "CRT flag for CEF's wrapper; must match the rest of the project" FORCE)
    endif()

    # CEF enables its sandbox by default on Windows, which selects the
    # bootstrap app model: the application is built as a DLL launched by
    # bootstrap.exe, and links cef_sandbox.lib. This host initializes CEF with
    # no_sandbox = true (see ui_cef/cef_lifecycle.cc), so the sandbox model
    # does not apply -- and leaving it on defines CEF_USE_BOOTSTRAP and
    # rewrites how libcef is linked. Must precede find_package(CEF).
    if(WIN32)
        set(USE_SANDBOX OFF CACHE BOOL
            "CEF sandbox; off because this host runs with no_sandbox" FORCE)
    endif()

    find_package(CEF REQUIRED)

    # libcef.lib is the import library for libcef.dll and provides the C API
    # the wrapper calls into. macOS has no equivalent -- the framework is
    # loaded dynamically -- which is why nothing linked it before.
    if(WIN32 AND NOT TARGET libcef_lib)
        ADD_LOGICAL_TARGET("libcef_lib" "${CEF_LIB_DEBUG}" "${CEF_LIB_RELEASE}")
    endif()

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
    #
    # Gated on the same compilers that get -Wpedantic in the first place (see
    # the top of this file): there is nothing to suppress under MSVC, and cl
    # rejects the unknown -W option outright with D8021 -- a hard error, not a
    # warning, so the whole CEF build fails on Windows without this guard.
    if(TARGET libcef_dll_wrapper AND CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
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
add_subdirectory(tools/dump_bounds)
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
add_subdirectory(tools/voxel_inspect)

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
