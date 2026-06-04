add_executable(inspect_flip inspect_flip.cc)
target_link_libraries(inspect_flip PRIVATE nif)
if(APPLE)
    target_link_options(inspect_flip PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
endif()
