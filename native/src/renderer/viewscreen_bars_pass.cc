#include <renderer/viewscreen_bars_pass.h>
#include <renderer/shader.h>
#include <assets/file_bytes.h>
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string_view>

namespace renderer {

namespace {

// Every readout pixel value is authored at a 640-wide RTT (spec §2a).
constexpr float kReadoutDesignTargetW = 640.0f;

constexpr std::string_view kEllipsis = "...";

/// `rgb` scaled (hue kept) so no channel exceeds kVsBarsChannelCap.
glm::vec3 capped(const std::array<float, 3>& rgb) {
    glm::vec3 c(std::clamp(rgb[0], 0.f, 1.f), std::clamp(rgb[1], 0.f, 1.f),
                std::clamp(rgb[2], 0.f, 1.f));
    const float mx = std::max({c.r, c.g, c.b});
    if (mx > kVsBarsChannelCap) c *= kVsBarsChannelCap / mx;
    return c;
}

struct Vertex { float x, y, u, v; };

void push_quad(std::vector<Vertex>& out, float x0, float y0, float x1, float y1,
               float u0, float v0, float u1, float v1) {
    // (x0,y0) bottom-left / (x1,y1) top-right in GL pixels; v0 at y0, v1 at y1.
    out.push_back({x0, y0, u0, v0}); out.push_back({x1, y0, u1, v0});
    out.push_back({x1, y1, u1, v1}); out.push_back({x0, y0, u0, v0});
    out.push_back({x1, y1, u1, v1}); out.push_back({x0, y1, u0, v1});
}

}  // namespace

ViewscreenBarsPass::~ViewscreenBarsPass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

bool ViewscreenBarsPass::ensure_font(const std::string& asset_root) {
    if (has_font()) return true;
    if (font_root_tried_ && asset_root == last_font_root_) return false;
    font_root_tried_ = true;
    last_font_root_ = asset_root;
    return load_font(asset_root + "/fonts/viewscreen_antonio.json");
}

bool ViewscreenBarsPass::load_font(const std::string& json_path) {
    glyphs_.clear();
    atlas_ = assets::Texture{};
    auto fail = [&](const std::string& why) {
        glyphs_.clear();
        atlas_ = assets::Texture{};
        if (!logged_failure_) {
            std::fprintf(stderr, "[vs-bars] font '%s': %s -- bars disabled\n",
                         json_path.c_str(), why.c_str());
            logged_failure_ = true;
        }
        return false;
    };

    const auto text = assets::read_binary_file(json_path);
    if (!text) return fail("cannot read");
    std::string atlas_name;
    try {
        const auto j = nlohmann::json::parse(text->begin(), text->end());
        atlas_name   = j.at("atlas").get<std::string>();
        atlas_w_     = j.at("atlas_w").get<float>();
        atlas_h_     = j.at("atlas_h").get<float>();
        line_height_ = j.at("line_height").get<float>();
        ascent_      = j.at("ascent").get<float>();
        for (const auto& [key, g] : j.at("glyphs").items()) {
            glyphs_[static_cast<std::uint32_t>(std::stoul(key))] = Glyph{
                g.at("x").get<float>(), g.at("y").get<float>(),
                g.at("w").get<float>(), g.at("h").get<float>(),
                g.at("bearing_x").get<float>(), g.at("bearing_y").get<float>(),
                g.at("advance").get<float>()};
        }
    } catch (const std::exception& e) {
        return fail(std::string("bad JSON: ") + e.what());
    }
    const auto space = glyphs_.find(' ');
    if (space == glyphs_.end()) return fail("no space glyph");
    space_advance_ = space->second.advance;
    const auto cap = glyphs_.find('H');
    cap_height_ = cap != glyphs_.end() ? cap->second.bearing_y : ascent_;

    const auto atlas_path = std::filesystem::path(json_path).parent_path() / atlas_name;
    const auto bytes = assets::read_binary_file(atlas_path);
    if (!bytes) return fail("cannot read atlas '" + atlas_path.string() + "'");
    try {
        const assets::Image img = assets::decode_image(*bytes);
        if (static_cast<float>(img.width) != atlas_w_ ||
            static_cast<float>(img.height) != atlas_h_)
            return fail("atlas size does not match atlas_w/atlas_h");
        atlas_ = assets::upload_image(img, /*generate_mipmaps=*/true);
    } catch (const std::exception& e) {
        return fail(std::string("atlas: ") + e.what());
    }
    return true;
}

const ViewscreenBarsPass::Glyph* ViewscreenBarsPass::glyph(unsigned char c) const {
    const auto it = glyphs_.find(c);
    return it == glyphs_.end() ? nullptr : &it->second;
}

float ViewscreenBarsPass::advance_of(unsigned char c) const {
    const Glyph* g = glyph(c);
    return g ? g->advance : space_advance_;
}

float ViewscreenBarsPass::width_of(const std::string& s) const {
    float w = 0.f;
    for (unsigned char c : s) w += advance_of(c);
    return w;
}

std::string ViewscreenBarsPass::fit(const std::string& s, float max_w) const {
    if (width_of(s) <= max_w) return s;
    const float ell = width_of(std::string(kEllipsis));
    if (ell > max_w) return {};
    std::string out;
    float w = 0.f;
    for (unsigned char c : s) {
        const float a = advance_of(c);
        if (w + a + ell > max_w) break;
        w += a;
        out.push_back(static_cast<char>(c));
    }
    return out + std::string(kEllipsis);
}

std::vector<std::pair<float, float>> ViewscreenBarsPass::layout(const std::string& s) const {
    std::vector<std::pair<float, float>> pens;
    float pen = 0.f;
    for (unsigned char c : s) {
        const Glyph* g = glyph(c);
        if (g && g->w > 0.f && g->h > 0.f) pens.emplace_back(pen, g->advance);
        pen += g ? g->advance : space_advance_;
    }
    return pens;
}

ViewscreenReadoutLayout ViewscreenBarsPass::readout_layout(int target_w,
                                                           int target_h) const {
    ViewscreenReadoutLayout l;
    if (!has_font() || target_w <= 0 || target_h <= 0) return l;
    const float s  = static_cast<float>(target_w) / kReadoutDesignTargetW;
    const float th = static_cast<float>(target_h);
    l.scale1 = kVsReadoutLine1Scale * s;
    l.scale2 = kVsReadoutLine2Scale * s;
    l.cap_height1 = cap_height_ * l.scale1;
    // Line 1's cap top sits the inset below the top edge (high y).
    l.baseline1 = std::round(th - kVsReadoutInsetYPx * s - l.cap_height1);
    // Line 2 is top-aligned with line 1: same cap top, its own cap height.
    l.baseline2 = std::round(th - kVsReadoutInsetYPx * s - cap_height_ * l.scale2);
    // Dot centred on line 1's caps, its left edge at the inset.
    l.dot_r  = 0.5f * kVsReadoutDotDiameterFrac * l.cap_height1;
    l.dot_cx = kVsReadoutInsetXPx * s + l.dot_r;
    l.dot_cy = l.baseline1 + 0.5f * l.cap_height1;
    l.name_x = std::round(l.dot_cx + l.dot_r + kVsReadoutDotGapPx * s);
    l.max_w  = static_cast<float>(target_w) - l.name_x - kVsReadoutInsetXPx * s;
    l.detail_right_x = static_cast<float>(target_w) - kVsReadoutInsetXPx * s;
    return l;
}

float ViewscreenBarsPass::detail_origin_x(const std::string& detail, int target_w,
                                          int target_h) const {
    const ViewscreenReadoutLayout l = readout_layout(target_w, target_h);
    if (!has_font() || l.scale2 <= 0.f) return 0.f;
    // Ellipsised only if it alone exceeds the old full width.
    const std::string drawn = fit(detail, l.max_w / l.scale2);
    return std::round(l.detail_right_x - width_of(drawn) * l.scale2);
}

float ViewscreenBarsPass::name_max_w(const std::string& detail, int target_w,
                                     int target_h) const {
    const ViewscreenReadoutLayout l = readout_layout(target_w, target_h);
    if (detail.empty()) return l.max_w;
    const float s = static_cast<float>(target_w) / kReadoutDesignTargetW;
    return detail_origin_x(detail, target_w, target_h) -
           kVsReadoutNameDetailGapPx * s - l.name_x;
}

std::vector<std::pair<float, float>> ViewscreenBarsPass::layout_line_for_test(
    const std::string& s, float max_w, float scale) const {
    auto pens = layout(fit(s, max_w / scale));
    for (auto& [pen, adv] : pens) { pen *= scale; adv *= scale; }
    return pens;
}

std::string ViewscreenBarsPass::fit_for_test(const std::string& s, float max_w,
                                             float scale) const {
    return fit(s, max_w / scale);
}

void ViewscreenBarsPass::ensure_buffers() {
    if (vao_) return;
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(Vertex), nullptr);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(Vertex),
                          reinterpret_cast<void*>(2 * sizeof(float)));
}

