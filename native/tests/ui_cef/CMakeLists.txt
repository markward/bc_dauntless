# The upload policy is header-only and has no CEF or GL dependency, so this
# test builds whether or not DAUNTLESS_ENABLE_CEF is on.
add_executable(ui_cef_tests
    cef_upload_policy_test.cc
)
target_include_directories(ui_cef_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/src/ui_cef)
target_link_libraries(ui_cef_tests PRIVATE GTest::gtest_main)

gtest_discover_tests(ui_cef_tests)
