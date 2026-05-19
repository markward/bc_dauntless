cmake_minimum_required(VERSION 3.20)
project(dauntless)

# Tests are enabled if DAUNTLESS_BUILD_TESTS is ON (defined in native/CMakeLists.txt).
# enable_testing() must be called at the top level for ctest to discover tests.
enable_testing()

add_subdirectory(native)
