add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
)
target_include_directories(scenegraph PUBLIC include)
target_compile_features(scenegraph PUBLIC cxx_std_20)
target_link_libraries(scenegraph PUBLIC glm)
