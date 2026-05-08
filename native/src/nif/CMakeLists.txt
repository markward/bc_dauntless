add_library(nif STATIC
    src/file.cc
    src/reader.cc
)

target_include_directories(nif
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(nif PUBLIC cxx_std_20)
