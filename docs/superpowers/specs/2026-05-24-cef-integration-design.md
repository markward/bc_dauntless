# CEF Integration — Design

**Status:** design drafted, awaiting user review
**Date:** 2026-05-24
**Author:** Mark Ward (with Claude)
**Prior art:** [`2026-05-23-cef-poc-design.md`](./2026-05-23-cef-poc-design.md) and [`2026-05-23-cef-poc-results.md`](./2026-05-23-cef-poc-results.md) on the `sdk-ui-shim` worktree. Read-only reference; this spec rebuilds on `main` from scratch.
**Follows:** [`2026-05-24-remove-rmlui-design.md`](./2026-05-24-remove-rmlui-design.md) (Stage 1 of UI→CEF). RmlUi removal landed; the dauntless build has no UI at all today.

## 1. Goal

Embed CEF as the UI rendering layer inside the existing `build/dauntless` binary. Render a transparent overlay browser the same size as the GL window. The browser loads one static HTML file that displays "Hello world" in the top-left corner, white, Antonio typeface. The 3D scene renders behind it with no regressions to dust, sun, glow, bridge view, or any existing pass. Game inputs (WASD, 0–9, R, SPACE, mouse) remain functional via the unchanged GLFW path; CEF receives no input events.

## 2. Non-goals

- Multiple panels, F-key routing, IPC adapter, event dispatch, Python ↔ JS bindings, DOM mutation API. All in the rebuild spec; out of scope here.
- macOS `.app` bundle. We keep the PoC's flat-directory approach with framework symlink + explicit `CefSettings` path overrides.
- Validating Windows or Linux at runtime. CMake is written portable; only macOS is built and tested.
- Zero-copy GPU surface (IOSurface, D3D11 shared texture). CPU bitmap upload only.
- Removing the worktree's `dauntless-cef` artifact (separate branch; not our concern).

## 3. Architecture

```
                     ┌─────────────────────────────────────┐
                     │ dauntless (single binary)           │
                     │                                     │
GLFW window ────────▶│ host_main: CefExecuteProcess()      │
                     │   ├── browser process (main thread) │
                     │   └── helper subprocesses (spawned) │
                     │                                     │
each frame:          │ host_loop tick                      │
                     │   ├── Python: ship/scene update     │
                     │   ├── render scene passes           │
                     │   ├── CefDoMessageLoopWork()        │
                     │   └── ui_cef_composite_pass.draw()  │◀──┐
                     │         (textured full-screen quad) │   │
                     │                                     │   │
                     │ off-thread (CEF UI thread = main):  │   │
                     │   OnPaint(BGRA buffer) ─────────────┼───┘
                     │     uploads to GL texture           │
                     └─────────────────────────────────────┘
```

- **One binary, multi-role dispatch.** `host_main.cc` calls `CefExecuteProcess(argv)` first. If the process is a helper role, that returns ≥ 0 and we exit. Otherwise we proceed to normal startup (GLFW window, GL context, Python embed, scene, etc.).
- **Single-threaded message pump.** `CefSettings::multi_threaded_message_loop = false`, `external_message_pump = false`. `CefDoMessageLoopWork()` is called once per `host_loop` tick. No thread bridge.
- **OSR (off-screen rendering) browser.** `CefBrowserHost::CreateBrowser` with `windowless_rendering_enabled = true` and a `CefRenderHandler` that delivers BGRA buffers to a new `ui_cef_composite_pass`.
- **Transparent background.** `CefBrowserSettings::background_color = 0x00000000` plus `color-scheme: dark; background: transparent;` on `<body>`. The GL composite uses standard alpha blend (`glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)`).

## 4. Build system

**`native/CMakeLists.txt` additions:**

