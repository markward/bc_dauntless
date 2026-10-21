#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <assets/texture.h>
namespace renderer { class Shader; }

namespace renderer {

/// What the viewscreen bars show this frame (pushed from Python).
struct ViewscreenBars {
    bool visible = false;
    std::string top, bottom;
    std::array<float, 3> band_rgb{};   // 0..1, sRGB as sent by Python /255
    std::array<float, 3> text_rgb{};
};

/// Band height as a fraction of the target height (top and bottom band each).
constexpr float kVsBarsHeightFrac  = 0.10f;
/// Inner-corner radius in pixels at a 640-wide target; scales with the width.
constexpr float kVsBarsRadiusPx640 = 18.0f;
/// No band or text channel exceeds this: the viewscreen picture reaches the
/// main post chain unlit, and its bloom threshold is ~0.9 (spec §4.3).
constexpr float kVsBarsChannelCap  = 0.85f;

/// Draws the target name / range bands over the viewscreen RTT: two solid
/// bands edge to edge (top band rounds its bottom corners, bottom band its
/// top corners) with bitmap-font text centred in each. Text comes from a
/// generated atlas (native/assets/fonts/viewscreen_antonio.{json,png}).
class ViewscreenBarsPass {
public:
    ViewscreenBarsPass() = default;
    ~ViewscreenBarsPass();
    ViewscreenBarsPass(const ViewscreenBarsPass&) = delete;
    ViewscreenBarsPass& operator=(const ViewscreenBarsPass&) = delete;

    /// Load the font JSON and the atlas it names (relative to the JSON's
    /// directory). Returns false -- logging once -- on any failure, and the
    /// pass then has no font, so render() is a no-op.
    bool load_font(const std::string& json_path);
    bool has_font() const { return atlas_.id() != 0; }
    /// Lazy load: loads `<asset_root>/fonts/viewscreen_antonio.json` unless a
    /// font is already loaded, and attempts at most once per distinct root
    /// value (a failed root is not retried; a changed root gets one attempt).
    bool ensure_font(const std::string& asset_root);

    /// Draw over the bound framebuffer, alpha-blended. No-op when
    /// !bars.visible or no font. Saves/restores blend, depth, cull, program,
    /// active texture + its 2D binding, VAO and array buffer.
    void render(Shader& shader, const ViewscreenBars& bars, int target_w, int target_h);

    /// Test seams, in font pixels. layout: one (pen x, advance) per DRAWN
    /// glyph (a glyph with an empty box, such as space, or a byte missing
    /// from the atlas advances the pen but is not listed). fit: the string
    /// actually drawn for a band `max_w` wide (ellipsis-truncated).
    std::vector<std::pair<float, float>> layout_line_for_test(const std::string& s,
                                                              float max_w) const;
    std::string fit_for_test(const std::string& s, float max_w) const;

private:
    struct Glyph { float x, y, w, h, bearing_x, bearing_y, advance; };
    const Glyph* glyph(unsigned char c) const;
    float advance_of(unsigned char c) const;
    float width_of(const std::string& s) const;
    std::string fit(const std::string& s, float max_w) const;
    std::vector<std::pair<float, float>> layout(const std::string& s) const;
    void ensure_buffers();

    std::unordered_map<std::uint32_t, Glyph> glyphs_;
    float space_advance_ = 0.f;
    float line_height_ = 0.f;
    float ascent_ = 0.f;
    float atlas_w_ = 1.f, atlas_h_ = 1.f;
    assets::Texture atlas_;
    bool logged_failure_ = false;
    std::string last_font_root_;
    bool font_root_tried_ = false;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
};

}  // namespace renderer
