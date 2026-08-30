add_executable(platform_tests
    exe_path_test.cc
)
target_link_libraries(platform_tests PRIVATE platform GTest::gtest_main)
target_compile_definitions(platform_tests PRIVATE
    OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}")

# No force_load here: libplatform.a has no self-registering static
# initializers, so the linker keeping only referenced objects is correct.

gtest_discover_tests(platform_tests)
