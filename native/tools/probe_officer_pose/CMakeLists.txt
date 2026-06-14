add_executable(probe_officer_pose probe_officer_pose.cc)
target_link_libraries(probe_officer_pose PRIVATE assets nif glm)
# nif self-registers its block parsers via static initializers; without
# force-loading the archive the linker dead-strips those TUs and nif::load
# returns 0 blocks. Mirror the other probe tools.
if(APPLE)
    target_link_options(probe_officer_pose PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(probe_officer_pose PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
