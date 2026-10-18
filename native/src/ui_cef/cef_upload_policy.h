// native/src/ui_cef/cef_upload_policy.h
//
// Whether a frame's composite uploads the CEF bitmap to its texture.
// Header-only with no CEF or GL dependency, so it is unit-tested on its own
// (native/tests/ui_cef/cef_upload_policy_test.cc).
//
// Exists for perf-register A-1 (docs/engine/perf-register.md): the CPU time
// in `cef.composite` tracks the GPU frame time almost exactly, which points
// at the full-surface glTexSubImage2D as the place the CPU waits for the GPU.
// The modes, chosen by DAUNTLESS_CEF_UPLOAD:
//
//   always    every frame (unset or unknown value; the original behaviour)
//   on_paint  only a frame CEF repainted since the last upload. Lossless:
//             an unrepainted frame redraws the texture it already holds.
//   never     only the first upload and size changes. The overlay FREEZES;
//             a diagnostic that removes the upload from every later frame.
//
// Every mode uploads when the texture must be (re)allocated.
#pragma once

#include <cstdint>
#include <cstring>

namespace dauntless::ui_cef {

enum class UploadMode { Always, OnPaint, Never };

inline UploadMode parse_upload_mode(const char* value) {
    if (value != nullptr) {
        if (std::strcmp(value, "on_paint") == 0) return UploadMode::OnPaint;
        if (std::strcmp(value, "never") == 0) return UploadMode::Never;
    }
    return UploadMode::Always;
}

inline const char* upload_mode_name(UploadMode mode) {
    switch (mode) {
        case UploadMode::OnPaint: return "on_paint";
        case UploadMode::Never:   return "never";
        case UploadMode::Always:  break;
    }
    return "always";
}

inline bool should_upload(UploadMode mode, bool texture_allocated,
                          bool size_changed, std::uint64_t paint_generation,
                          std::uint64_t uploaded_generation) {
    if (!texture_allocated || size_changed) return true;
    switch (mode) {
        case UploadMode::Always:  return true;
        case UploadMode::OnPaint: return paint_generation != uploaded_generation;
        case UploadMode::Never:   return false;
    }
    return true;
}

}  // namespace dauntless::ui_cef
