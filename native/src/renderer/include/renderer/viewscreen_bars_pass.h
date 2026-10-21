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

/// What the viewscreen target readout shows this frame (pushed from Python).
struct ViewscreenBars {
    bool visible = false;
    std::string name, detail;          // line 1 (after the dot), line 2
    std::array<float, 3> dot_rgb{};    // 0..1, sRGB as sent by Python /255
};

// Readout geometry (spec §2a). Pixel values are at a 640-wide RTT; every one
// scales by target_w / 640, the font too (scale 1.0 = the atlas pixel_size).
/// Inset from the picture's left and top edges, so the bezel can't clip it.
constexpr float kVsReadoutInsetXPx         = 24.f;
constexpr float kVsReadoutInsetYPx         = 18.f;
/// Line sizes, as a fraction of the atlas pixel_size (one atlas, scaled).
constexpr float kVsReadoutLine1Scale       = 1.0f;
constexpr float kVsReadoutLine2Scale       = 0.7f;
/// Minimum gap between the (ellipsised) name's end and the detail line.
constexpr float kVsReadoutNameDetailGapPx  = 16.f;
/// Dot diameter as a fraction of line 1's cap height ('H' bearing_y).
constexpr float kVsReadoutDotDiameterFrac  = 0.6f;
/// Dot right edge -> name.
constexpr float kVsReadoutDotGapPx         = 7.f;
/// Black shadow under the dot and both lines, offset down-right.
constexpr float kVsReadoutShadowOffsetPx   = 1.5f;
constexpr float kVsReadoutShadowAlpha      = 0.6f;
/// No dot or text channel exceeds this: the viewscreen picture reaches the
/// main post chain unlit, and its bloom threshold is ~0.9 (spec §4.3).
constexpr float kVsBarsChannelCap          = 0.85f;

/// Where the readout goes on a target, in GL pixels (origin bottom-left,
/// y up: the top of the picture is high y).
struct ViewscreenReadoutLayout {
    float scale1 = 0.f, scale2 = 0.f;   // atlas pixel -> target pixel, per line
    float cap_height1 = 0.f;            // line 1 cap height, target pixels
    float baseline1 = 0.f;
    float baseline2 = 0.f;              // detail line: cap top level with line 1's
    float dot_cx = 0.f, dot_cy = 0.f, dot_r = 0.f;
    float name_x = 0.f;                 // the name starts here
    float max_w = 0.f;                  // widest a line may be before "..."
    float detail_right_x = 0.f;         // detail line's right edge (top-right)
};

/// The target readout: dot + name top-left, distance/speed line top-right.
/// Font atlas: `<project_asset_root>/fonts/viewscreen_antonio.json`.
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

    /// The readout's placement on a target_w x target_h RTT. Needs the font
    /// (cap height); without one every field is 0.
    ViewscreenReadoutLayout readout_layout(int target_w, int target_h) const;

    /// Pen x of the detail line (right-aligned, whole pixels). 0 without a font.
    float detail_origin_x(const std::string& detail, int target_w, int target_h) const;
    /// Widest the name may be: stops kVsReadoutNameDetailGapPx short of the
    /// detail line; the old full width when `detail` is empty.
    float name_max_w(const std::string& detail, int target_w, int target_h) const;

    /// Test seams, in TARGET pixels for a line drawn at `scale` (atlas pixel
    /// -> target pixel). layout: one (pen x, advance) per DRAWN glyph (a glyph
    /// with an empty box, such as space, or a byte missing from the atlas
    /// advances the pen but is not listed). fit: the string actually drawn in
    /// `max_w` (ellipsis-truncated).
    std::vector<std::pair<float, float>> layout_line_for_test(const std::string& s,
                                                              float max_w,
                                                              float scale) const;
    std::string fit_for_test(const std::string& s, float max_w, float scale) const;

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
    float cap_height_ = 0.f;   // 'H' bearing_y, else ascent
    float atlas_w_ = 1.f, atlas_h_ = 1.f;
    assets::Texture atlas_;
    bool logged_failure_ = false;
    std::string last_font_root_;
    bool font_root_tried_ = false;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
};

}  // namespace renderer
