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
)

target_link_libraries(nif_tests
    PRIVATE
        nif
        GTest::gtest_main
)

target_include_directories(nif_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

gtest_discover_tests(nif_tests)
