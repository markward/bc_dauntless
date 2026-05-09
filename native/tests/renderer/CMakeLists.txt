add_executable(renderer_tests
    window_test.cc
)

target_link_libraries(renderer_tests
    PRIVATE
        renderer
        GTest::gtest_main
)

target_include_directories(renderer_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/tests/assets/gpu  # reuse gl_fixture for offscreen contexts
)

gtest_discover_tests(renderer_tests
    PROPERTIES
        ENVIRONMENT "GALLIUM_DRIVER=llvmpipe"
)
