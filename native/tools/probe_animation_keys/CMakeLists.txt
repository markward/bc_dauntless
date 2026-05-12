add_executable(probe_animation_keys probe_animation_keys.cc)
target_link_libraries(probe_animation_keys PRIVATE nif)
if(APPLE)
    target_link_options(probe_animation_keys PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(probe_animation_keys PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
