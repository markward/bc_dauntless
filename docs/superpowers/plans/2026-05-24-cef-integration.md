# CEF Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed CEF into the canonical `build/dauntless` binary as a transparent full-window overlay that displays "Hello world" in white Antonio over the 3D scene, without regressing existing rendering or input.

**Architecture:** Single binary with multi-role argv dispatch via `CefExecuteProcess`. OSR (off-screen rendering) browser using CPU bitmap → GL texture upload. Single-threaded CEF message pump called once per frame. CEF receives no input events; game keys (WASD/0–9/R/SPACE) keep their existing GLFW path. F12 opens DevTools; Cmd+R reloads the HTML.

**Tech Stack:** C++20, CMake `FetchContent` for CEF, pinned Chromium 144 build (`cef_binary_144.0.25+g27ce504+chromium-144.0.7559.250`), GLFW + glad (existing), pybind11 (existing), Antonio font (OFL, shipped locally).

**Spec:** `docs/superpowers/specs/2026-05-24-cef-integration-design.md`
**Reference code (read-only):** `.claude/worktrees/sdk-ui-shim/native/src/ui_cef/` and `.claude/worktrees/sdk-ui-shim/native/CMakeLists.txt`.

---

## File structure (decisions locked in here)

**New files:**
- `native/src/ui_cef/CMakeLists.txt` — STATIC library wiring + CEF include paths
- `native/src/ui_cef/cef_app.{h,cc}` — `CefApp` impl; lockdown switches in `OnBeforeCommandLineProcessing`
- `native/src/ui_cef/cef_client.{h,cc}` — `CefClient` + `CefRenderHandler::OnPaint`; owns last-paint bitmap
- `native/src/ui_cef/cef_composite_pass.{h,cc}` — GL texture upload + fullscreen-triangle blit with state save/restore
- `native/src/ui_cef/cef_lifecycle.{h,cc}` — process-wide singleton glue: `dispatch_subprocess`, `initialize`, `pump`, `composite`, `shutdown`, `toggle_devtools`, `reload`
- `native/assets/ui-cef/hello.html` — `<div class="hello">Hello world</div>` markup
- `native/assets/ui-cef/css/hello.css` — `@font-face` + top-left positioning + white text + transparent body
- `native/assets/ui-cef/fonts/Antonio-Regular.woff2` — fetched from Google Fonts during setup; checked into the repo (it's ~30 KB)
- `native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt` — OFL licence text shipped with the font

**Modified files:**
- `native/CMakeLists.txt` — add `option(DAUNTLESS_ENABLE_CEF "" ON)`, per-platform URL table, `FetchContent` block, `libcef_dll_wrapper` STATIC subdirectory with `BUILD_SHARED_LIBS` save/restore, and conditional `add_subdirectory(src/ui_cef)`
- `native/src/host/CMakeLists.txt` — link `dauntless` and `_dauntless_host` against `ui_cef`; add POST_BUILD framework symlink/copy step (platform-branched)
- `native/src/host/host_main.cc` — early `CefExecuteProcess` dispatch; ensure subprocess return-codes propagate before any Python init
- `native/src/host/host_bindings.cc` — add `cef_initialize(width, height, html_path)`, `cef_shutdown()`, `cef_pump()`, `cef_composite()`, `cef_toggle_devtools()`, `cef_reload()` bindings
- `engine/renderer.py` — thin re-exports for the six new bindings
- `engine/host_loop.py` — call `cef_initialize` after `init(...)`, `cef_pump` + `cef_composite` per tick, `cef_shutdown` on exit; F12 → toggle DevTools, Cmd+R → reload
- `THIRD_PARTY_NOTICES.md` — add CEF (BSD 3-clause) and Antonio (OFL) sections

**Why this split:** `cef_lifecycle.{h,cc}` is the single integration point between the host binary and CEF; `cef_app`/`cef_client`/`cef_composite_pass` are CEF-callback implementations isolated by responsibility. Host bindings only call into `cef_lifecycle` — they never touch `CefRefPtr`. That isolation matters because `host_bindings.cc` is compiled into both the `_dauntless_host` Python extension (no `dauntless` binary needed) and the `dauntless` executable; bindings that touch CEF symbols would force the extension to depend on libcef too.

---

## Task 1: CMake `DAUNTLESS_ENABLE_CEF` option + `FetchContent` for CEF

**Files:**
- Modify: `native/CMakeLists.txt` (after the existing `option(DAUNTLESS_BUILD_TESTS ...)` line, before `add_subdirectory(src/nif)`)

- [ ] **Step 1: Add the option and FetchContent block**

Insert this block at the marked location:

```cmake
option(DAUNTLESS_ENABLE_CEF "Build with CEF-backed UI overlay" ON)

if(DAUNTLESS_ENABLE_CEF)
    include(FetchContent)

    # Per-platform CEF tarball selection. Spotify's CDN hosts the Minimal
    # distribution. Version pinned: bumping is a deliberate, separate task.
    # Only macosarm64's SHA256 is filled in — Windows/Linux SHA256s must be
    # added when those platforms are first validated (see spec §11).
    set(CEF_VERSION "144.0.25+g27ce504+chromium-144.0.7559.250")
    if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
        set(CEF_PLATFORM "macosarm64")
        set(CEF_SHA256 "541a2e38234ef0c99e40e7f6fc8e895be6dde8293b84c7d0490897eb54062ece")
    elseif(APPLE)
        set(CEF_PLATFORM "macosx64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Intel macOS
    elseif(WIN32)
        set(CEF_PLATFORM "windows64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Windows
    elseif(UNIX)
        set(CEF_PLATFORM "linux64")
        set(CEF_SHA256 "")  # TODO(plan-followup): fill when validating on Linux
    else()
        message(FATAL_ERROR "DAUNTLESS_ENABLE_CEF: unsupported platform")
    endif()

    # URL-encode the '+' characters in the version string (Spotify CDN serves
    # the file by its literal name on disk, which uses '+').
    string(REPLACE "+" "%2B" CEF_VERSION_URL "${CEF_VERSION}")
    set(CEF_URL "https://cef-builds.spotifycdn.com/cef_binary_${CEF_VERSION_URL}_${CEF_PLATFORM}_minimal.tar.bz2")

    if(CEF_SHA256)
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            URL_HASH SHA256=${CEF_SHA256}
            SOURCE_SUBDIR cmake  # skip the CEF SDK's sample-driver CMakeLists
        )
    else()
        message(WARNING "DAUNTLESS_ENABLE_CEF: no SHA256 pinned for ${CEF_PLATFORM} — integrity check skipped")
        FetchContent_Declare(cef
            URL "${CEF_URL}"
            SOURCE_SUBDIR cmake
        )
    endif()
    FetchContent_MakeAvailable(cef)

    set(CEF_ROOT "${cef_SOURCE_DIR}" CACHE INTERNAL "")
    list(APPEND CMAKE_MODULE_PATH "${CEF_ROOT}/cmake")
    find_package(CEF REQUIRED)
endif()
```

Why each piece exists (write these as inline comments where they're not obvious):
- `SOURCE_SUBDIR cmake` points FetchContent at a subdir with no CMakeLists, so `FetchContent_MakeAvailable` populates the archive without running CEF's sample driver (which defines `libcef_dll_wrapper` itself; we want to define it explicitly below in Task 2).
- The `string(REPLACE "+" "%2B" ...)` is required because the literal `+` in the version breaks the URL.

- [ ] **Step 2: Configure the build and confirm download succeeds**

Run from project root:

```bash
cmake -B build -S . -DDAUNTLESS_ENABLE_CEF=ON
```

Expected output (excerpt): a `-- Downloading...` line followed by `-- Extracting...`, then `-- Found CEF ...`. The configure must complete without errors. The first run takes minutes because the tarball is ~300 MB; subsequent runs use the FetchContent cache under `build/_deps/cef-src/`.

Verify the cache exists:

```bash
ls build/_deps/cef-src/cmake/cef_variables.cmake
```

Expected: file exists.

- [ ] **Step 3: Confirm build still passes with CEF disabled**

```bash
cmake -B build-nocef -S . -DDAUNTLESS_ENABLE_CEF=OFF
cmake --build build-nocef --target dauntless -j
```

Expected: clean build of the existing `dauntless` binary; no CEF symbols referenced.

Verify:
```bash
./build-nocef/dauntless --smoke-check
```
Expected: prints the same smoke-check output as today's `main`.

Then remove the temporary build tree to avoid clutter:
```bash
rm -rf build-nocef
```

- [ ] **Step 4: Commit**

```bash
git add native/CMakeLists.txt
git commit -m "build: add DAUNTLESS_ENABLE_CEF option + CEF FetchContent block"
```

---

## Task 2: Build `libcef_dll_wrapper` STATIC

**Files:**
- Modify: `native/CMakeLists.txt` (immediately after the `find_package(CEF REQUIRED)` line added in Task 1)

- [ ] **Step 1: Add the wrapper subdirectory with `BUILD_SHARED_LIBS` save/restore**

Insert before `endif()` of the `if(DAUNTLESS_ENABLE_CEF)` block:

```cmake
    # CEF ships libcef_dll/ as source; consumers must compile it into their
    # project. Force STATIC: CEF's add_library() honors BUILD_SHARED_LIBS,
    # which openal-soft turns ON globally. Combined with CEF's
    # -fvisibility=hidden flags that would hide every wrapper symbol
    # (CefExecuteProcess, CefInitialize, ...) and downstream linking fails
    # with "undefined symbol". Static sidesteps visibility entirely.
    set(_dauntless_saved_BUILD_SHARED_LIBS ${BUILD_SHARED_LIBS})
    set(BUILD_SHARED_LIBS OFF)
    add_subdirectory("${CEF_ROOT}/libcef_dll" libcef_dll_wrapper)
    set(BUILD_SHARED_LIBS ${_dauntless_saved_BUILD_SHARED_LIBS})

    # Project-wide -Wpedantic collides with CEF's -Werror inside
    # libcef_dll_wrapper (CEF's logging headers use GNU token-pasting via
    # `, ##__VA_ARGS__`). Suppress only that warning on the wrapper.
    if(TARGET libcef_dll_wrapper)
        target_compile_options(libcef_dll_wrapper PRIVATE
            -Wno-gnu-zero-variadic-macro-arguments)
    endif()

    message(STATUS "CEF SDK at: ${CEF_ROOT}")
    message(STATUS "CEF version: ${CEF_VERSION}")
```

- [ ] **Step 2: Reconfigure and build the wrapper target**

```bash
cmake -B build -S .
cmake --build build --target libcef_dll_wrapper -j
```

Expected: the wrapper compiles cleanly; the build emits `libcef_dll_wrapper.a` under `build/libcef_dll_wrapper/` (or similar path — exact filename varies by CMake version, but it's a static archive).

Verify the archive contains expected symbols:

```bash
nm build/libcef_dll_wrapper/liblibcef_dll_wrapper.a 2>/dev/null | grep -c "CefExecuteProcess\|CefInitialize"
```

Expected: a positive count (typically several hits across translation units).

- [ ] **Step 3: Commit**

```bash
git add native/CMakeLists.txt
git commit -m "build: compile libcef_dll_wrapper STATIC for dauntless"
```

---

## Task 3: `ui_cef` library skeleton — empty translation units that link

**Files:**
- Create: `native/src/ui_cef/CMakeLists.txt`
- Create: `native/src/ui_cef/cef_lifecycle.h`
- Create: `native/src/ui_cef/cef_lifecycle.cc`
- Modify: `native/CMakeLists.txt` (add the `add_subdirectory(src/ui_cef)` call)

- [ ] **Step 1: Create the library CMake**

`native/src/ui_cef/CMakeLists.txt`:

```cmake
# ui_cef — CEF-backed UI overlay (transparent browser composited over the
# 3D scene). Linked into both dauntless and _dauntless_host.

if(NOT DAUNTLESS_ENABLE_CEF)
    return()
endif()

add_library(ui_cef STATIC
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
```

- [ ] **Step 2: Create the lifecycle header**

`native/src/ui_cef/cef_lifecycle.h`:

```cpp
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
```

- [ ] **Step 3: Create the lifecycle source stub**

`native/src/ui_cef/cef_lifecycle.cc` (real bodies come in Tasks 4–8; here we just need it to compile):

```cpp
// native/src/ui_cef/cef_lifecycle.cc
#include "cef_lifecycle.h"

namespace dauntless::ui_cef {

int  dispatch_subprocess(int /*argc*/, char* /*argv*/[])  { return -1; }
bool initialize(int, int, const std::string&)             { return false; }
void pump()                                                {}
void composite()                                           {}
void toggle_devtools()                                     {}
void reload()                                              {}
void shutdown()                                            {}

}  // namespace dauntless::ui_cef
```

- [ ] **Step 4: Wire the library into the top-level CMake**

In `native/CMakeLists.txt`, after `add_subdirectory(src/host)` add:

```cmake
if(DAUNTLESS_ENABLE_CEF)
    add_subdirectory(src/ui_cef)
endif()
```

The order matters because `src/host` consumes `ui_cef` (Task 7); CMake handles late targets via target name resolution, but explicit ordering avoids ambiguity.

- [ ] **Step 5: Build the new library**

```bash
cmake --build build --target ui_cef -j
```

Expected: clean build; `ui_cef.a` produced under `build/native/src/ui_cef/` (path depends on CMake's directory mapping — verify with `find build -name 'libui_cef*.a'`).

- [ ] **Step 6: Commit**

```bash
git add native/src/ui_cef/CMakeLists.txt \
        native/src/ui_cef/cef_lifecycle.{h,cc} \
        native/CMakeLists.txt
git commit -m "build: scaffold ui_cef library with stub lifecycle entry points"
```

---

## Task 4: `CefApp` with lockdown switches (Keychain, Notifications, GPU)

**Files:**
- Create: `native/src/ui_cef/cef_app.h`
- Create: `native/src/ui_cef/cef_app.cc`
- Modify: `native/src/ui_cef/CMakeLists.txt` (add `cef_app.cc` to the library sources)

- [ ] **Step 1: Create the CefApp header**

`native/src/ui_cef/cef_app.h`:

```cpp
// native/src/ui_cef/cef_app.h
//
// CefApp implementation: applies process-wide Chromium command-line
// switches via OnBeforeCommandLineProcessing. These switches MUST hit
// the browser process — without them macOS shows a Keychain password
// prompt and a Notifications permission prompt at every launch.

#pragma once

#include "include/cef_app.h"

namespace dauntless::ui_cef {

class DauntlessCefApp : public CefApp, public CefBrowserProcessHandler {
public:
    DauntlessCefApp() = default;

    CefRefPtr<CefBrowserProcessHandler> GetBrowserProcessHandler() override {
        return this;
    }

    void OnBeforeCommandLineProcessing(
        const CefString& process_type,
        CefRefPtr<CefCommandLine> command_line) override;

private:
    IMPLEMENT_REFCOUNTING(DauntlessCefApp);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefApp);
};

}  // namespace dauntless::ui_cef
```

- [ ] **Step 2: Create the CefApp source**

`native/src/ui_cef/cef_app.cc`:

```cpp
// native/src/ui_cef/cef_app.cc
#include "cef_app.h"

namespace dauntless::ui_cef {

void DauntlessCefApp::OnBeforeCommandLineProcessing(
    const CefString& process_type,
    CefRefPtr<CefCommandLine> command_line) {
    // Apply lockdown only in the browser process. Helpers inherit a copy
    // of these via CEF's internal command-line propagation.
    if (!process_type.empty()) return;

    // Force software GPU inside CEF's GPU process. CEF's GPU process
    // would otherwise conflict with our GLFW-managed OpenGL context
    // (shared IOSurface allocations on macOS in particular).
    command_line->AppendSwitch("disable-gpu");
    command_line->AppendSwitch("disable-gpu-compositing");

    // Stops the macOS Keychain "Chromium Safe Storage" password prompt.
    // We do not persist user data, so a plaintext backend + mock keychain
    // are appropriate.
    command_line->AppendSwitchWithValue("password-store", "basic");
    command_line->AppendSwitch("use-mock-keychain");

    // Stops the macOS Notifications permission prompt. The HTML5
    // `--disable-notifications` switch alone leaves macOS's NATIVE
    // NSUserNotificationCenter registration active, which is what
    // actually triggers the OS permission dialog. Both are required.
    command_line->AppendSwitch("disable-notifications");
    command_line->AppendSwitchWithValue(
        "disable-features",
        "NativeNotifications,SystemNotifications,UNNotifications");
}

}  // namespace dauntless::ui_cef
```

- [ ] **Step 3: Add to the library**

Edit `native/src/ui_cef/CMakeLists.txt` — add `cef_app.cc` to the `add_library` sources:

```cmake
add_library(ui_cef STATIC
    cef_app.cc
    cef_lifecycle.cc
)
```

- [ ] **Step 4: Build**

```bash
cmake --build build --target ui_cef -j
```

Expected: clean build; no warnings about token-pasting.

- [ ] **Step 5: Commit**

```bash
git add native/src/ui_cef/cef_app.{h,cc} native/src/ui_cef/CMakeLists.txt
git commit -m "ui_cef: add CefApp with Keychain + Notifications + GPU lockdowns"
```

---

## Task 5: `CefClient` + `CefRenderHandler` (OnPaint capture)

**Files:**
- Create: `native/src/ui_cef/cef_client.h`
- Create: `native/src/ui_cef/cef_client.cc`
- Modify: `native/src/ui_cef/CMakeLists.txt`

- [ ] **Step 1: Create the client header**

`native/src/ui_cef/cef_client.h`:

```cpp
// native/src/ui_cef/cef_client.h
//
// CefClient + CefRenderHandler. CEF calls OnPaint each time the browser
// produces a new bitmap; we cache it for the next composite. CEF runs in
// single-threaded message-loop mode (see cef_lifecycle.cc), so OnPaint
// arrives on the main thread between pump() and composite() — no mutex.

#pragma once

#include "include/cef_client.h"
#include "include/cef_render_handler.h"

#include <cstdint>
#include <vector>

namespace dauntless::ui_cef {

class DauntlessCefClient : public CefClient,
                           public CefRenderHandler,
                           public CefLifeSpanHandler {
public:
    DauntlessCefClient(int view_width, int view_height);

    // CefClient
    CefRefPtr<CefRenderHandler>   GetRenderHandler()   override { return this; }
    CefRefPtr<CefLifeSpanHandler> GetLifeSpanHandler() override { return this; }

    // CefRenderHandler
    void GetViewRect(CefRefPtr<CefBrowser> browser, CefRect& rect) override;
    void OnPaint(CefRefPtr<CefBrowser> browser,
                 PaintElementType type,
                 const RectList& dirtyRects,
                 const void* buffer,
                 int width, int height) override;

    // CefLifeSpanHandler — stores the browser handle for toggle_devtools / reload.
    void OnAfterCreated(CefRefPtr<CefBrowser> browser) override;
    void OnBeforeClose(CefRefPtr<CefBrowser> browser) override;

    // Returns nullptr if no bitmap has arrived yet.
    const std::uint8_t* latest_bitmap(int* out_width, int* out_height) const;

    CefRefPtr<CefBrowser> browser() const { return browser_; }

private:
    int view_width_;
    int view_height_;

    std::vector<std::uint8_t> bitmap_;
    int bitmap_width_  = 0;
    int bitmap_height_ = 0;
    bool ready_ = false;

    CefRefPtr<CefBrowser> browser_;

    IMPLEMENT_REFCOUNTING(DauntlessCefClient);
    DISALLOW_COPY_AND_ASSIGN(DauntlessCefClient);
};

}  // namespace dauntless::ui_cef
```

- [ ] **Step 2: Create the client source**

`native/src/ui_cef/cef_client.cc`:

```cpp
// native/src/ui_cef/cef_client.cc
#include "cef_client.h"

#include <cstdio>
#include <cstring>

namespace dauntless::ui_cef {

DauntlessCefClient::DauntlessCefClient(int view_width, int view_height)
    : view_width_(view_width), view_height_(view_height) {}

void DauntlessCefClient::GetViewRect(CefRefPtr<CefBrowser> /*browser*/,
                                      CefRect& rect) {
    rect = CefRect(0, 0, view_width_, view_height_);
}

void DauntlessCefClient::OnPaint(CefRefPtr<CefBrowser> /*browser*/,
                                  PaintElementType type,
                                  const RectList& /*dirtyRects*/,
                                  const void* buffer,
                                  int width, int height) {
    if (type != PET_VIEW) return;
    const size_t bytes = static_cast<size_t>(width) * height * 4;
    if (bitmap_.size() != bytes) bitmap_.resize(bytes);
    std::memcpy(bitmap_.data(), buffer, bytes);
    bitmap_width_  = width;
    bitmap_height_ = height;
    if (!ready_) {
        ready_ = true;
        std::printf("[cef] first OnPaint: %dx%d\n", width, height);
    }
}

void DauntlessCefClient::OnAfterCreated(CefRefPtr<CefBrowser> browser) {
    browser_ = browser;
}

void DauntlessCefClient::OnBeforeClose(CefRefPtr<CefBrowser> /*browser*/) {
    browser_ = nullptr;
}

const std::uint8_t* DauntlessCefClient::latest_bitmap(int* out_width,
                                                       int* out_height) const {
    if (!ready_) return nullptr;
    *out_width  = bitmap_width_;
    *out_height = bitmap_height_;
    return bitmap_.data();
}

}  // namespace dauntless::ui_cef
```

- [ ] **Step 3: Add to library and build**

Edit `native/src/ui_cef/CMakeLists.txt` to add `cef_client.cc`:

```cmake
add_library(ui_cef STATIC
    cef_app.cc
    cef_client.cc
    cef_lifecycle.cc
)
```

```bash
cmake --build build --target ui_cef -j
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add native/src/ui_cef/cef_client.{h,cc} native/src/ui_cef/CMakeLists.txt
git commit -m "ui_cef: add CefClient with OSR OnPaint capture"
```

---

## Task 6: `CefCompositePass` — GL texture upload + premultiplied-alpha blit

**Files:**
- Create: `native/src/ui_cef/cef_composite_pass.h`
- Create: `native/src/ui_cef/cef_composite_pass.cc`
- Modify: `native/src/ui_cef/CMakeLists.txt`

- [ ] **Step 1: Create the header**

`native/src/ui_cef/cef_composite_pass.h`:

```cpp
// native/src/ui_cef/cef_composite_pass.h
//
// Uploads the latest CEF OSR bitmap to a GL texture and draws it as a
// fullscreen triangle over the 3D scene with premultiplied-alpha blend.
// Saves and restores GL state (cull / depth / blend / scissor) so the
// next frame's 3D passes resume from the state they left in.

#pragma once

#include <cstdint>

namespace dauntless::ui_cef {

class CefCompositePass {
public:
    CefCompositePass();
    ~CefCompositePass();

    CefCompositePass(const CefCompositePass&) = delete;
    CefCompositePass& operator=(const CefCompositePass&) = delete;

    // pixels is BGRA8 premultiplied (CEF OSR contract). No-op if pixels==nullptr.
    void draw_fullscreen(const std::uint8_t* pixels, int width, int height);

private:
    unsigned int program_id_ = 0;
    unsigned int vao_        = 0;
    unsigned int vbo_        = 0;
    unsigned int tex_id_     = 0;
    int last_width_  = 0;
    int last_height_ = 0;
};

}  // namespace dauntless::ui_cef
```

- [ ] **Step 2: Create the source**

`native/src/ui_cef/cef_composite_pass.cc`:

```cpp
// native/src/ui_cef/cef_composite_pass.cc
#include "cef_composite_pass.h"

#include <glad/glad.h>

#include <cstdio>
#include <cstdlib>

namespace dauntless::ui_cef {

namespace {

const char* kVS = R"(
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    v_uv.y = 1.0 - v_uv.y;  // GL bottom-up; CEF bitmap top-down
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
)";

const char* kFS = R"(
#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_tex;
void main() { frag_color = texture(u_tex, v_uv); }
)";

unsigned int compile(unsigned int type, const char* src) {
    unsigned int sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, nullptr);
    glCompileShader(sh);
    int ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetShaderInfoLog(sh, sizeof(log), nullptr, log);
        std::fprintf(stderr, "ui_cef shader compile failed: %s\n", log);
        std::exit(1);
    }
    return sh;
}

