add_library(nif STATIC
    src/dispatch.cc
    src/file.cc
    src/header.cc
    src/reader.cc
    src/resolver.cc
    src/blocks/av_object_base.cc
    src/blocks/ni_node.cc
    src/blocks/ni_tri_shape.cc
    src/blocks/properties.cc
)

target_include_directories(nif
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(nif PUBLIC cxx_std_20)
