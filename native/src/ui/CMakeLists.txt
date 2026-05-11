# native/src/ui/CMakeLists.txt — RmlUi integration library.
#
# The GLFW platform backend and GL3 render backend are compiled here from the
# FetchContent source tree so they pick up our glad + glfw targets rather than
# any system copies.

add_library(ui STATIC
    UiSystem.cc
    HudDocument.cc
    PanelDocument.cc
    ${rmlui_SOURCE_DIR}/Backends/RmlUi_Platform_GLFW.cpp
    ${rmlui_SOURCE_DIR}/Backends/RmlUi_Renderer_GL3.cpp
)

target_include_directories(ui
    PUBLIC  include
    PRIVATE "${rmlui_SOURCE_DIR}/Backends"
)

# Use our glad for RmlUi's GL3 backend rather than RmlUi's vendored glad 2.x
# — otherwise both libraries define the same glad_glXXX symbols and the host
# binary fails to link with 357 duplicate symbols. RMLUI_GL3_CUSTOM_LOADER
# names a header to #include in place of RmlUi_Include_GL3.h.
target_compile_definitions(ui PRIVATE
    "RMLUI_GL3_CUSTOM_LOADER=<glad/glad.h>"
)

# glad must be included before any GL headers; linking it here makes its
# include path available to the backend sources.
target_link_libraries(ui PUBLIC RmlUi::Core RmlUi::Debugger glad glfw)

target_compile_features(ui PUBLIC cxx_std_20)
