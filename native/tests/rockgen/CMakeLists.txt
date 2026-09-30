add_executable(rockgen_tests
    recipe_test.cc
    shape_test.cc
    surface_test.cc
    impostor_test.cc
    catalogue_writer_test.cc
)
target_link_libraries(rockgen_tests PRIVATE rockgen rock_catalogue_writer GTest::gtest_main)
gtest_discover_tests(rockgen_tests)
