add_executable(lottie_tests
    lottie_clip_test.cc
    panel_math_test.cc
    panel_worker_test.cc
)

target_link_libraries(lottie_tests
    PRIVATE
        lottie
        GTest::gtest_main
)

target_compile_definitions(lottie_tests
    PRIVATE
        LOTTIE_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
)

gtest_discover_tests(lottie_tests)
