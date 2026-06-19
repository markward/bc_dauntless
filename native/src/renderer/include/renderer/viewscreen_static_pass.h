#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <assets/texture.h>
namespace renderer { class Shader; }

namespace renderer {

/// Composites the BC "View Screen Static" noise over the viewscreen RTT.
/// Owns the (up to 3) noise frames; cycles them by wall time and alpha-blends
/// the current frame at `intensity` so the framebuffer computes
/// out = mix(feed, noise, intensity). Orientation-agnostic (noise is isotropic).
class ViewscreenStaticPass {
public:
    ViewscreenStaticPass() = default;
    ~ViewscreenStaticPass();
    ViewscreenStaticPass(const ViewscreenStaticPass&) = delete;
    ViewscreenStaticPass& operator=(const ViewscreenStaticPass&) = delete;

    /// Load/cache noise frames from absolute paths. No-op if the path set is
    /// unchanged. Skips frames that fail to load.
    void set_textures(const std::vector<std::string>& paths);
    bool has_textures() const { return !frames_.empty(); }

    /// Draw the current noise frame over the bound framebuffer, alpha-blended
    /// at `intensity`. Saves/restores blend + depth + cull state.
    void render(Shader& shader, float intensity, double wall_time);

    /// Test-only: register a single 1x1 (v,v,v,1) frame without file I/O.
    void set_solid_noise_for_test(float v);

private:
    void ensure_quad();
    std::vector<assets::Texture> frames_;
    std::vector<std::string> loaded_paths_;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
};

}  // namespace renderer
