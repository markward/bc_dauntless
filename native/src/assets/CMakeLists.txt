add_library(assets STATIC
    src/animation_build.cc
    src/cache.cc
    src/gl_handle.cc
    src/flip_frame.cc
    src/material_build.cc
    src/mesh_build.cc
    src/mesh_lifetime.cc
    src/mesh_upload.cc
    src/model_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/skin_weights.cc
    src/texture_decode.cc
    src/texture_lifetime.cc
    src/texture_upload.cc
)
target_include_directories(assets PUBLIC include)
target_compile_features(assets PUBLIC cxx_std_20)
target_link_libraries(assets PUBLIC nif glm glad stb_image)
