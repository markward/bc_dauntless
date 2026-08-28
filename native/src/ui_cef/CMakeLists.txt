# ui_cef — CEF-backed UI overlay (transparent browser composited over the
# 3D scene). Linked into both dauntless and _dauntless_host.

if(NOT DAUNTLESS_ENABLE_CEF)
    return()
endif()

set(UI_CEF_SOURCES
    cef_app.cc
    cef_client.cc
    cef_composite_pass.cc
    cef_lifecycle.cc
)
if(APPLE)
    list(APPEND UI_CEF_SOURCES cef_macos_app.mm)
endif()

add_library(ui_cef STATIC ${UI_CEF_SOURCES})

target_include_directories(ui_cef PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/..
    ${CEF_INCLUDE_PATH}
)

# CEF's logging headers use GNU token-pasting; project-wide -Wpedantic
# would otherwise reject CEF include sites. PUBLIC so any translation
# unit that includes CEF via ui_cef inherits the suppression.
#
# GCC/Clang spelling only. MSVC has no such warning to suppress and answers an
# unknown -W option with D9002 for every translation unit that inherits it --
# and this is PUBLIC, so that is every consumer of ui_cef.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(ui_cef PUBLIC
        -Wno-gnu-zero-variadic-macro-arguments
    )
endif()

if(WIN32)
    # CEF headers call std::min/std::max. <windows.h> defines min/max as macros
    # unless NOMINMAX is set, which turns those calls into syntax errors inside
    # CEF's own headers (cef_types_wrappers.h). CEF's bundled wrapper target
    # defines these for itself; consumers have to do the same.
    target_compile_definitions(ui_cef PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

target_compile_features(ui_cef PRIVATE cxx_std_20)

target_link_libraries(ui_cef PUBLIC
    libcef_dll_wrapper
    $<$<BOOL:${WIN32}>:libcef_lib>
    ${CEF_STANDARD_LIBS}
    renderer
    glfw
)
