add_executable(probe_bound_radius probe_bound_radius.cc)
target_link_libraries(probe_bound_radius PRIVATE nif)
if(APPLE)
    target_link_options(probe_bound_radius PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(probe_bound_radius PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
