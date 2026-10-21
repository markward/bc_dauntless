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

// The font's pixel size was chosen for a 360-tall viewscreen RTT (spec §4.2):
// at that height one atlas pixel is one target pixel. Other heights scale.
constexpr float kFontDesignTargetH = 360.0f;

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

std::vector<std::pair<float, float>> ViewscreenBarsPass::layout_line_for_test(
    const std::string& s, float max_w) const {
    return layout(fit(s, max_w));
}

std::string ViewscreenBarsPass::fit_for_test(const std::string& s, float max_w) const {
    return fit(s, max_w);
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
    const float band_h = std::round(kVsBarsHeightFrac * th);
    const float radius = std::min(kVsBarsRadiusPx640 * tw / 640.f, band_h);
    const float scale  = th / kFontDesignTargetH;
    const float max_w  = (tw - 2.f * radius) / scale;   // in font pixels

    // Geometry: [0,6) top band, [6,12) bottom band, then the glyph quads.
    std::vector<Vertex> verts;
    push_quad(verts, 0.f, th - band_h, tw, th, 0, 0, 0, 0);
    push_quad(verts, 0.f, 0.f, tw, band_h, 0, 0, 0, 0);
    auto emit_line = [&](const std::string& s, float band_top_y) {
        const std::string drawn = fit(s, max_w);
        const float x0 = std::round(0.5f * (tw - width_of(drawn) * scale));
        // The line box (line_height tall) centred on the band; baseline at
        // its top + ascent (GL y is up, so subtract going down).
        const float baseline = std::round(
            band_top_y - 0.5f * (band_h - line_height_ * scale) - ascent_ * scale);
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
    emit_line(bars.top, th);
    emit_line(bars.bottom, band_h);

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

    // Bands: top rounds its bottom corners, bottom rounds its top corners.
    shader.set_int("u_mode", 0);
    shader.set_vec3("u_color", capped(bars.band_rgb));
    shader.set_vec4("u_rect", glm::vec4(0.f, th - band_h, tw, th));
    shader.set_float("u_radius_top", 0.f);
    shader.set_float("u_radius_bottom", radius);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    shader.set_vec4("u_rect", glm::vec4(0.f, 0.f, tw, band_h));
    shader.set_float("u_radius_top", radius);
    shader.set_float("u_radius_bottom", 0.f);
    glDrawArrays(GL_TRIANGLES, 6, 6);

    // Text.
    const GLsizei glyph_verts = static_cast<GLsizei>(verts.size()) - 12;
    if (glyph_verts > 0) {
        shader.set_int("u_mode", 1);
        shader.set_vec3("u_color", capped(bars.text_rgb));
        glDrawArrays(GL_TRIANGLES, 12, glyph_verts);
    }

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
