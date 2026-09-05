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
elseif(MSVC)
    target_link_options(scan_nifs PRIVATE
        "/WHOLEARCHIVE:$<TARGET_FILE:nif>")
endif()

# Register a corpus-coverage test when a BC install is present. The game root
# is configurable (engine/paths.py: CLI flag, env var, settings.json, or the
# in-project game/ fallback) and CMake cannot read settings.json itself, so
# ask the same authority Python uses, at configure time. Falls back to the
# in-project game/ if that fails (Python missing/broken, or paths unresolved)
# so this degrades to the old behaviour rather than breaking configure.
find_package(Python3 COMPONENTS Interpreter QUIET)
set(_BC_GAME_ROOT "")
if(Python3_EXECUTABLE)
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c
            "from engine import paths; print(paths.game_root())"
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        OUTPUT_VARIABLE _BC_GAME_ROOT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
        RESULT_VARIABLE _BC_GAME_RC)
    if(NOT _BC_GAME_RC EQUAL 0 OR _BC_GAME_ROOT STREQUAL "")
        set(_BC_GAME_ROOT "")
    endif()
endif()
if(_BC_GAME_ROOT STREQUAL "")
    set(_BC_GAME_ROOT "${CMAKE_SOURCE_DIR}/game")
endif()
get_filename_component(_BC_GAME_DATA "${_BC_GAME_ROOT}/data" ABSOLUTE)

# Register unconditionally so absence is a visible SKIP/FAIL rather than the
# test silently not existing (ctest prints "0 failures" identically either
# way, which previously hid this test having vanished from the list).
add_test(NAME scan_nifs_corpus COMMAND scan_nifs "${_BC_GAME_DATA}")
if(NOT EXISTS "${_BC_GAME_DATA}")
    set_tests_properties(scan_nifs_corpus PROPERTIES
        DISABLED TRUE)
endif()
