add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
    src/damage_decals.cc
    src/hull_craters.cc
)
target_include_directories(scenegraph PUBLIC include)
target_compile_features(scenegraph PUBLIC cxx_std_20)
target_link_libraries(scenegraph PUBLIC glm)
