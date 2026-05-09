add_library(renderer STATIC
    window.cc
)
target_include_directories(renderer PUBLIC include)
target_compile_features(renderer PUBLIC cxx_std_20)
target_link_libraries(renderer PUBLIC assets glad glfw glm)
