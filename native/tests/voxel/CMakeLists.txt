add_executable(voxel_tests
    volume_test.cc
    voxelize_test.cc
    decode_test.cc
)
target_link_libraries(voxel_tests PRIVATE voxel GTest::gtest_main)
target_compile_definitions(voxel_tests PRIVATE
    OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}")

# Block parsers in libnif.a self-register via static initializers. Without
# force-load the linker drops object files not otherwise referenced and the
# registrations never run. Same pattern as assets_tests / nif_tests.
if(APPLE)
    target_link_options(voxel_tests PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(voxel_tests PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()

gtest_discover_tests(voxel_tests)