- New `option(DAUNTLESS_ENABLE_CEF "" ON)` — defaults on. Lets us turn CEF off in tooling builds (e.g. NIF probes) that don't need a renderer.
- A small per-platform URL table mapping `(host_os, host_arch)` → Spotify CDN tarball:

  ```cmake
  set(CEF_VERSION "149.x.y+gZZZ+chromium-149.0.NNNN.MM")  # exact tag chosen at plan time
  if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
    set(CEF_PLATFORM "macosarm64")
  elseif(APPLE)
    set(CEF_PLATFORM "macosx64")
  elseif(WIN32)
    set(CEF_PLATFORM "windows64")
  elseif(UNIX)
    set(CEF_PLATFORM "linux64")
  endif()
  set(CEF_URL "https://cef-builds.spotifycdn.com/cef_binary_${CEF_VERSION}_${CEF_PLATFORM}_minimal.tar.bz2")
  ```

- `FetchContent_Declare(cef URL ${CEF_URL} URL_HASH SHA256=...)` — hash pinned per platform. The hash table lives in CMake; updates require re-pinning.
- `BUILD_SHARED_LIBS` save/restore around `add_subdirectory(${cef_SOURCE_DIR}/libcef_dll)` so `libcef_dll_wrapper` builds STATIC regardless of project-level settings — carried over from the PoC's `BUILD_SHARED_LIBS` lesson.
- `SET_EXECUTABLE_TARGET_PROPERTIES(dauntless)` from `cef_variables.cmake` so `dauntless` inherits CEF's required flags (including `-fno-exceptions` on the target — no `throw` in CEF-adjacent code; `std::exit` is the fatal-error path).
- POST_BUILD step that symlinks (macOS) or copies (Windows, Linux) the CEF framework / `.so` / `.dll` alongside `build/dauntless` so `CefScopedLibraryLoader::LoadInMain()` resolves it. Platform-branched.

**`native/src/host/CMakeLists.txt`:**

- New library `ui_cef` (sibling of `renderer`, lives under `native/src/ui_cef/`), linked into `dauntless`.
- `target_link_libraries(dauntless PRIVATE ui_cef libcef_lib libcef_dll_wrapper)`.

## 5. Source layout

**New files:**

```
native/src/ui_cef/
├── CMakeLists.txt
├── cef_app.{h,cc}              CefApp impl: OnBeforeCommandLine (lockdown switches)
├── cef_client.{h,cc}            CefClient + CefRenderHandler (OnPaint → composite pass)
├── cef_lifecycle.{h,cc}         init(window, scene-size) / shutdown / pump / browser handle
└── cef_composite_pass.{h,cc}    GL texture + full-screen quad shader; called from frame()

native/assets/ui-cef/
├── hello.html                   <html><body><div class="hello">Hello world</div></body></html>
├── css/
│   └── hello.css                @font-face Antonio; .hello { position fixed top-left, white, transparent body }
└── fonts/
    └── Antonio-Regular.woff2    Locally shipped (OFL licence — THIRD_PARTY_NOTICES entry)
```

**Modified files:**

- `native/src/host/host_main.cc` — early `CefExecuteProcess` dispatch; CEF init after window/GL ready; pump + composite per frame; CEF shutdown before window destroy.
- `native/src/host/host_bindings.cc` — two new bindings: `cef_toggle_devtools()` and `cef_reload()`. No other surface changes.
- `engine/host_loop.py` — F12 → `_h.cef_toggle_devtools()`, Cmd/Ctrl+R → `_h.cef_reload()`. Slot into the existing key-handler block.
- `native/CMakeLists.txt` and the new `ui_cef/CMakeLists.txt` per §4.
- `THIRD_PARTY_NOTICES.md` — CEF (BSD), Antonio (OFL).

## 6. Composite pass

`ui_cef_composite_pass` is structurally similar to existing render passes:

- One GL texture (`GL_TEXTURE_2D`, `GL_BGRA`, `GL_UNSIGNED_BYTE`), sized to window.
- One VAO + two-triangle full-screen quad, one shader (vertex passthrough, fragment samples texture).
- `OnPaint` callback (runs on main thread per §3) calls into the pass to update the dirty rects via `glTexSubImage2D` — only the changed regions, matching CEF's contract.
- `frame()` calls `pass.draw()` after all other render passes. Standard alpha blend; depth disabled (UI is always on top).
- Window-resize hook resizes both the texture and notifies `CefBrowserHost::WasResized()`.

