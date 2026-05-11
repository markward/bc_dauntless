// native/src/ui/UiSystem.cc
#include "ui/UiSystem.h"
#include "ui/HudDocument.h"
#include "ui/PanelDocument.h"

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

    hud_ = std::make_unique<HudDocument>(context_, assets_root / "hud.rml");
    assets_root_ = assets_root;

    // RmlUi debug overlay — open on demand via the F8 key (handled in
    // host_loop). Initialise unconditionally; SetVisible toggles display.
    Rml::Debugger::Initialise(context_);

    // Wire GLFW input → RmlUi context. The scroll callback is owned by
    // renderer::Window (orbit camera zoom) and is intentionally not touched
    // here. Mouse-wheel forwarding into RmlUi can be added later when a
    // scrollable panel needs it.
    g_input_ctx = context_;
    glfwSetCursorPosCallback(window, cursor_pos_cb);
    glfwSetMouseButtonCallback(window, mouse_button_cb);
    glfwSetKeyCallback(window, key_cb);
    glfwSetCharCallback(window, char_cb);
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

void UiSystem::update_hud(const HudState& state) {
    if (hud_) hud_->update(state);
    if (context_) context_->Update();
}

void UiSystem::render(int fb_width, int fb_height) {
    if (!context_) return;
    render_iface_->SetViewport(fb_width, fb_height);
    render_iface_->BeginFrame();
    context_->Render();
    render_iface_->EndFrame();
}

}  // namespace ui