void ViewscreenBarsPass::render(Shader& shader, const ViewscreenBars& bars,
                                int target_w, int target_h) {
    if (!bars.visible || !has_font() || target_w <= 0 || target_h <= 0) return;

    const float tw = static_cast<float>(target_w);
    const float th = static_cast<float>(target_h);
    const ViewscreenReadoutLayout l = readout_layout(target_w, target_h);

    // Geometry: [0,6) the dot's quad (padded for the antialiased edge), then
    // the glyph quads of both lines.
    std::vector<Vertex> verts;
    const float pad = l.dot_r + 1.5f;
    push_quad(verts, l.dot_cx - pad, l.dot_cy - pad, l.dot_cx + pad, l.dot_cy + pad,
              0, 0, 0, 0);
    auto emit_line = [&](const std::string& s, float x0, float max_w, float baseline,
                         float scale) {
        const std::string drawn = fit(s, max_w / scale);
        float pen = 0.f;
        for (unsigned char c : drawn) {
            const Glyph* g = glyph(c);
            if (g && g->w > 0.f && g->h > 0.f) {
                const float gx0 = x0 + (pen + g->bearing_x) * scale;
                const float gy1 = baseline + g->bearing_y * scale;   // glyph top
                // Atlas rows are top-down and upload unflipped, so texture
                // v = atlas_y / atlas_h: the glyph TOP is v = y / H.
                push_quad(verts, gx0, gy1 - g->h * scale, gx0 + g->w * scale, gy1,
                          g->x / atlas_w_, (g->y + g->h) / atlas_h_,
                          (g->x + g->w) / atlas_w_, g->y / atlas_h_);
            }
            pen += g ? g->advance : space_advance_;
        }
    };
    emit_line(bars.name, l.name_x, name_max_w(bars.detail, target_w, target_h),
              l.baseline1, l.scale1);
    emit_line(bars.detail, detail_origin_x(bars.detail, target_w, target_h), l.max_w,
              l.baseline2, l.scale2);

    // Save state.
    const GLboolean prev_blend = glIsEnabled(GL_BLEND);
    const GLboolean prev_depth = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_cull  = glIsEnabled(GL_CULL_FACE);
    GLint prev_src_rgb = GL_ONE, prev_dst_rgb = GL_ZERO;
    GLint prev_src_alpha = GL_ONE, prev_dst_alpha = GL_ZERO;
    glGetIntegerv(GL_BLEND_SRC_RGB,   &prev_src_rgb);
    glGetIntegerv(GL_BLEND_DST_RGB,   &prev_dst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &prev_src_alpha);
    glGetIntegerv(GL_BLEND_DST_ALPHA, &prev_dst_alpha);
    GLint prev_program = 0, prev_active_tex = GL_TEXTURE0, prev_tex0 = 0;
    GLint prev_vao = 0, prev_array_buffer = 0;
    glGetIntegerv(GL_CURRENT_PROGRAM, &prev_program);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &prev_active_tex);
    glActiveTexture(GL_TEXTURE0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev_tex0);
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &prev_vao);
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &prev_array_buffer);

    ensure_buffers();
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(verts.size() * sizeof(Vertex)),
                 verts.data(), GL_STREAM_DRAW);

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    shader.use();
    shader.set_vec2("u_target", glm::vec2(tw, th));
    glBindTexture(GL_TEXTURE_2D, atlas_.id());
    shader.set_int("u_atlas", 0);
    shader.set_vec3("u_dot", glm::vec3(l.dot_cx, l.dot_cy, l.dot_r));

    const GLsizei glyph_verts = static_cast<GLsizei>(verts.size()) - 6;
    auto draw_all = [&](const glm::vec3& dot_rgb, const glm::vec3& text_rgb) {
        shader.set_int("u_mode", 0);
        shader.set_vec3("u_color", dot_rgb);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        if (glyph_verts > 0) {
            shader.set_int("u_mode", 1);
            shader.set_vec3("u_color", text_rgb);
            glDrawArrays(GL_TRIANGLES, 6, glyph_verts);
        }
    };
    // Shadow first: the same geometry in black, offset down-right (GL y up).
    const float off = kVsReadoutShadowOffsetPx * tw / kReadoutDesignTargetW;
    shader.set_vec2("u_offset", glm::vec2(off, -off));
    shader.set_float("u_alpha", kVsReadoutShadowAlpha);
    draw_all(glm::vec3(0.f), glm::vec3(0.f));
    // Then the dot in the affiliation colour and the text in white, capped.
    shader.set_vec2("u_offset", glm::vec2(0.f));
    shader.set_float("u_alpha", 1.f);
    draw_all(capped(bars.dot_rgb), capped({1.f, 1.f, 1.f}));

    // Restore state.
    glBindVertexArray(static_cast<GLuint>(prev_vao));
    glBindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(prev_array_buffer));
    glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(prev_tex0));
    glActiveTexture(static_cast<GLenum>(prev_active_tex));
    glUseProgram(static_cast<GLuint>(prev_program));
    glBlendFuncSeparate(static_cast<GLenum>(prev_src_rgb),
                        static_cast<GLenum>(prev_dst_rgb),
                        static_cast<GLenum>(prev_src_alpha),
                        static_cast<GLenum>(prev_dst_alpha));
    if (!prev_blend) glDisable(GL_BLEND);
    if (prev_depth)  glEnable(GL_DEPTH_TEST);
    if (prev_cull)   glEnable(GL_CULL_FACE);
}

}  // namespace renderer