unsigned int link(unsigned int vs, unsigned int fs) {
    unsigned int p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    int ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[1024] = {0};
        glGetProgramInfoLog(p, sizeof(log), nullptr, log);
        std::fprintf(stderr, "ui_cef program link failed: %s\n", log);
        std::exit(1);
    }
    return p;
}

}  // namespace

CefCompositePass::CefCompositePass() {
    unsigned int vs = compile(GL_VERTEX_SHADER,   kVS);
    unsigned int fs = compile(GL_FRAGMENT_SHADER, kFS);
    program_id_ = link(vs, fs);
    glDeleteShader(vs); glDeleteShader(fs);

    // Fullscreen-triangle trick: one triangle covering [-1,3]² clipspace.
    const float verts[] = { -1.0f, -1.0f,   3.0f, -1.0f,   -1.0f,  3.0f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);

    glGenTextures(1, &tex_id_);
    glBindTexture(GL_TEXTURE_2D, tex_id_);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
}

CefCompositePass::~CefCompositePass() {
    if (tex_id_)     glDeleteTextures(1, &tex_id_);
    if (vbo_)        glDeleteBuffers(1,  &vbo_);
    if (vao_)        glDeleteVertexArrays(1, &vao_);
    if (program_id_) glDeleteProgram(program_id_);
}

