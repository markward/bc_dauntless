// native/src/ui/include/ui/UiSystem.h
#pragma once

#include <filesystem>
#include <memory>
#include <string>

struct GLFWwindow;
namespace Rml { class Context; }
class SystemInterface_GLFW;
class RenderInterface_GL3;

namespace ui {

class HudDocument;

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

private:
    std::unique_ptr<SystemInterface_GLFW> sys_iface_;
    std::unique_ptr<RenderInterface_GL3>  render_iface_;
    Rml::Context*                         context_ = nullptr;
    std::unique_ptr<HudDocument>          hud_;
};

}  // namespace ui
