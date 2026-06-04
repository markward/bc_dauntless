add_executable(dump_nif_tree dump_nif_tree.cc)
target_link_libraries(dump_nif_tree PRIVATE nif)

if(APPLE)
    target_link_options(dump_nif_tree PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(dump_nif_tree PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