void CefCompositePass::draw_fullscreen(const std::uint8_t* pixels,
                                       int width, int height) {
    if (!pixels) return;

    glBindTexture(GL_TEXTURE_2D, tex_id_);

    // CEF delivers tight rows; GL's default UNPACK_ALIGNMENT is 4 bytes.
    // Force tight unpack so odd widths never misalign.
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

    if (width != last_width_ || height != last_height_) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                     GL_BGRA, GL_UNSIGNED_BYTE, pixels);
        last_width_ = width;
        last_height_ = height;
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height,
                        GL_BGRA, GL_UNSIGNED_BYTE, pixels);
    }

    glUseProgram(program_id_);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex_id_);
    glUniform1i(glGetUniformLocation(program_id_, "u_tex"), 0);

    // Save state we are about to clobber so the next frame's 3D passes
    // see the same GL config they had before the composite ran.
    const GLboolean prev_cull       = glIsEnabled(GL_CULL_FACE);
    const GLboolean prev_scissor    = glIsEnabled(GL_SCISSOR_TEST);
    const GLboolean prev_depth_test = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend      = glIsEnabled(GL_BLEND);
    GLint prev_blend_src = 0, prev_blend_dst = 0;
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &prev_blend_src);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &prev_blend_dst);

    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glEnable(GL_BLEND);
    // CEF delivers PREMULTIPLIED-alpha BGRA. The correct blend is
    // (ONE, ONE_MINUS_SRC_ALPHA). Using straight alpha would
    // double-attenuate by alpha and leave the overlay invisible.
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    // Restore everything.
    glDepthMask(GL_TRUE);
    if (prev_cull)       glEnable(GL_CULL_FACE);
    if (prev_scissor)    glEnable(GL_SCISSOR_TEST);
    if (prev_depth_test) glEnable(GL_DEPTH_TEST);
    if (!prev_blend)     glDisable(GL_BLEND);
    glBlendFunc(static_cast<GLenum>(prev_blend_src),
                static_cast<GLenum>(prev_blend_dst));
}

}  // namespace dauntless::ui_cef
```

- [ ] **Step 3: Add to library and build**

Edit `native/src/ui_cef/CMakeLists.txt` sources list:

```cmake
add_library(ui_cef STATIC
    cef_app.cc
    cef_client.cc
    cef_composite_pass.cc
    cef_lifecycle.cc
)
```

```bash
cmake --build build --target ui_cef -j
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add native/src/ui_cef/cef_composite_pass.{h,cc} native/src/ui_cef/CMakeLists.txt
git commit -m "ui_cef: add GL composite pass with premultiplied-alpha blend"
```

---

## Task 7: Implement `cef_lifecycle.cc` (real bodies)

**Files:**
- Modify: `native/src/ui_cef/cef_lifecycle.cc` (replace the stub with real implementation)

- [ ] **Step 1: Replace the stub body**

`native/src/ui_cef/cef_lifecycle.cc`:

```cpp
// native/src/ui_cef/cef_lifecycle.cc
#include "cef_lifecycle.h"

