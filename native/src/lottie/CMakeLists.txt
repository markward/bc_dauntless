add_library(lottie STATIC
    src/lottie_clip.cc
    src/panel_math.cc
    src/panel_worker.cc
)
target_include_directories(lottie PUBLIC include)
target_compile_features(lottie PUBLIC cxx_std_20)
find_package(Threads REQUIRED)
target_link_libraries(lottie PUBLIC assets PRIVATE thorvg Threads::Threads)

# panel_math.cc (the per-frame still composite) is optimised in every
# configuration, Debug included: the panels exist to move smoothly and Mark
# runs Debug, where -O0 made a 2048-wide composite 156 ms (18 ms at -O2).
if(MSVC)
    # MSVC rejects /O2 beside /RTC1 and warns when it overrides /Od or /Ob0, so
    # this directory's Debug flags lose all three and the other sources get
    # them back per source.
    string(REGEX REPLACE "/RTC[1csu]+|/Od|/Ob0" "" CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG}")
    set_source_files_properties(src/lottie_clip.cc src/panel_worker.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:/Od>;$<$<CONFIG:Debug>:/Ob0>;$<$<CONFIG:Debug>:/RTC1>")
    set_source_files_properties(src/panel_math.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:/O2>")
else()
    set_source_files_properties(src/panel_math.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:-O2>")
endif()
