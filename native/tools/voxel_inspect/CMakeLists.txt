add_executable(voxel_inspect main.cc)

target_link_libraries(voxel_inspect PRIVATE nif)

# Block parsers self-register via static initializers in libnif.a; force the
# whole archive in so every registration runs (NiBinaryVoxelData included).
if(APPLE)
    target_link_options(voxel_inspect PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(voxel_inspect PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