#include "cef_app.h"
#include "cef_client.h"
#include "cef_composite_pass.h"

#include "include/cef_app.h"
#include "include/cef_browser.h"
#include "include/cef_browser_process_handler.h"
#include "include/wrapper/cef_library_loader.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <string>

namespace dauntless::ui_cef {

namespace {

// CEF lifetime is process-wide; these statics are intentionally never
// destroyed (CEF expects to outlive normal C++ destructors).
int                                       g_saved_argc = 0;
char**                                    g_saved_argv = nullptr;
std::unique_ptr<CefScopedLibraryLoader>   g_library_loader;
CefRefPtr<DauntlessCefApp>                g_app;
CefRefPtr<DauntlessCefClient>             g_client;
std::unique_ptr<CefCompositePass>         g_composite;
bool                                      g_initialized = false;

// On macOS without a .app bundle, CEF's NSBundle-based path discovery
// fails. We must tell CEF where its framework, locales, resources, and
// helper subprocess binary live. Helpers re-use this binary's argv0
// (multi-role dispatch).
#ifdef __APPLE__
std::string framework_dir(const std::string& exec_dir) {
    return exec_dir + "/Frameworks/Chromium Embedded Framework.framework";
}
std::string main_bundle_dir(const std::string& exec_dir) {
    return exec_dir;
}
std::string resources_dir(const std::string& exec_dir) {
    return framework_dir(exec_dir) + "/Resources";
}
std::string locales_dir(const std::string& exec_dir) {
    return resources_dir(exec_dir);
}
#endif

}  // namespace

int dispatch_subprocess(int argc, char* argv[]) {
    g_saved_argc = argc;
    g_saved_argv = argv;

    g_library_loader = std::make_unique<CefScopedLibraryLoader>();
    if (!g_library_loader->LoadInMain()) {
        std::fprintf(stderr,
                     "dauntless: failed to load CEF framework. Ensure "
                     "'Frameworks/Chromium Embedded Framework.framework' "
                     "exists alongside the binary.\n");
        return 1;
    }

    CefMainArgs main_args(argc, argv);
    g_app = new DauntlessCefApp();
    // CefExecuteProcess returns >= 0 for helper roles and -1 for the
    // main browser process. Callers exit with the returned code if it's
    // >= 0, otherwise proceed to initialize().
    return CefExecuteProcess(main_args, g_app, nullptr);
}

bool initialize(int view_width, int view_height,
                const std::string& html_path) {
    if (g_initialized) return true;
    if (!g_app) {
        std::fprintf(stderr, "ui_cef: dispatch_subprocess must run first\n");
        return false;
    }

    CefMainArgs main_args(g_saved_argc, g_saved_argv);

    CefSettings settings;
    settings.no_sandbox                  = true;
    settings.windowless_rendering_enabled = true;
    settings.external_message_pump       = false;
    settings.multi_threaded_message_loop = false;
    settings.command_line_args_disabled  = true;

#ifdef __APPLE__
    // No .app bundle: tell CEF where everything lives.
    const std::filesystem::path exec_path = g_saved_argc > 0
        ? std::filesystem::canonical(g_saved_argv[0])
        : std::filesystem::current_path();
    const std::string exec_dir = exec_path.parent_path().string();

    CefString(&settings.framework_dir_path)     = framework_dir(exec_dir);
    CefString(&settings.main_bundle_path)       = main_bundle_dir(exec_dir);
    CefString(&settings.resources_dir_path)     = resources_dir(exec_dir);
    CefString(&settings.locales_dir_path)       = locales_dir(exec_dir);
    CefString(&settings.browser_subprocess_path) =
        g_saved_argc > 0 ? std::filesystem::canonical(g_saved_argv[0]).string() : "";
#endif

    if (!CefInitialize(main_args, settings, g_app, nullptr)) {
        std::fprintf(stderr, "ui_cef: CefInitialize failed\n");
        return false;
    }

    g_client = new DauntlessCefClient(view_width, view_height);

    CefWindowInfo window_info;
    window_info.SetAsWindowless(0);  // OSR; no parent

    CefBrowserSettings browser_settings;
    browser_settings.windowless_frame_rate = 60;
    // Transparent backdrop so the 3D scene shows through everywhere the
    // page is not painted.
    browser_settings.background_color = 0x00000000;

    const std::string url = std::string("file://") +
        std::filesystem::canonical(html_path).string();

    CefBrowserHost::CreateBrowser(window_info, g_client, url,
                                  browser_settings, nullptr, nullptr);

    g_composite = std::make_unique<CefCompositePass>();
    g_initialized = true;
    return true;
}

void pump() {
    if (!g_initialized) return;
    CefDoMessageLoopWork();
    // Force the OSR browser to repaint on every pump. Without this, CEF
    // sometimes skips OnPaint after JS-driven DOM mutation on macOS in
    // --disable-gpu mode.
    if (g_client && g_client->browser()) {
        auto host = g_client->browser()->GetHost();
        if (host) host->Invalidate(PET_VIEW);
    }
}

void composite() {
    if (!g_initialized || !g_client || !g_composite) return;
    int w = 0, h = 0;
    const std::uint8_t* pixels = g_client->latest_bitmap(&w, &h);
    g_composite->draw_fullscreen(pixels, w, h);
}

void toggle_devtools() {
    if (!g_client || !g_client->browser()) return;
    auto host = g_client->browser()->GetHost();
    if (!host) return;
    if (host->HasDevTools()) {
        host->CloseDevTools();
    } else {
        CefWindowInfo info;
        // DevTools opens in a native OS window — managed by CEF, not by us.
        host->ShowDevTools(info, g_client, CefBrowserSettings(), CefPoint());
    }
}

void reload() {
    if (g_client && g_client->browser()) g_client->browser()->Reload();
}

void shutdown() {
    if (!g_initialized) return;
    g_composite.reset();  // releases GL handles while GL context is alive
    g_client = nullptr;
    if (g_client) {
        // Defensive — should be nulled by OnBeforeClose. CEF will close
        // the browser as part of CefShutdown.
    }
    CefShutdown();
    g_app = nullptr;
    g_initialized = false;
}

}  // namespace dauntless::ui_cef
```

- [ ] **Step 2: Build the library**

```bash
cmake --build build --target ui_cef -j
```

Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add native/src/ui_cef/cef_lifecycle.cc
git commit -m "ui_cef: implement lifecycle (init, pump, composite, devtools, reload)"
```

