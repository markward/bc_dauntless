# The upload policy is header-only and has no CEF or GL dependency, so this
# test builds whether or not DAUNTLESS_ENABLE_CEF is on.
add_executable(ui_cef_tests
    cef_upload_policy_test.cc
    cef_dirty_rects_test.cc
)
target_include_directories(ui_cef_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/src/ui_cef)
target_link_libraries(ui_cef_tests PRIVATE GTest::gtest_main)

gtest_discover_tests(ui_cef_tests)

# The composite pass's sub-image upload on a real GL context (hidden GLFW
# window via the assets tests' gl_fixture; skips without one). The pass
# itself includes only glad, so it is compiled in directly with no CEF.
add_executable(ui_cef_gpu_tests
    cef_composite_pass_gpu_test.cc
    ${CMAKE_SOURCE_DIR}/native/src/ui_cef/cef_composite_pass.cc
    ${CMAKE_SOURCE_DIR}/native/tests/assets/gpu/gl_fixture.cc
)
target_include_directories(ui_cef_gpu_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/src/ui_cef
    ${CMAKE_SOURCE_DIR}/native/tests/assets/gpu)
target_link_libraries(ui_cef_gpu_tests PRIVATE glad glfw GTest::gtest_main)

gtest_discover_tests(ui_cef_gpu_tests
    PROPERTIES
        ENVIRONMENT "GALLIUM_DRIVER=llvmpipe"
)
