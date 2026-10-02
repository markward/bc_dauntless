// native/src/ui_cef/cef_lifecycle.h
//
// Process-wide entry points for the CEF UI overlay. host_bindings.cc calls
// only these functions; everything else (CefApp, CefClient, CefBrowser,
// CefRefPtr) is internal to ui_cef so the bindings translation unit does
// not depend on libcef directly.

#pragma once

#include <functional>
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
// device_scale_factor — DPR for the GL framebuffer the composite pass
// writes to (1.0 on non-Retina; 2.0 on Retina). Pass framebuffer_w /
// window_w from the host. CEF renders the OSR bitmap at
// view_width*dsf × view_height*dsf so the composite blits 1:1 to a
// high-DPI framebuffer without bilinear upscaling.
bool initialize(int view_width, int view_height,
                const std::string& html_path,
                float device_scale_factor);

// Re-size the OSR browser to track the host window. view_width/height are
// the new logical (window-point) dimensions; device_scale_factor is the
// new framebuffer/window ratio (recomputed in case the window moved to a
// different-DPI monitor). Updates the client's GetViewRect/GetScreenInfo
// response and calls CefBrowserHost::WasResized(), which makes CEF
// re-layout the HTML/CSS at the new size and re-raster — so the overlay
// reflows instead of being bilinear-stretched by the composite pass.
// No-op if no browser is alive. Safe to call every frame; cheap when the
// size is unchanged (the host should still guard to avoid needless
// WasResized churn).
void resize(int view_width, int view_height, float device_scale_factor);

// Call once per frame after the 3D scene renders.
//   pump()      runs CEF's message loop (may invoke OnPaint synchronously);
//   composite() blits the latest CEF bitmap with premultiplied-alpha blend.
void pump();
void composite();

// F12 / Cmd+R handlers. No-op if no browser is alive.
void toggle_devtools();
void reload();

// True while the DevTools window for the overlay browser is open. The host
// loop freezes the simulation on this so the UI you are inspecting cannot
// advance out from under you. Tracks the real window, so closing DevTools
// via its own close button also unfreezes. False if no browser is alive.
bool devtools_open();

// Execute a JavaScript string in the main frame of the overlay browser.
// No-op if no browser is alive. Used to drive DOM mutation from Python
// (e.g. toggling visibility of pause-menu HTML).
void execute_javascript(const std::string& script);

// Mouse-event forwarding to the OSR browser. Coordinates are in CEF
// view-space (matches GLFW window coords on non-Retina; on Retina the
// caller must convert if the framebuffer is scaled). No-op if no
// browser is alive.
//
//   send_mouse_move:  hover / cursor tracking (e.g. for CSS :hover)
//   send_mouse_click: left/middle/right click edge.
//                     button: 0=left, 1=middle, 2=right.
//   send_mouse_wheel: scroll wheel; delta_y positive scrolls up.
void send_mouse_move(int x, int y);
void send_mouse_click(int x, int y, int button, bool is_down);
void send_mouse_wheel(int x, int y, int delta_y);

// Keyboard forwarding for typed CEF fields: one already-paired
// renderer::CefKeyIntent (renderer::TextEventTranslator's output). `type`
// is a renderer::CefKeyType value, cast to cef_key_event_type_t (the two
// enums share the same four values 0-3 by construction). windows_vk is
// CEF's windows_key_code (all platforms, ignored by CEF on macOS);
// native_code is the platform key code (GLFW scancode, or 0 for an
// unpaired char). `character`/`unmodified_character` are the same value --
// the translator never produces a CHAR intent whose unmodified differs
// from its character. glfw_mods are GLFW_MOD_* bits. No-op with no browser.
void send_key_intent(int type, int windows_vk, int native_code,
                      char16_t character, char16_t unmodified_character,
                      int glfw_mods);

// Run an edit command on the focused frame: 1 SelectAll, 2 Copy, 3 Paste,
// 4 Cut, 5 Undo, 6 Redo (renderer::EditCommand's values). No-op with no
// browser or an unknown value.
void edit_command(int cmd);

// JS→C++ event channel. The handler is invoked with the event name
// when JS navigates to dauntless://event/<name>. The intercept lives
// in CefRequestHandler::OnBeforeBrowse — fire-and-forget, no return
// value, no response payload back to JS. Pass an empty function to
// disable.
void set_event_handler(std::function<void(const std::string&)> handler);

// Load-end handler injection. Invoked once when the main frame finishes
// loading index.html (or after Cmd+R reload). Used by the panel layer
// to invalidate per-tick snapshot caches so the first post-load tick
// re-emits state. Pass an empty function to disable.
void set_load_end_handler(std::function<void()> handler);

// Called (main thread) whenever the page that might hold a focused text field
// goes away: main-frame load start (reload / navigation) and renderer-process
// termination. The host wires it to Window::set_key_capture(false). Stored in
// the lifecycle, not on the client, so it can be installed before
// initialize().
void set_capture_reset_handler(std::function<void()> handler);
// Invoke the handler if one is installed. Used by DauntlessCefClient.
void fire_capture_reset();

// Called before window/GL teardown. Releases the browser and CEF.
void shutdown();

}  // namespace dauntless::ui_cef
