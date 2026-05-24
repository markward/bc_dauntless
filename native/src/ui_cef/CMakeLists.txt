# ui_cef — CEF-backed UI overlay (transparent browser composited over the
# 3D scene). Linked into both dauntless and _dauntless_host.

if(NOT DAUNTLESS_ENABLE_CEF)
    return()
endif()

add_library(ui_cef STATIC
    cef_app.cc
    cef_client.cc
    cef_composite_pass.cc
    cef_lifecycle.cc
)

target_include_directories(ui_cef PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/..
    ${CEF_INCLUDE_PATH}
)

# CEF's logging headers use GNU token-pasting; project-wide -Wpedantic
# would otherwise reject CEF include sites. PUBLIC so any translation
# unit that includes CEF via ui_cef inherits the suppression.
target_compile_options(ui_cef PUBLIC
    -Wno-gnu-zero-variadic-macro-arguments
)

target_compile_features(ui_cef PRIVATE cxx_std_20)

target_link_libraries(ui_cef PUBLIC
    libcef_dll_wrapper
    ${CEF_STANDARD_LIBS}
    renderer
    glfw
)
