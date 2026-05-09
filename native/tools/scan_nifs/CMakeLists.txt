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

# Register a corpus-coverage test when a BC install is present at game/data.
# Skipped silently when assets are absent (e.g. fresh clone, CI without game).
# Re-run cmake configure after dropping in game/ to pick this up.
# Anchored on this dir (native/tools/scan_nifs) so it resolves whether cmake
# is configured against the project root or against native/ directly.
get_filename_component(_BC_GAME_DATA
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../game/data" ABSOLUTE)
if(EXISTS "${_BC_GAME_DATA}")
    add_test(NAME scan_nifs_corpus COMMAND scan_nifs "${_BC_GAME_DATA}")
endif()
