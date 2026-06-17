add_library(voxel STATIC
    src/volume.cc
    src/voxelize.cc
    src/decode.cc
)
target_include_directories(voxel PUBLIC include)
target_compile_features(voxel PUBLIC cxx_std_20)
# glm is used in the public header (volume.h). nif/assets are used only in
# the .cc files (forward-declared in headers), but kept PUBLIC so voxel_tests
# inherits their include paths transitively — decode_test.cc includes nif/*.
target_link_libraries(voxel PUBLIC nif assets glm)
