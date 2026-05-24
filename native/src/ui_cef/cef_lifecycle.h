// native/src/ui_cef/cef_lifecycle.h
//
// Process-wide entry points for the CEF UI overlay. host_bindings.cc calls
// only these functions; everything else (CefApp, CefClient, CefBrowser,
// CefRefPtr) is internal to ui_cef so the bindings translation unit does
// not depend on libcef directly.

#pragma once

#include <string>

namespace dauntless::ui_cef {

// Called first thing in main(). Returns >= 0 if argv indicates a CEF
// subprocess role (helper / renderer / GPU process); the caller must
// exit() with that code immediately. Returns -1 for the main browser
// process (continue with normal startup).
int dispatch_subprocess(int argc, char* argv[]);

// Call once after the GL context is current. Loads the CEF framework,
// runs CefInitialize, and creates an OSR browser pointed at html_path
// (file:// URL synthesised from this absolute path). view_width/height
// determine the OSR viewport; resize handling is a follow-up task.
bool initialize(int view_width, int view_height, const std::string& html_path);

// Call once per frame after the 3D scene renders.
//   pump()      runs CEF's message loop (may invoke OnPaint synchronously);
//   composite() blits the latest CEF bitmap with premultiplied-alpha blend.
void pump();
void composite();

// F12 / Cmd+R handlers. No-op if no browser is alive.
void toggle_devtools();
void reload();

// Called before window/GL teardown. Releases the browser and CEF.
void shutdown();

}  // namespace dauntless::ui_cef
