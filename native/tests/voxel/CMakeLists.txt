add_executable(voxel_tests
    volume_test.cc
    voxelize_test.cc
    decode_test.cc
)
target_link_libraries(voxel_tests PRIVATE voxel GTest::gtest_main)
target_compile_definitions(voxel_tests PRIVATE
    OPEN_STBC_PROJECT_ROOT="${CMAKE_SOURCE_DIR}")
gtest_discover_tests(voxel_tests)
