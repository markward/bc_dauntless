// native/src/ui_cef/cef_lifecycle.cc
#include "cef_lifecycle.h"

#include "cef_app.h"
#include "cef_client.h"
#include "cef_composite_pass.h"

#include "include/cef_app.h"
#include "include/cef_browser.h"
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

#ifdef __APPLE__
    // On macOS the default LoadInMain() looks at <exec-dir>/../Frameworks/,
    // which assumes an .app bundle layout we don't use. Compute the
    // explicit path that matches Task 8's symlink at build/Frameworks/.
    const std::filesystem::path exec_path = std::filesystem::canonical(argv[0]);
    const std::string framework_lib =
        exec_path.parent_path().string() +
        "/Frameworks/Chromium Embedded Framework.framework/"
        "Chromium Embedded Framework";
    if (!cef_load_library(framework_lib.c_str())) {
        std::fprintf(stderr,
                     "dauntless: cef_load_library failed for %s\n",
                     framework_lib.c_str());
        return 1;
    }
#else
    g_library_loader = std::make_unique<CefScopedLibraryLoader>();
    if (!g_library_loader->LoadInMain()) {
        std::fprintf(stderr,
                     "dauntless: failed to load CEF framework.\n");
        return 1;
    }
#endif

    CefMainArgs main_args(argc, argv);
    g_app = new DauntlessCefApp();
    // CefExecuteProcess returns >= 0 for helper roles and -1 for the
    // main browser process. Callers exit with the returned code if it's
    // >= 0, otherwise proceed to initialize().
    return CefExecuteProcess(main_args, g_app, nullptr);
}

bool initialize(int view_width, int view_height,
                const std::string& html_path,
                float device_scale_factor) {
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
    CefString(&settings.browser_subprocess_path) = exec_path.string();
#endif

    if (!CefInitialize(main_args, settings, g_app, nullptr)) {
        std::fprintf(stderr, "ui_cef: CefInitialize failed\n");
        return false;
    }

    g_client = new DauntlessCefClient(view_width, view_height);
    g_client->set_device_scale_factor(device_scale_factor);

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

void execute_javascript(const std::string& script) {
    if (!g_client || !g_client->browser()) return;
    auto frame = g_client->browser()->GetMainFrame();
    if (!frame) return;
    frame->ExecuteJavaScript(script, frame->GetURL(), 0);
}

void send_mouse_move(int x, int y) {
    if (!g_client || !g_client->browser()) return;
    auto host = g_client->browser()->GetHost();
    if (!host) return;
    CefMouseEvent ev;
    ev.x = x;
    ev.y = y;
    ev.modifiers = 0;
    host->SendMouseMoveEvent(ev, /*mouseLeave=*/false);
}

void send_mouse_click(int x, int y, int button, bool is_down) {
    if (!g_client || !g_client->browser()) return;
    auto host = g_client->browser()->GetHost();
    if (!host) return;
    CefMouseEvent ev;
    ev.x = x;
    ev.y = y;
    ev.modifiers = 0;
    cef_mouse_button_type_t btn = MBT_LEFT;
    if (button == 1) btn = MBT_MIDDLE;
    else if (button == 2) btn = MBT_RIGHT;
    // Single click — CEF wants click_count=1 on press and on the
    // matching release. Double-clicks would pass 2; we never generate
    // those from Python's edge-only mouse helpers.
    host->SendMouseClickEvent(ev, btn, /*mouseUp=*/!is_down, /*clickCount=*/1);
}

void set_event_handler(std::function<void(const std::string&)> handler) {
    if (!g_client) return;
    g_client->set_event_handler(std::move(handler));
}

void set_load_end_handler(std::function<void()> handler) {
    if (g_client) {
        g_client->set_load_end_handler(std::move(handler));
    }
}

void shutdown() {
    if (!g_initialized) return;
    g_composite.reset();  // releases GL handles while GL context is alive
    g_client = nullptr;
    CefShutdown();
    g_app = nullptr;
    g_initialized = false;
#ifdef __APPLE__
    cef_unload_library();
#endif
}

}  // namespace dauntless::ui_cef
