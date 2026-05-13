// native/src/ui/UiSystem.cc
#include "ui/UiSystem.h"
#include "ui/HudDocument.h"
#include "ui/PanelDocument.h"
#include <renderer/window.h>

// glad must be included before any GL headers.
#include <glad/glad.h>

#include <RmlUi_Platform_GLFW.h>
#include <RmlUi_Renderer_GL3.h>
#include <RmlUi/Core.h>
#include <RmlUi/Debugger.h>
#include <GLFW/glfw3.h>

#include <cstdio>
#include <stdexcept>

namespace ui {

namespace {
// Single UiSystem at a time — the input callbacks reference this directly.
// GLFW callbacks are C function pointers (no captures), so the context has
// to live somewhere addressable. The host has exactly one UI system, so a
// translation-unit-scope pointer is the cleanest fit.
Rml::Context* g_input_ctx = nullptr;

void cursor_pos_cb(GLFWwindow* w, double xpos, double ypos) {
    if (g_input_ctx) {
        RmlGLFW::ProcessCursorPosCallback(g_input_ctx, w, xpos, ypos, /*mods=*/0);
    }
}

void mouse_button_cb(GLFWwindow*, int button, int action, int mods) {
    if (g_input_ctx) {
        RmlGLFW::ProcessMouseButtonCallback(g_input_ctx, button, action, mods);
    }
}

void key_cb(GLFWwindow*, int key, int /*scancode*/, int action, int mods) {
    if (g_input_ctx) {
        RmlGLFW::ProcessKeyCallback(g_input_ctx, key, action, mods);
    }
}

void char_cb(GLFWwindow*, unsigned int codepoint) {
    if (g_input_ctx) {
        RmlGLFW::ProcessCharCallback(g_input_ctx, codepoint);
    }
}

void scroll_cb(GLFWwindow* w, double /*xoffset*/, double yoffset) {
    // Always forward scroll to the Window accumulator.  The Python host
    // loop decides whether the wheel goes to the camera or to a panel
    // based on a cursor-vs-panel-bounds check (see _cursor_over_panel in
    // engine/host_loop.py).
    //
    // RmlUi's ProcessScrollCallback return value reports "propagation
    // still active" — true is the common case when no element cancelled
    // the event, and tells us nothing useful about whether a scrollable
    // panel actually consumed the wheel.  We still call it so any future
    // scrollable RmlUi elements get a chance to process the event.
    if (g_input_ctx) {
        RmlGLFW::ProcessScrollCallback(
            g_input_ctx, yoffset, /*key_modifier_state=*/0);
    }
    if (auto* win = static_cast<renderer::Window*>(
            glfwGetWindowUserPointer(w))) {
        win->add_scroll_y(yoffset);
    }
}
}  // namespace

UiSystem::UiSystem(GLFWwindow* window,
                   const std::filesystem::path& assets_root)
    : sys_iface_(std::make_unique<SystemInterface_GLFW>())
    , render_iface_(std::make_unique<RenderInterface_GL3>())
{
    sys_iface_->SetWindow(window);

    Rml::SetSystemInterface(sys_iface_.get());

    if (!Rml::Initialise()) {
        throw std::runtime_error("ui::UiSystem: Rml::Initialise() failed");
    }

    int fb_width = 0, fb_height = 0;
    glfwGetFramebufferSize(window, &fb_width, &fb_height);
    if (fb_width  <= 0) fb_width  = 1280;
    if (fb_height <= 0) fb_height = 720;

    context_ = Rml::CreateContext(
        "main",
        Rml::Vector2i(fb_width, fb_height),
        render_iface_.get()
    );
    if (!context_) {
        Rml::Shutdown();
        throw std::runtime_error("ui::UiSystem: Rml::CreateContext failed");
    }

    auto font_path = (assets_root / "fonts" / "Antonio-Regular.ttf").string();
    if (!Rml::LoadFontFace(font_path)) {
        std::fprintf(stderr,
            "[ui] Warning: failed to load font '%s' - HUD text will not render\n",
            font_path.c_str());
    }

    // Symbol fallback. Antonio's glyph table doesn't cover the Unicode
    // geometric-shapes block used by the collapsible disclosure arrows
    // (U+25B6 etc.), so we load Noto Sans Symbols 2 as a fallback face —
    // RmlUi consults fallback faces for any missing glyph in the primary.
    auto symbols_path = (assets_root / "fonts" / "NotoSansSymbols2-Regular.ttf").string();
    if (!Rml::LoadFontFace(symbols_path, /*fallback_face=*/true)) {
        std::fprintf(stderr,
            "[ui] Warning: failed to load symbol fallback font '%s' - "
            "geometric glyphs (arrows etc.) will render as boxes\n",
            symbols_path.c_str());
    }

    // The old hud.rml debug overlay was replaced by an in-engine UiPanel
    // ("Debug" top-right, built from host_loop.py via UiStatRow). The
    // HudDocument class stays in the tree as Phase-2 reference but is no
    // longer instantiated by the runtime.
    assets_root_ = assets_root;

    // RmlUi debug overlay — open on demand via the F8 key (handled in
    // host_loop). Initialise unconditionally; SetVisible toggles display.
    Rml::Debugger::Initialise(context_);

    // Wire GLFW input → RmlUi context.  Scroll is filtered: RmlUi
    // attempts to consume the event first (cursor over a scrollable
    // element), and if it declines the delta is forwarded to
    // renderer::Window's accumulator for camera-zoom.
    g_input_ctx = context_;
    glfwSetCursorPosCallback(window, cursor_pos_cb);
    glfwSetMouseButtonCallback(window, mouse_button_cb);
    glfwSetKeyCallback(window, key_cb);
    glfwSetCharCallback(window, char_cb);
    glfwSetScrollCallback(window, scroll_cb);
}

UiSystem::~UiSystem() {
    g_input_ctx = nullptr;
    panels_.clear();      // destroy panel documents before RmlUi shuts down
    hud_.reset();
    context_ = nullptr;   // owned by RmlUi core; Shutdown destroys it
    Rml::Shutdown();
}

int UiSystem::create_panel(const std::string& anchor,
                           float width_vw, float height_vh) {
    int id = next_panel_id_++;
    panels_[id] = std::make_unique<PanelDocument>(
        context_,
        assets_root_ / "panel.rml",
        anchor, width_vw, height_vh);
    return id;
}

void UiSystem::destroy_panel(int panel_id) {
    panels_.erase(panel_id);
}

PanelDocument* UiSystem::get_panel(int panel_id) {
    auto it = panels_.find(panel_id);
    return it == panels_.end() ? nullptr : it->second.get();
}

void UiSystem::set_ui_scale(float scale) {
    if (context_) context_->SetDensityIndependentPixelRatio(scale);
}

void UiSystem::toggle_debugger() {
    static bool visible = false;
    visible = !visible;
    Rml::Debugger::SetVisible(visible);
}

void UiSystem::toggle_visibility() {
    rendering_enabled_ = !rendering_enabled_;
    // Skip Rml::Debugger when visibility is off, otherwise its window stays
    // up while everything else disappears.
    Rml::Debugger::SetVisible(false);
}

void UiSystem::update_hud(const HudState& state) {
    if (hud_) hud_->update(state);
    if (context_) context_->Update();
}

void UiSystem::render(int fb_width, int fb_height) {
    if (!context_) return;
    if (!rendering_enabled_) return;
    render_iface_->SetViewport(fb_width, fb_height);
    render_iface_->BeginFrame();
    context_->Render();
    render_iface_->EndFrame();
}

}  // namespace ui
