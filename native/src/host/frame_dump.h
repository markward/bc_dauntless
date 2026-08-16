#pragma once
#include <string>

namespace dauntless {

/// Read the default framebuffer's colour and write it out as a PNG.
///
/// Developer diagnostic support: the HDR black-square bug is a single-frame
/// artefact at an unpredictable position, which makes it effectively impossible
/// to capture by hand. The non-finite probe fires on the frame it happens, and
/// this writes that exact frame to disk.
///
/// `path` must be absolute — GLFW changes the process working directory on
/// macOS, so a relative path lands somewhere surprising. Returns false if the
/// readback or the write fails.
bool dump_default_framebuffer_png(const std::string& path, int w, int h);

}  // namespace dauntless
