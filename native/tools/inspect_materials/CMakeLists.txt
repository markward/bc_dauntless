add_executable(inspect_materials inspect_materials.cc)
target_link_libraries(inspect_materials PRIVATE nif)
if(APPLE)
    target_link_options(inspect_materials PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(inspect_materials PRIVATE
        "LINKER:--whole-archive" "$<TARGET_FILE:nif>" "LINKER:--no-whole-archive")
elseif(MSVC)
    target_link_options(inspect_materials PRIVATE
        "/WHOLEARCHIVE:$<TARGET_FILE:nif>")
endif()
