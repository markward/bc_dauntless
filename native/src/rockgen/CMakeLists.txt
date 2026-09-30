add_library(rockgen STATIC
    src/recipe.cc
    src/shape.cc
    src/surface.cc
    src/impostor.cc
)
target_include_directories(rockgen PUBLIC include)
target_compile_features(rockgen PUBLIC cxx_std_20)
# assets for MeshCpu (header only here -- rockgen makes no GL calls).
target_link_libraries(rockgen
    PUBLIC assets glm
    PRIVATE nlohmann_json::nlohmann_json)
