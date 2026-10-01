# The writer half is its own small static library so the round-trip gtest
# (native/tests/rockgen/catalogue_writer_test.cc) can exercise the exact
# bytes this tool ships without duplicating main.cc's CLI plumbing.
add_library(rock_catalogue_writer STATIC writer.cc)
target_include_directories(rock_catalogue_writer PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(rock_catalogue_writer
    PUBLIC rockgen voxel assets nlohmann_json::nlohmann_json stb_image)

add_executable(rock_catalogue main.cc)
target_link_libraries(rock_catalogue PRIVATE
    rock_catalogue_writer rockgen voxel nif assets stb_image nlohmann_json::nlohmann_json)

# Block parsers self-register via static initializers in libnif.a; force the
# whole archive in so every registration runs (NiBinaryVoxelData included).
if(APPLE)
    target_link_options(rock_catalogue PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(rock_catalogue PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
elseif(MSVC)
    target_link_options(rock_catalogue PRIVATE
        "/WHOLEARCHIVE:$<TARGET_FILE:nif>")
endif()
