# platform — small OS-facing helpers shared by the host binary and ui_cef.
#
# Deliberately a .cc/.h split rather than a header-only utility: the Windows
# implementation needs <windows.h>, and this header is included by CEF
# translation units. Pulling <windows.h> in there collides with CEF's
# std::min/std::max usage (see the NOMINMAX handling in src/ui_cef).
set(PLATFORM_SOURCES exe_path.cc folder_picker.cc)
if(APPLE)
    list(APPEND PLATFORM_SOURCES folder_picker.mm)
elseif(WIN32)
    list(APPEND PLATFORM_SOURCES folder_picker_win.cc)
endif()

add_library(platform STATIC ${PLATFORM_SOURCES})

# NSOpenPanel. PUBLIC so every target linking `platform` inherits the
# framework; both _dauntless_host and the host binary do.
if(APPLE)
    target_link_libraries(platform PUBLIC "-framework AppKit")
elseif(WIN32)
    # IFileDialog: CoCreateInstance lives in ole32, the CLSID/IID in uuid.
    target_link_libraries(platform PUBLIC ole32 uuid)
endif()

target_include_directories(platform PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/..")
target_compile_features(platform PUBLIC cxx_std_20)
