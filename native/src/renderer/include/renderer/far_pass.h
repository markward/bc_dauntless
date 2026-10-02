// native/src/renderer/include/renderer/far_pass.h
// Far tier (docs/superpowers/specs/2026-10-01-far-tier-design.md, §3): the
// impostor draw. One glDrawArraysInstanced per non-empty ImpostorBin whose
// catalogue rock has an atlas, through Pipeline::impostor_shader() --
// impostor.vert linked with the EXISTING opaque.frag -- so an impostor is lit
// by the same code as a mesh rock. Speck and haze draws arrive with later
// tasks of the far-tier plan. Specks (render_specks) are one instanced draw of
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

    // One instanced draw of every speck (none when empty): premultiplied,
    // blended GL_ONE / GL_ONE_MINUS_SRC_ALPHA, depth-tested without depth
    // writes, unculled. `viewport_w/h` are the target's framebuffer pixels.
    // `ambient_scale` scales the ambient exactly as render_impostors /
    // configure_rock_program do (set_ambient_uniforms), so a filmic exterior
    // dims a speck's ambient with its mesh's.
    void render_specks(const std::vector<SpeckGpu>& specks, const scenegraph::Camera& cam,
                       Pipeline& pipeline, const Lighting& lighting, float ambient_scale,
                       float speck_gain, int viewport_w, int viewport_h);

    // Belt haze (spec §2 "Haze"): one fullscreen-triangle draw of
    // far_haze.frag per source in `active` that has populations, among the
    // first 4 (the rest are ignored, with one warning; a population-less
    // source has nothing to march and draws nothing). `origin_sys` is the eye in system coordinates; the
    // eye in render space is the camera's. `depth_texture` is the scene depth
    // the march stops at, reconstructed through `inv_view_proj`. No pixel cut
    // (ruling R16): the haze is independent of the camera's k, and each
    // source's `brightness` scales its colour only. A table longer than 32 rows uses its first 32 and
    // warns once; at most 2 populations per source are marched, and
    // dials.haze_steps is clamped to [1, 64]. Premultiplied blend, depth test
    // and depth writes off; afterwards depth test and writes are on, blending
    // off, and the blend function is as found.
    void render_haze(const std::vector<far::DiscSource>& active, const glm::dvec3& origin_sys,
                     const scenegraph::Camera& cam, Pipeline& pipeline, const Lighting& lighting,
                     float ambient_scale, unsigned depth_texture, const glm::mat4& inv_view_proj,
                     const far::FarDials& dials);

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
    std::uint32_t white_texture_ = 0;
    std::uint32_t black_texture_ = 0;
    std::uint32_t haze_vao_ = 0;            // empty: the fullscreen triangle
    bool warned_haze_cap_ = false;
    bool warned_haze_table_ = false;
    bool warned_haze_pops_ = false;
    int draw_calls_ = 0;
};

// Dilate RGB into alpha-0 texels (`passes` rings), keeping alpha. Pure, CPU.
// Each ring fills an uncovered texel with the mean RGB of its already-filled
// 8-neighbours, so mipmaps of an impostor atlas do not fringe the silhouette
// toward the transparent texels' colour.
void dilate_coverage(assets::Image& img, int passes);

}  // namespace renderer