## 7. Threading & main loop

Per-tick order inside `host_loop`:

1. GLFW `glfwPollEvents()` → existing input handling.
2. Python tick (mission AI, physics, scene update).
3. Render scene passes (existing): backdrop, sun, ships, dust, shields, bridge, etc.
4. `_h.cef_pump()` → calls `CefDoMessageLoopWork()`. This may synchronously call `OnPaint` if CEF has new pixels ready; the composite pass updates its texture in place.
5. `ui_cef_composite_pass.draw()` — blits the most-recent texture state over the scene.
6. `glfwSwapBuffers()`.

CEF's UI thread is our main thread (single-threaded mode). `OnPaint` therefore arrives on the main thread, between calls 4 and 5, with the GL context current. No mutex, no double-buffer.

## 8. Lockdowns — hard requirement

`CefApp::OnBeforeCommandLine` MUST append these switches before CEF initialises, applied to all process types including helpers:

| Switch | Reason |
|---|---|
| `--password-store=basic` | Stops the **Chromium Safe Storage / Keychain password prompt** |
| `--use-mock-keychain` | Belt-and-braces; some macOS paths still touch Keychain otherwise |
| `--disable-notifications` | Stops the **"dauntless wants to send Notifications"** prompt |
| `--disable-gpu` | Forces software rendering inside CEF's GPU process; avoids conflict with our GLFW GL context |
| `--disable-gpu-compositing` | Same family; required alongside `--disable-gpu` on macOS |

These are non-negotiable. A verification gate (§12) explicitly asserts that launching `build/dauntless` produces neither prompt.

Two additional `CefSettings` lockdowns:

- `command_line_args_disabled = true` — prevents user-provided `argv` from re-enabling disabled features.
- `no_sandbox = true` — required when there is no `.app` bundle. Acceptable for a local-file-only browser; revisit if/when the bundle is added.

## 9. Input routing

The existing GLFW key/mouse handling stays exactly as it is. CEF receives no events.

Implementation: the CEF browser is created with `windowless_rendering_enabled = true` and we never call `CefBrowserHost::SendKeyEvent` / `SendMouseClickEvent` / `SendMouseMoveEvent`. The browser is effectively a render-only sink. WASD, 0–9, R, SPACE, mouse-orbit, scroll-zoom, F10 — all unchanged.

Two exceptions for dev tooling (§10):

