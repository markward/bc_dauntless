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

# Public libraries.
add_subdirectory(src/nif)
add_subdirectory(src/assets)

# enable_testing() must precede any add_subdirectory whose CMakeLists registers
# add_test (scan_nifs registers its corpus-coverage test conditionally).
enable_testing()

# Diagnostic tools that consume the public library.
add_subdirectory(tools/scan_nifs)

option(OPEN_STBC_BUILD_TESTS "Build native tests for open_stbc" ON)
if(OPEN_STBC_BUILD_TESTS)
  set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
  set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
  add_subdirectory(third_party/glfw)
  add_subdirectory(tests)
endif()
