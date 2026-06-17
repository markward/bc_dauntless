include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.14.0
)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

include(GoogleTest)

add_executable(nif_tests
    nif/sanity_test.cc
    nif/types_test.cc
    nif/reader_test.cc
    nif/version_test.cc
    nif/canonical_dump.cc
    nif/header_unit_test.cc
    nif/header_test.cc
    nif/error_test.cc
    nif/resolver_test.cc
    nif/ni_node_test.cc
    nif/ni_tri_shape_test.cc
    nif/ship_gate_test.cc
    nif/animation_parse_test.cc
    nif/legacy_rng_test.cc
    nif/voxel_data_test.cc
)

target_link_libraries(nif_tests
    PRIVATE
        nif
        GTest::gtest_main
)

# Block parsers self-register via static initializers in libnif.a. Without
# force-load, the linker drops object files that aren't otherwise referenced,
# and the registrations never run. Force-load the whole archive so every
# block parser registers its dispatch entry.
if(APPLE)
    target_link_options(nif_tests PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(nif_tests PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()

target_include_directories(nif_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

# Bake the project root path into the test binary so sample-file paths
# resolve regardless of the working directory ctest is invoked from.
target_compile_definitions(nif_tests
    PRIVATE
        OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}"
)

gtest_discover_tests(nif_tests)

add_subdirectory(assets)
add_subdirectory(renderer)
add_subdirectory(scenegraph)
add_subdirectory(audio)
add_subdirectory(voxel)
