add_executable(probe_block_inventory probe_block_inventory.cc)
target_link_libraries(probe_block_inventory PRIVATE nif)
if(APPLE)
    target_link_options(probe_block_inventory PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(probe_block_inventory PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