---

## Task 8: Wire `ui_cef` into `dauntless` (link + framework symlink)

**Files:**
- Modify: `native/src/host/CMakeLists.txt`

- [ ] **Step 1: Link `ui_cef` into both targets**

Append `ui_cef` to the link lines for both `_dauntless_host` and `dauntless`. Use a conditional so the build still works with `DAUNTLESS_ENABLE_CEF=OFF`:

```cmake
if(DAUNTLESS_ENABLE_CEF)
    target_link_libraries(_dauntless_host PRIVATE ui_cef)
    target_link_libraries(dauntless       PRIVATE ui_cef)
endif()
```

Add this block immediately after the existing `target_link_libraries(...)` calls (the ones that already link `renderer scenegraph assets dauntless_audio`).

**IMPORTANT:** do NOT call `SET_EXECUTABLE_TARGET_PROPERTIES(dauntless)`. That CEF macro applies `-fno-rtti`, which breaks pybind11 (typeid usage in its headers). `dauntless` compiles with the project's normal flags; only `ui_cef` (a STATIC library with no pybind11 contact) needs CEF-include suppression.

- [ ] **Step 2: Add POST_BUILD framework symlink (macOS) / copy (Windows, Linux)**

Append to the same `CMakeLists.txt`, after the existing POST_BUILD region:

```cmake
if(DAUNTLESS_ENABLE_CEF)
    if(APPLE)
        # CefScopedLibraryLoader::LoadInMain() resolves the framework at
        # <exec-dir>/Frameworks/Chromium Embedded Framework.framework.
        # Create that path via symlink for fast incremental rebuilds.
        add_custom_command(TARGET dauntless POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E make_directory
                "${CMAKE_BINARY_DIR}/Frameworks"
            COMMAND ${CMAKE_COMMAND} -E create_symlink
                "${CEF_ROOT}/Release/Chromium Embedded Framework.framework"
                "${CMAKE_BINARY_DIR}/Frameworks/Chromium Embedded Framework.framework"
            COMMENT "Symlinking CEF framework into build/Frameworks/"
            VERBATIM
        )
    elseif(WIN32)
        # Windows: CEF ships .dll files in Release/. Copy alongside the
        # executable so LoadLibrary finds them at runtime.
        add_custom_command(TARGET dauntless POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_directory
                "${CEF_ROOT}/Release"
                "${CMAKE_BINARY_DIR}"
            COMMENT "Copying CEF runtime DLLs alongside dauntless.exe"
            VERBATIM
        )
    elseif(UNIX)
        # Linux: CEF ships libcef.so + ICU + locale paks in Release/. Copy.
        add_custom_command(TARGET dauntless POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_directory
                "${CEF_ROOT}/Release"
                "${CMAKE_BINARY_DIR}"
            COMMENT "Copying CEF runtime files alongside dauntless"
            VERBATIM
        )
    endif()
endif()
```

