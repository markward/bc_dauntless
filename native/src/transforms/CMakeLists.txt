add_library(dauntless_transforms STATIC
    src/transform_store.cc
    src/torpedo_scan.cc
    src/proximity_query.cc
)
target_include_directories(dauntless_transforms PUBLIC include)
target_compile_features(dauntless_transforms PUBLIC cxx_std_20)
target_link_libraries(dauntless_transforms PUBLIC glm)
# The incoming-torpedo scan and the proximity sphere test must round exactly
# as CPython does (see torpedo_scan.h, transform_store.h): no fused
# multiply-add.
if(NOT MSVC)
    set_source_files_properties(src/torpedo_scan.cc src/proximity_query.cc
        PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
endif()