- F12 is intercepted in `host_loop.py` and dispatched to `_h.cef_toggle_devtools()` — never forwarded to game controls (it wasn't used by them anyway).
- Cmd+R (macOS) / Ctrl+R (Linux, Windows) is intercepted similarly and dispatched to `_h.cef_reload()`.

## 10. Hot reload + DevTools

- `_h.cef_toggle_devtools()` → `CefBrowserHost::ShowDevTools()` if not open, else `CloseDevTools()`. Opens in a separate platform window (DevTools is not OSR — CEF gives it a native window automatically). Acceptable since it's a dev tool, not shipped UX.
- `_h.cef_reload()` → `CefBrowser::Reload()`. Re-fetches `hello.html` from disk. Combined with editing the file in your editor, gives sub-second iteration on CSS/HTML without rebuilding.

## 11. Cross-platform portability — what's portable, what's macOS-only

| Concern | macOS (validated) | Windows (portable) | Linux (portable) |
|---|---|---|---|
| CEF tarball URL | `macosarm64` | `windows64` | `linux64` |
| `libcef` library | `Chromium Embedded Framework.framework` | `libcef.dll` | `libcef.so` |
| `LoadInMain()` resolver path | Framework symlink alongside binary | DLL alongside | `.so` alongside |
| Helper subprocess path | Same binary (multi-role dispatch) | Same binary | Same binary |
| `CefSettings` path overrides | All five (no `.app` bundle) | Defaults work | Defaults work |
| `--no-sandbox` required | Yes (no bundle) | No | No (unless suid sandbox missing) |
| Hot reload key | Cmd+R | Ctrl+R | Ctrl+R |

The C++ code branches on platform only inside `cef_lifecycle.cc::init()` for the path overrides and inside the CMake POST_BUILD step. Everything else is platform-independent.

## 12. Verification gates

The work is complete only when all gates pass on macOS:

1. **Build clean.** `cmake -B build -S . && cmake --build build -j` succeeds. `build/dauntless` exists and links libcef.
2. **No permission prompts.** `./build/dauntless` launches without showing the Keychain password prompt or the Notifications permission prompt. Both are reproducible failures of this gate.
3. **Scene unchanged.** Sun, dust, ship NIFs, bridge view, shields all render exactly as on `main` today. Side-by-side snapshot vs current `main` shows no diff in the 3D region.
4. **Overlay visible.** "Hello world" appears top-left in white Antonio. 3D scene visible through the rest of the window. No black background, no fallback font.
5. **Inputs work.** WASD moves the ship, 0–9 sets throttle, R reverses, SPACE toggles bridge view, ESC exits bridge view, F10 still triggers shield-hit debug.
6. **Dev tooling.** F12 opens DevTools in a separate window. Cmd+R reloads `hello.html` (edit the file, hit Cmd+R, see the change).
7. **Pytest green.** `uv run pytest` passes with no new skips.
8. **Clean exit.** Closing the window with the X button shuts down CEF before the GL context, then exits without crash or hang.

## 13. Risks & mitigations

- **CEF `-fno-exceptions` propagates to `dauntless`.** Any existing code in the binary using `throw` will fail to compile. Mitigation: audit during implementation; convert to `std::exit` or factor into a library that doesn't inherit the CEF flags. If broad, scope this into the plan as a discrete prep step.
- **Antonio licence.** Antonio is OFL — redistribution requires THIRD_PARTY_NOTICES entry. Tracked in §5.
- **CEF tarball size in CI.** 300+ MB download per fresh build tree. Mitigation: `FetchContent` caches under `build/_deps/`; only downloaded once per build tree. CI cache key includes CEF version.
- **CEF version pinning.** Chromium 149 series at design time; the exact tarball + SHA256 gets picked in the implementation plan and frozen in CMake. Updates are deliberate, not automatic.
- **GLFW + CEF init order.** CEF requires `CefInitialize` before any browser creation but also before any non-CEF threads start. The PoC ordered it: GLFW init → GL context → CEF init → browser create. Same order here.
- **DevTools window blocks input on its own window only.** It's a native OS window managed by CEF, separate from our GLFW window. Closing it doesn't disturb anything. Confirmed safe pattern.

## 14. Out of scope (deliberate)

- IPC adapter (`push_state` / event dispatch). When real panels arrive, this design extends; today's CEF integration is one-way render.
- Multiple browsers. One full-window browser; if we later want a per-panel browser model, that's a re-architecture call.
- macOS `.app` bundle.
- Replacing GLFW with CEF's own windowing.
- Removing the worktree's `dauntless-cef` artifact.

## 15. What happens after this stage

This integration is intentionally minimal: prove CEF embedded in the canonical `dauntless` binary, with a one-line transparent overlay, on macOS. Subsequent stages add scope without re-architecting:

- **Next:** IPC adapter (Python `push_state(panel, json)` → JS `data-bind` rendering) + first real panel (officer menu or engineer, per the rebuild spec's Phase E order).
- **Later:** macOS `.app` bundle, hot-reload event dispatch, multi-browser per-panel model if needed.
- **Eventually:** Linux + Windows validation, locale-pak stripping, zero-copy GPU surface if perf demands it.

Each is its own brainstorm + spec + plan cycle.
