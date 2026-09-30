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
# The catalogue is committed, so generation must not depend on whether the
# compiler fuses a*b+c into an FMA (clang on arm64 contracts by default).
if(NOT MSVC)
    target_compile_options(rockgen PRIVATE -ffp-contract=off)
endif()
