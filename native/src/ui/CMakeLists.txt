# native/src/ui/CMakeLists.txt — RmlUi integration library.
#
# The GLFW platform backend and GL3 render backend are compiled here from the
# FetchContent source tree so they pick up our glad + glfw targets rather than
# any system copies.

add_library(ui STATIC
    UiSystem.cc
    HudDocument.cc
    ${rmlui_SOURCE_DIR}/Backends/RmlUi_Platform_GLFW.cpp
    ${rmlui_SOURCE_DIR}/Backends/RmlUi_Renderer_GL3.cpp
)

target_include_directories(ui
    PUBLIC  include
    PRIVATE "${rmlui_SOURCE_DIR}/Backends"
)

# glad must be included before any GL headers; linking it here makes its
# include path available to the backend sources.
target_link_libraries(ui PUBLIC RmlCore glad glfw)

target_compile_features(ui PUBLIC cxx_std_20)
