add_executable(probe_texture_stages probe_texture_stages.cc)
target_link_libraries(probe_texture_stages PRIVATE nif)
if(APPLE)
    target_link_options(probe_texture_stages PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(probe_texture_stages PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
