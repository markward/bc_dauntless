# platform — small OS-facing helpers shared by the host binary and ui_cef.
#
# Deliberately a .cc/.h split rather than a header-only utility: the Windows
# implementation needs <windows.h>, and this header is included by CEF
# translation units. Pulling <windows.h> in there collides with CEF's
# std::min/std::max usage (see the NOMINMAX handling in src/ui_cef).
add_library(platform STATIC exe_path.cc)

target_include_directories(platform PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/..")
target_compile_features(platform PUBLIC cxx_std_20)
