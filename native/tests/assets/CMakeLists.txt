add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/animation_build_test.cc
    cpu/cache_test.cc
    cpu/material_build_test.cc
    cpu/mesh_build_test.cc
    cpu/model_build_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/skeleton_build_test.cc
    cpu/texture_decode_test.cc
    gpu/gl_fixture.cc
    gpu/fixture_smoke_test.cc
    gpu/mesh_upload_test.cc
    gpu/model_smoke_test.cc
    gpu/texture_upload_test.cc
)

target_link_libraries(assets_tests
    PRIVATE
        assets
        GTest::gtest_main
        glfw
)

# Block parsers in libnif.a self-register via static initializers. Without
# force-load, the linker drops object files that aren't otherwise referenced
# and the registrations never run. Mirror the pattern used by nif_tests.
if(APPLE)
    target_link_options(assets_tests PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(assets_tests PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()

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
