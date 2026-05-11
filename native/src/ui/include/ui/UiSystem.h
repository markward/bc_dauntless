// native/src/ui/include/ui/UiSystem.h
#pragma once

#include <filesystem>
#include <memory>
#include <string>
#include <unordered_map>

struct GLFWwindow;
namespace Rml { class Context; }
class SystemInterface_GLFW;
class RenderInterface_GL3;

namespace ui {

class HudDocument;
class PanelDocument;

struct HudState {
    float pos_x = 0.f, pos_y = 0.f, pos_z = 0.f;
    float yaw_deg = 0.f, pitch_deg = 0.f, roll_deg = 0.f;
    std::string system_name;
    std::string ship_name;
};

class UiSystem {
public:
    /// Initialise RmlUi, load the font and HUD document from assets_root.
    /// Throws std::runtime_error if Rml::Initialise() or context creation fails.
    UiSystem(GLFWwindow* window, const std::filesystem::path& assets_root);
    ~UiSystem();

    UiSystem(const UiSystem&) = delete;
    UiSystem& operator=(const UiSystem&) = delete;

    /// Update HUD element text. Call once per frame before render().
    void update_hud(const HudState& state);

    /// Render the UI context at the given framebuffer size.
    void render(int fb_width, int fb_height);

    /// Create a new PanelDocument from panel.rml. Returns an integer handle
    /// the bindings use to reference it later. Ownership stays with this
    /// UiSystem.
    int create_panel(const std::string& anchor, float width_vw, float height_vh);
    void destroy_panel(int panel_id);
    PanelDocument* get_panel(int panel_id);

    /// Iterator access for the binding layer — used to resolve which panel
    /// owns a given element id when callers pass element ids directly.
    auto& panels_for_bindings() { return panels_; }

    /// Set the density-independent-pixel ratio for the UI context. Every
    /// `dp` value in RCSS / inline style is multiplied by this — a setting
    /// of 2.0 doubles the visual size of every UI element. Affects all
    /// documents in the context (HUD + panels).
    void set_ui_scale(float scale);

    /// Toggle the RmlUi debugger overlay. Shows the live element tree,
    /// computed styles, layout boxes — exactly what we need to see when
    /// "the panel only renders at top and bottom" without theorising.
    void toggle_debugger();

private:
    std::unique_ptr<SystemInterface_GLFW> sys_iface_;
    std::unique_ptr<RenderInterface_GL3>  render_iface_;
    Rml::Context*                         context_ = nullptr;
    std::unique_ptr<HudDocument>          hud_;

    std::filesystem::path                 assets_root_;
    std::unordered_map<int, std::unique_ptr<PanelDocument>> panels_;
    int                                   next_panel_id_ = 1;
};

}  // namespace ui
