add_library(assets STATIC
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/mesh_lifetime.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
    src/texture_lifetime.cc
)
target_include_directories(assets PUBLIC include)
target_compile_features(assets PUBLIC cxx_std_20)
target_link_libraries(assets PUBLIC nif glm glad stb_image)