- [ ] **Step 3: Configure and build dauntless**

```bash
cmake -B build -S .
cmake --build build --target dauntless -j
```

Expected: clean build. May produce a substantial number of CEF/Chromium link symbols on first pass; should finish without errors.

Verify the framework symlink exists:

```bash
ls -la "build/Frameworks/Chromium Embedded Framework.framework"
```

Expected: symlink pointing into `build/_deps/cef-src/Release/...`.

- [ ] **Step 4: Verify dauntless still smoke-checks (CEF not yet wired)**

```bash
./build/dauntless --smoke-check
```

Expected: same smoke-check output as today's main. The CEF code is linked but not yet called from `host_main`, so behaviour is unchanged.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/CMakeLists.txt
git commit -m "build: link ui_cef into dauntless + symlink CEF framework alongside"
```

---

## Task 9: `CefExecuteProcess` dispatch in `host_main`

**Files:**
- Modify: `native/src/host/host_main.cc`

- [ ] **Step 1: Add the dispatch call**

Add this include near the top of `host_main.cc`, guarded so non-CEF builds still compile:

```cpp
#ifdef DAUNTLESS_ENABLE_CEF
#include "ui_cef/cef_lifecycle.h"
#endif
```

Modify `int main(int argc, char* argv[])` so the **first** non-trivial line is the CEF subprocess dispatch:

```cpp
int main(int argc, char* argv[]) {
    if (argc < 1) return 1;

#ifdef DAUNTLESS_ENABLE_CEF
    // CEF spawns helper subprocesses by re-running this binary. The
    // subprocess role is encoded in argv; CefExecuteProcess detects it
    // and runs the appropriate event loop, returning the exit code we
    // must propagate. A return value of -1 means "main browser process,
    // keep going with normal startup."
    {
        const int subprocess_rc = dauntless::ui_cef::dispatch_subprocess(argc, argv);
        if (subprocess_rc >= 0) return subprocess_rc;
    }
#endif

    auto project_root = discover_project_root(argv[0]);
    configure_python_path(project_root);
    // ... rest of main unchanged
```

The `#ifdef DAUNTLESS_ENABLE_CEF` is a CMake-defined macro. Add it to the `dauntless` target in `native/src/host/CMakeLists.txt`:

```cmake
if(DAUNTLESS_ENABLE_CEF)
    target_compile_definitions(dauntless       PRIVATE DAUNTLESS_ENABLE_CEF=1)
    target_compile_definitions(_dauntless_host PRIVATE DAUNTLESS_ENABLE_CEF=1)
endif()
```

- [ ] **Step 2: Build and verify dispatch is hit only by helpers**

```bash
cmake --build build --target dauntless -j
./build/dauntless --smoke-check
```

Expected: smoke-check output unchanged. `dispatch_subprocess` is called but returns -1 (main browser), so the rest of `main` runs as before.

- [ ] **Step 3: Commit**

```bash
git add native/src/host/host_main.cc native/src/host/CMakeLists.txt
git commit -m "host: dispatch CEF subprocess role from main() before Python init"
```

---

## Task 10: Asset files — `hello.html`, `hello.css`, Antonio woff2

**Files:**
- Create: `native/assets/ui-cef/hello.html`
- Create: `native/assets/ui-cef/css/hello.css`
- Create: `native/assets/ui-cef/fonts/Antonio-Regular.woff2` (binary file)
- Create: `native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`

- [ ] **Step 1: Download Antonio Regular (OFL-licensed)**

```bash
mkdir -p native/assets/ui-cef/fonts native/assets/ui-cef/css native/assets/ui-cef/THIRD_PARTY
curl -sSL -o native/assets/ui-cef/fonts/Antonio-Regular.woff2 \
    https://github.com/google/fonts/raw/main/ofl/antonio/Antonio%5Bwght%5D.ttf
```

Note: Google Fonts ships Antonio as a variable TTF, not woff2. For our use we want the smallest hermetic asset. Convert with `woff2_compress` if available, OR just rename — modern Chromium accepts TTF as well as woff2 under `@font-face`. The simplest path that always works:

```bash
curl -sSL -o native/assets/ui-cef/fonts/Antonio-Regular.ttf \
    "https://github.com/google/fonts/raw/main/ofl/antonio/Antonio%5Bwght%5D.ttf"
```

(Change references in `hello.css` to `.ttf` accordingly.)

Verify file size is non-zero and ~30–80 KB:

```bash
ls -l native/assets/ui-cef/fonts/Antonio-Regular.ttf
```

- [ ] **Step 2: Add the OFL licence text**

`native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`: copy from `https://github.com/google/fonts/raw/main/ofl/antonio/OFL.txt`:

```bash
curl -sSL -o native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt \
    https://github.com/google/fonts/raw/main/ofl/antonio/OFL.txt
```

- [ ] **Step 3: Create `hello.css`**

`native/assets/ui-cef/css/hello.css`:

```css
@font-face {
    font-family: "Antonio";
    src: url("../fonts/Antonio-Regular.ttf") format("truetype");
    font-weight: normal;
    font-style: normal;
}

html, body {
    margin: 0;
    padding: 0;
    color-scheme: dark;
    background: transparent;
}

.hello {
    position: fixed;
    top: 16px;
    left: 16px;
    font-family: "Antonio", sans-serif;
    font-size: 24px;
    color: #ffffff;
    /* Subtle shadow so the text stays legible against bright sky/nebula
       backdrops without needing a panel chrome behind it. */
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}
```

- [ ] **Step 4: Create `hello.html`**

`native/assets/ui-cef/hello.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>dauntless</title>
    <link rel="stylesheet" href="css/hello.css">
</head>
<body>
    <div class="hello">Hello world</div>
</body>
</html>
```

- [ ] **Step 5: Verify the HTML renders correctly in a real browser**

```bash
open native/assets/ui-cef/hello.html
```

Expected: a tiny white "Hello world" in Antonio in the top-left corner of an otherwise transparent (browser-default-white) page.

- [ ] **Step 6: Commit**

```bash
git add native/assets/ui-cef/
git commit -m "assets: ui-cef Hello World HTML/CSS + Antonio font (OFL)"
```

---

## Task 11: Add `cef_*` bindings to `host_bindings.cc`

**Files:**
- Modify: `native/src/host/host_bindings.cc` (add bindings after `m.def("framebuffer_size", ...)`)

- [ ] **Step 1: Add CEF include guarded by macro**

Near the other includes:

```cpp
#ifdef DAUNTLESS_ENABLE_CEF
#include "ui_cef/cef_lifecycle.h"
#endif
```

- [ ] **Step 2: Add six bindings inside the `PYBIND11_MODULE(_dauntless_host, m)` block**

After the existing `m.def("framebuffer_size", ...)` line, add:

```cpp
#ifdef DAUNTLESS_ENABLE_CEF
    m.def("cef_initialize",
          [](int view_width, int view_height, const std::string& html_path) {
              return dauntless::ui_cef::initialize(view_width, view_height, html_path);
          },
          py::arg("view_width"), py::arg("view_height"), py::arg("html_path"),
          "Initialise CEF and create the OSR overlay browser. Returns true on success.");

    m.def("cef_pump",
          []() { dauntless::ui_cef::pump(); },
          "Run one iteration of CEF's message loop. Call once per frame.");

    m.def("cef_composite",
          []() { dauntless::ui_cef::composite(); },
          "Blit the latest CEF bitmap over the current framebuffer.");

    m.def("cef_shutdown",
          []() { dauntless::ui_cef::shutdown(); },
          "Tear down CEF. Call before the GL context is destroyed.");

    m.def("cef_toggle_devtools",
          []() { dauntless::ui_cef::toggle_devtools(); },
          "Open or close the DevTools window for the overlay browser.");

    m.def("cef_reload",
          []() { dauntless::ui_cef::reload(); },
          "Reload the overlay browser's current document.");
#else
    // Stub the bindings out so engine.host_loop can call them
    // unconditionally regardless of build config.
    m.def("cef_initialize",
          [](int, int, const std::string&) { return false; },
          py::arg("view_width"), py::arg("view_height"), py::arg("html_path"));
    m.def("cef_pump",            []() {});
    m.def("cef_composite",       []() {});
    m.def("cef_shutdown",        []() {});
    m.def("cef_toggle_devtools", []() {});
    m.def("cef_reload",          []() {});
#endif
```

- [ ] **Step 3: Build both targets**

```bash
cmake --build build --target dauntless _dauntless_host -j
```

Expected: clean build of both.

- [ ] **Step 4: Smoke-test that the new bindings are callable**

```bash
uv run python -c "
import _dauntless_host as h
print('cef_initialize:',  hasattr(h, 'cef_initialize'))
print('cef_pump:',        hasattr(h, 'cef_pump'))
print('cef_composite:',   hasattr(h, 'cef_composite'))
print('cef_shutdown:',    hasattr(h, 'cef_shutdown'))
print('cef_toggle_devtools:', hasattr(h, 'cef_toggle_devtools'))
print('cef_reload:',      hasattr(h, 'cef_reload'))
"
```

Expected: all six print `True`.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "host: add cef_* bindings (initialize/pump/composite/shutdown/devtools/reload)"
```

---

## Task 12: Add `engine/renderer.py` re-exports

**Files:**
- Modify: `engine/renderer.py`

- [ ] **Step 1: Add typed wrappers after the existing `framebuffer_size` definition (or near the end of the file)**

```python
def cef_initialize(view_width: int, view_height: int, html_path: str) -> bool:
    """Initialise the CEF overlay browser. Idempotent; returns True on success."""
    return _h.cef_initialize(view_width, view_height, html_path)


def cef_pump() -> None:
    """Run one iteration of CEF's message loop. Call once per frame."""
    _h.cef_pump()


def cef_composite() -> None:
    """Blit the latest CEF bitmap over the current framebuffer."""
    _h.cef_composite()


def cef_shutdown() -> None:
    """Tear down CEF. Call before the GL context is destroyed."""
    _h.cef_shutdown()


def cef_toggle_devtools() -> None:
    """Open or close the DevTools window for the overlay browser."""
    _h.cef_toggle_devtools()


def cef_reload() -> None:
    """Reload the overlay browser's current document."""
    _h.cef_reload()
```

- [ ] **Step 2: Verify the module still imports cleanly**

```bash
uv run python -c "from engine import renderer; print(renderer.cef_initialize, renderer.cef_pump)"
```

Expected: prints two function references.

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "engine: re-export cef_* bindings via engine.renderer"
```

---

## Task 13: Wire per-tick CEF pump + composite into `host_bindings.cc::frame()`

**Files:**
- Modify: `native/src/host/host_bindings.cc`

The pump-then-composite pair must run between the last 3D pass and `swap_buffers()`, with CEF holding the GL context. The cleanest place is inside the existing C++ `frame()` function — modifying `engine/host_loop.py` would require re-wrapping the entire frame in Python.

Task 11 already added the `#include "ui_cef/cef_lifecycle.h"` guarded by `#ifdef DAUNTLESS_ENABLE_CEF` for the bindings. The same include serves the calls below; no further include changes needed.

- [ ] **Step 1: Insert pump + composite into `frame()`**

In `frame()`, after the `if (g_bridge_pass_enabled && g_bridge_pass) { ... }` block closes and BEFORE the key-state snapshot loop (`for (auto& [k, prev] : g_prev_key_state)`), insert:

```cpp
#ifdef DAUNTLESS_ENABLE_CEF
    // Pump CEF's message loop (may deliver OnPaint synchronously into
    // g_client). Then composite the latest bitmap over the 3D scene with
    // premultiplied-alpha blend. Runs before poll_events / swap_buffers.
    dauntless::ui_cef::pump();
    dauntless::ui_cef::composite();
#endif
```

- [ ] **Step 2: Build and verify**

```bash
cmake --build build --target dauntless _dauntless_host -j
```

Expected: clean build. The binary is now wired to pump and composite every frame, but `cef_initialize` has not been called yet — `pump` and `composite` are both no-ops when `g_initialized == false`, so the scene continues to render exactly as before.

```bash
./build/dauntless --smoke-check
```

Expected: same smoke-check output as today's main.

- [ ] **Step 3: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "host: pump + composite CEF inside frame() per tick (no-op until initialise)"
```

---

## Task 14: Wire CEF init + shutdown + key handlers into `engine/host_loop.py`

**Files:**
- Modify: `engine/host_loop.py`
- Modify: `native/src/host/host_bindings.cc` (add three new GLFW key constants)

- [ ] **Step 1: Add the CEF init call after `r.init(1280, 720, "open_stbc")`**

Find the line near `host_loop.py:1840`:

```python
    r.init(1280, 720, "open_stbc")
```

Immediately after, add:

```python
    # Initialise the CEF UI overlay. Resolves hello.html relative to the
    # project root (two parents up from this file).
    _cef_html = _project_root_for_cef() / "native" / "assets" / "ui-cef" / "hello.html"
    if not r.cef_initialize(1280, 720, str(_cef_html)):
        # Non-fatal in builds where CEF is disabled (the stub returns False).
        # If CEF is enabled and initialize failed, the binary will print the
        # framework-load error to stderr — surface it but keep running so the
        # 3D scene still renders.
        import sys as _sys
        print("[host_loop] cef_initialize returned False — overlay disabled",
              file=_sys.stderr)
```

Add this helper near the top of the file (after other `_project_root_*` helpers, or define one if none exists):

```python
def _project_root_for_cef():
    """Return the project root path for resolving native/assets/ui-cef/ files."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent
```

- [ ] **Step 2: Wire `cef_shutdown()` into the teardown path**

In `engine/host_loop.py`, find where the main loop exits (search for `r.shutdown()` near the end of `run()`). Immediately BEFORE `r.shutdown()`:

```python
    r.cef_shutdown()  # tear down CEF while GL context still alive
    r.shutdown()
```

- [ ] **Step 3: Add F12 and Cmd+R key handlers**

In `engine/host_loop.py`, find the F10 handler block near line 1925 (`_h.key_pressed(_h.keys.KEY_F10)`). Add F12 handling alongside:

```python
            # F12: toggle CEF DevTools for the UI overlay.
            if _h is not None and _h.key_pressed(_h.keys.KEY_F12):
                _h.cef_toggle_devtools()
```

For Cmd+R (macOS) / Ctrl+R (Linux/Windows), we already have a `KEY_R` constant exported. Add it nearby:

```python
            # Cmd+R / Ctrl+R: hot-reload the CEF overlay's HTML.
            if _h is not None and _h.key_pressed(_h.keys.KEY_R):
                # Reload only when Cmd (macOS) or Ctrl (Linux/Windows) is held;
                # bare R is reverse-thrust and must not be intercepted.
                _cmd_held = _h.key_state(_h.keys.KEY_LEFT_SUPER) if hasattr(_h.keys, "KEY_LEFT_SUPER") else False
                _ctrl_held = _h.key_state(_h.keys.KEY_LEFT_CONTROL) if hasattr(_h.keys, "KEY_LEFT_CONTROL") else False
                if _cmd_held or _ctrl_held:
                    _h.cef_reload()
```

**That requires exporting `KEY_F12`, `KEY_LEFT_SUPER`, `KEY_LEFT_CONTROL` from the bindings.** Add to `native/src/host/host_bindings.cc`'s `keys` submodule (next to the other KEY_F* constants):

```cpp
    keys.attr("KEY_F12")          = GLFW_KEY_F12;
    keys.attr("KEY_LEFT_SUPER")   = GLFW_KEY_LEFT_SUPER;
    keys.attr("KEY_LEFT_CONTROL") = GLFW_KEY_LEFT_CONTROL;
```

- [ ] **Step 4: Build and confirm everything still compiles**

```bash
cmake --build build --target dauntless _dauntless_host -j
```

Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py native/src/host/host_bindings.cc
git commit -m "host_loop: drive CEF lifecycle + F12 DevTools + Cmd/Ctrl+R reload"
```

---

## Task 15: First runtime smoke — Hello world over the scene

**Files:** none — runtime verification only.

- [ ] **Step 1: Run dauntless**

```bash
./build/dauntless
```

- [ ] **Step 2: Manual verification (this is the moment of truth)**

Check all of the following:

1. **No Keychain prompt.** No "Chromium Safe Storage" dialog appears at any point during startup or running.
2. **No Notifications prompt.** No "dauntless wants to send Notifications" dialog appears.
3. **"Hello world" visible.** White Antonio text in the top-left of the window, sized ~24 px.
4. **Scene visible through the rest of the window.** Sun, dust, player ship, backdrop all rendering exactly as before.
5. **Dust unchanged.** Particles drift past as expected; no new artifacts.
6. **Inputs work:** press W/S/A/D and observe the ship move. Press 1–9 and observe throttle settings change. Press R and observe reverse. Press SPACE → bridge interior appears. Press ESC → exterior view restored. Press F10 → shield bubble flash appears on the player ship.

Either every item passes, or the run failed. If anything fails, debug before committing.

- [ ] **Step 3: Test F12 (DevTools)**

While dauntless is running, press F12. A separate native window with the Chrome DevTools inspector should open, attached to the `hello.html` document. Press F12 again → window closes. The 3D scene and "Hello world" text continue rendering unchanged through both transitions.

- [ ] **Step 4: Test Cmd+R (reload)**

With dauntless running, edit `native/assets/ui-cef/hello.html` to change the text to "Hello dauntless". Save. Press Cmd+R (macOS) or Ctrl+R. The overlay text should update to "Hello dauntless" within a frame, without a rebuild.

Revert the edit before continuing:

```bash
git checkout native/assets/ui-cef/hello.html
```

- [ ] **Step 5: Test clean exit**

Close the dauntless window via the X button. The process should exit cleanly with no console errors, no crash, no hang. Check the exit code:

```bash
echo $?
```

Expected: 0.

- [ ] **Step 6: Commit any debugging adjustments needed to reach the gate**

If verification passed without code changes, this task has no commit. Otherwise:

```bash
git add -p   # selectively
git commit -m "fix: <what was needed>"
```

---

## Task 16: Pytest verification

**Files:** none — verification only.

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest
```

Expected: green. No new skips beyond what was already skipped on `main` before this work began.

- [ ] **Step 2: Investigate any failures**

Most likely failure modes:
- `tests/host/test_bindings_smoke.py` may need `cef_*` added to a list of expected names. If so, add them. Do not add or remove any other assertions.
- Tests that subprocess-run `./build/dauntless` may need to set `DAUNTLESS_ENABLE_CEF=ON`/`OFF` via env. If so, fix per-test.

- [ ] **Step 3: Commit any test adjustments**

```bash
git add tests/
git commit -m "tests: account for cef_* bindings in host smoke tests"
```

---

## Task 17: Update `THIRD_PARTY_NOTICES.md`

**Files:**
- Modify: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Add entries**

Append to the file:

```markdown
## Chromium Embedded Framework (CEF)

- Licence: BSD 3-Clause (CEF) + various open-source licences for bundled Chromium components
- Version pinned: 144.0.25+g27ce504+chromium-144.0.7559.250
- Source: https://bitbucket.org/chromiumembedded/cef
- Distribution: Minimal binary from https://cef-builds.spotifycdn.com/
- See `build/_deps/cef-src/LICENSE.txt` for full text after first configure.

## Antonio font

- Licence: SIL Open Font License 1.1 (OFL)
- Source: https://github.com/google/fonts/tree/main/ofl/antonio
- Copy of the licence is shipped at `native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`.
```

- [ ] **Step 2: Commit**

```bash
git add THIRD_PARTY_NOTICES.md
git commit -m "docs: third-party notices for CEF + Antonio"
```

---

## Task 18: Final verification gate (spec §12)

**Files:** none — paperwork.

- [ ] **Step 1: Walk through each of the eight spec gates and confirm pass**

1. **Build clean.** `cmake -B build -S . && cmake --build build -j` succeeds, links libcef. ✓ (Tasks 1–9)
2. **No permission prompts.** Manual smoke run shows neither Keychain nor Notifications prompt. ✓ (Task 15 Step 2)
3. **Scene unchanged.** Side-by-side with `main`: sun/dust/ship/bridge/shields identical. ✓ (Task 15 Step 2)
4. **Overlay visible.** "Hello world" top-left in white Antonio. ✓ (Task 15 Step 2)
5. **Inputs work.** WASD, 0–9, R, SPACE, ESC, F10 all functional. ✓ (Task 15 Step 2)
6. **Dev tooling.** F12 opens DevTools; Cmd+R reloads. ✓ (Task 15 Steps 3–4)
7. **Pytest green.** `uv run pytest` passes with no new skips. ✓ (Task 16)
8. **Clean exit.** Window-X closes cleanly. ✓ (Task 15 Step 5)

- [ ] **Step 2: Final commit if anything outstanding**

If any gate was met with adjustments, commit them now. Otherwise no commit needed.

- [ ] **Step 3: Final summary** (this is a manual write-up for the PR description)

Write a one-paragraph summary listing what got integrated, what verification ran, and any deferred items (locale-pak stripping, .app bundle, IPC adapter for real panels). This becomes the PR body when the branch is ready to merge.

---

## Self-review checklist (engineer fills out before declaring done)

- [ ] All eight spec gates met (Task 18 Step 1).
- [ ] No file uses `try/except: pass` or `throw` inside `ui_cef/` (compiled with normal flags, but the lifecycle code uses `std::exit` for unrecoverable errors per the worktree's precedent).
- [ ] `THIRD_PARTY_NOTICES.md` updated.
- [ ] All commits have descriptive messages and the working tree is clean.
- [ ] Branch is rebased on latest `main` (no merge commits introduced).
