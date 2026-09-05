add_library(dauntless_transforms STATIC
    src/transform_store.cc
)
target_include_directories(dauntless_transforms PUBLIC include)
target_compile_features(dauntless_transforms PUBLIC cxx_std_20)
