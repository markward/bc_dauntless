// native/src/renderer/include/renderer/far_pass.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md, §3): the
// impostor draw. One glDrawArraysInstanced per non-empty ImpostorBin whose
// catalogue rock has an atlas, through Pipeline::impostor_shader() --
// impostor.vert linked with the EXISTING opaque.frag -- so an impostor is lit
// by the same code as a mesh rock. Specks (render_specks) are one instanced draw of
// premultiplied, area-weighted screen quads through Pipeline::speck_shader().
#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <assets/texture.h>

#include <renderer/far_field.h>
#include <renderer/speck.h>
#include <renderer/rock_speck.h>
#include <renderer/rock_puffs.h>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;
struct Lighting;

class FarPass {
public:
    FarPass() = default;
    FarPass(const FarPass&) = delete;
    FarPass& operator=(const FarPass&) = delete;
    ~FarPass();                         // deletes the GL objects (GL alive)

    // Atlas for catalogue rock `index`, loaded lazily from these paths and kept
    // until the pass is destroyed (NOT on mission swap: not mission content).
    // A relative path is joined onto project_asset_root() at LOAD time.
    void set_atlas_paths(std::vector<std::pair<std::string, std::string>> albedo_normal);

    // `rim_strength` is the FINAL u_rim_strength, as MinorPass::render takes it.
    void render_impostors(const std::vector<far::ImpostorBin>& bins, const scenegraph::Camera& cam,
                          Pipeline& pipeline, const Lighting& lighting, float ambient_scale,
                          float rim_strength);

    // Rock fade (2026-10-03): the same draw, TRANSLUCENT -- for impostors
    // fading in from (or out to) nothing, where the screen door read as a
    // dot grid. Each item draws premultiplied with alpha =
    // far::impostor_fade_alpha(axis_y_dither.w) (opaque.frag's u_impostor_blend
    // path: no dither discard; the coverage cutout stays), blended
    // GL_ONE / GL_ONE_MINUS_SRC_ALPHA, depth-tested WITHOUT depth writes.
    // Bins and items draw in the order given -- the caller sorts far to near.
    // The host draws these in phase 2. Silhouette-edge 2x2
    // quads (partial under the per-pixel coverage cutout) shade differently
    // from render_impostors' -- MEASURED; undefined derivatives, as for the
    // dithered draw. A pixel's NaN-probe cause code (u_nan_debug) stays in alpha.
    // Afterwards blending is off with the blend function as found, depth
    // test and writes are on, the active texture unit is 0 and no VAO is bound.
    void render_impostors_blended(const std::vector<far::ImpostorBin>& bins,
                                  const scenegraph::Camera& cam, Pipeline& pipeline,
                                  const Lighting& lighting, float ambient_scale,
                                  float rim_strength);

    // One instanced draw of every speck (none when empty): premultiplied,
    // blended GL_ONE / GL_ONE_MINUS_SRC_ALPHA, depth-tested without depth
    // writes, unculled. `viewport_w/h` are the target's framebuffer pixels.
    // `ambient_scale` scales the ambient exactly as render_impostors /
    // configure_rock_program do (set_ambient_uniforms), so a filmic exterior
    // dims a speck's ambient with its mesh's.
    void render_specks(const std::vector<SpeckGpu>& specks, const scenegraph::Camera& cam,
                       Pipeline& pipeline, const Lighting& lighting, float ambient_scale,
                       float speck_gain, int viewport_w, int viewport_h);

    // Rock-field speck band (rock_speck.h): upload the band's
    // instances when it re-streams; draw them every frame (GPU-side radius
    // and alpha, rock_speck.vert). Same blend/depth state as render_specks.
    struct RockSpeckDraw {
        glm::vec3 offset{0.0f};   // render-space position of the band origin
        float in_gu = 0, in_fade_gu = 0, out_gu = 0, out_fade_gu = 0;
        float keep_d0_gu = 0, keep_band = 0.25f, keep_power = 3.0f, gain = 1.0f;
    };
    void upload_rock_specks(const std::vector<rockfield::RockSpeckGpu>& specks);
    void render_rock_specks(const RockSpeckDraw& d, const scenegraph::Camera& cam,
                            Pipeline& pipeline, const Lighting& lighting, float ambient_scale,
                            float speck_gain, int viewport_w, int viewport_h);
    int rock_speck_count() const { return rock_speck_count_; }
    // Rock-field puffs (rock_puffs.h): upload on change, draw every
    // frame. Premultiplied over, depth-tested, no depth writes, unculled.
    void upload_rock_puffs(const std::vector<rockfield::PuffGpu>& puffs);
    void render_rock_puffs(const glm::vec3& offset, const rockfield::PuffDials& d,
                           const scenegraph::Camera& cam, Pipeline& pipeline,
                           const Lighting& lighting, float ambient_scale);
    int rock_puff_count() const { return rock_puff_count_; }

    int last_draw_calls() const { return draw_calls_; }   // since the last reset_counts()
    void reset_counts() { draw_calls_ = 0; }
    bool atlas_loaded(int index) const { return atlases_.count(index) != 0; }
    // Whether catalogue rock `index` can draw an impostor: loads its atlas now
    // if needed (GL must be current). False for a missing/corrupt file or no
    // path -- the host then tells FarField the rock has no impostor.
    bool has_atlas(int index) { return atlas_for(index) != nullptr; }

    // TEST-ONLY: inject an atlas instead of loading files.
    void debug_set_atlas(int index, const assets::Image& albedo, const assets::Image& normal);

private:
    struct AtlasGpu { assets::Texture albedo, normal; };
    const AtlasGpu* atlas_for(int index);   // lazy load; nullptr = none
    void draw_impostors(const std::vector<far::ImpostorBin>& bins, const scenegraph::Camera& cam,
                        Pipeline& pipeline, const Lighting& lighting, float ambient_scale,
                        float rim_strength, bool blended);
    void install_atlas(int index, assets::Image albedo, assets::Image normal);
    void ensure_geometry();

    std::vector<std::pair<std::string, std::string>> paths_;
    std::map<int, AtlasGpu> atlases_;
    std::set<int> failed_;                  // warned once; never retried
    std::uint32_t vao_ = 0;
    std::uint32_t corner_vbo_ = 0;
    std::uint32_t instance_vbo_ = 0;
    std::size_t instance_capacity_ = 0;     // bytes
    std::vector<far::ImpostorGpu> staging_;
    std::uint32_t speck_vao_ = 0;
    std::uint32_t speck_vbo_ = 0;
    std::size_t speck_capacity_ = 0;        // bytes
    std::uint32_t rock_speck_vao_ = 0;
    std::uint32_t rock_speck_vbo_ = 0;
    int rock_speck_count_ = 0;
    std::uint32_t rock_puff_vao_ = 0;
    std::uint32_t rock_puff_vbo_ = 0;
    int rock_puff_count_ = 0;
    std::uint32_t white_texture_ = 0;
    std::uint32_t black_texture_ = 0;
    int draw_calls_ = 0;
};

// Dilate RGB into alpha-0 texels (`passes` rings), keeping alpha. Pure, CPU.
// Each ring fills an uncovered texel with the mean RGB of its already-filled
// 8-neighbours, so mipmaps of an impostor atlas do not fringe the silhouette
// toward the transparent texels' colour.
void dilate_coverage(assets::Image& img, int passes);

}  // namespace renderer
