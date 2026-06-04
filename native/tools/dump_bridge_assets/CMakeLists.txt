add_executable(dump_bridge_assets dump_bridge_assets.cc)
target_link_libraries(dump_bridge_assets PRIVATE assets nif)

if(APPLE)
    target_link_options(dump_bridge_assets PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(dump_bridge_assets PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
