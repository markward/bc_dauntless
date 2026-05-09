add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/texture_decode_test.cc
)

target_link_libraries(assets_tests
    PRIVATE
        assets
        GTest::gtest_main
)

target_include_directories(assets_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/native/src/assets/src
)

# Bake the project root path so sample-file tests can find game/ assets.
target_compile_definitions(assets_tests
    PRIVATE
        OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}"
)

gtest_discover_tests(assets_tests)
