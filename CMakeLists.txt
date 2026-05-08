cmake_minimum_required(VERSION 3.20)
project(open_stbc)

# Tests are enabled if OPEN_STBC_BUILD_TESTS is ON (defined in native/CMakeLists.txt).
# enable_testing() must be called at the top level for ctest to discover tests.
enable_testing()

add_subdirectory(native)
