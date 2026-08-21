add_executable(dump_bounds dump_bounds.cc)

target_link_libraries(dump_bounds PRIVATE nif renderer)

# Block parsers self-register via static initializers in libnif.a; force the
# whole archive in so every registration runs (same as scan_nifs).
if(APPLE)
    target_link_options(dump_bounds PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(dump_bounds PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
