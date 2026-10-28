# Host-side logic that the pybind module calls, tested from C++ where the
# process-global developer gate (dauntless::set_developer_mode) can be set
# without exposing any setter to Python.
add_executable(host_tests
    bridge_highlight_test.cc
    model_identity_maps_test.cc
)
target_link_libraries(host_tests
    PRIVATE
        dauntless_host_core
        GTest::gtest_main
)
# model_build.h (assets' private header): the identity-maps test builds a
# model through the real loader.
target_include_directories(host_tests PRIVATE ${CMAKE_SOURCE_DIR}/native/src/assets/src)
gtest_discover_tests(host_tests)
