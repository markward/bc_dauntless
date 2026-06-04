add_executable(inspect_tex_props inspect_tex_props.cc)
target_link_libraries(inspect_tex_props PRIVATE nif)
if(APPLE)
    target_link_options(inspect_tex_props PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(inspect_tex_props PRIVATE
        "LINKER:--whole-archive" "$<TARGET_FILE:nif>" "LINKER:--no-whole-archive")
endif()
