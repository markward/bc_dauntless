add_library(lottie STATIC
    src/lottie_clip.cc
    src/panel_math.cc
    src/panel_worker.cc
)
target_include_directories(lottie PUBLIC include)
target_compile_features(lottie PUBLIC cxx_std_20)
find_package(Threads REQUIRED)
target_link_libraries(lottie PUBLIC assets PRIVATE thorvg Threads::Threads)
