add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
)

target_link_libraries(renderer_tests
    PRIVATE
        renderer
        GTest::gtest_main
)

# Force-load the nif static library so block parsers self-register via
# static initializers (matches the pattern used by nif_tests / assets_tests).
if(APPLE)
    target_link_options(renderer_tests PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(renderer_tests PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()

target_include_directories(renderer_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/tests/assets/gpu  # reuse gl_fixture for offscreen contexts
)

gtest_discover_tests(renderer_tests
    PROPERTIES
        ENVIRONMENT "GALLIUM_DRIVER=llvmpipe"
)
