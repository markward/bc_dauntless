add_library(lottie STATIC
    src/lottie_clip.cc
)
target_include_directories(lottie PUBLIC include)
target_compile_features(lottie PUBLIC cxx_std_20)
target_link_libraries(lottie PUBLIC assets PRIVATE thorvg)
