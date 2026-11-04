add_library(dauntless_transforms STATIC
    src/transform_store.cc
    src/torpedo_scan.cc
    src/proximity_query.cc
    src/interp_buffer.cc
)
target_include_directories(dauntless_transforms PUBLIC include)
target_compile_features(dauntless_transforms PUBLIC cxx_std_20)
target_link_libraries(dauntless_transforms PUBLIC glm)
# The incoming-torpedo scan, the proximity sphere test and the render
# interpolation twin must round exactly as CPython does (see torpedo_scan.h,
# transform_store.h, interp_buffer.h): no fused multiply-add.
if(NOT MSVC)
    set_source_files_properties(src/torpedo_scan.cc src/proximity_query.cc
        src/interp_buffer.cc
        PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
endif()
