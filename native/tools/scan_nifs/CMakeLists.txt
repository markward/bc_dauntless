add_executable(scan_nifs scan_nifs.cc)

target_link_libraries(scan_nifs PRIVATE nif)

# Block parsers self-register via static initializers in libnif.a; force the
# whole archive in so every registration runs.
if(APPLE)
    target_link_options(scan_nifs PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:nif>")
elseif(UNIX)
    target_link_options(scan_nifs PRIVATE
        "LINKER:--whole-archive"
        "$<TARGET_FILE:nif>"
        "LINKER:--no-whole-archive")
endif()
