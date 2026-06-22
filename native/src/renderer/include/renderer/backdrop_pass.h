// native/src/renderer/include/renderer/backdrop_pass.h
#pragma once

#include <renderer/frame.h>          // Backdrop, BackdropKind
#include <renderer/cubemap_target.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <glm/glm.hpp>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class BackdropPass {
public:
    BackdropPass() = default;
    ~BackdropPass();
    BackdropPass(const BackdropPass&) = delete;
    BackdropPass& operator=(const BackdropPass&) = delete;

    /// Render `backdrops` in order. Caller is responsible for clearing
    /// color + depth before this call. Caller has bound a default
    /// framebuffer.
    void render(const std::vector<Backdrop>& backdrops,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                bool procedural,
                float now_seconds,
                float warp_streak = 0.0f,
                glm::vec3 warp_travel = glm::vec3(0.0f, 1.0f, 0.0f));

    /// Bake `backdrops` into all 6 cubemap faces (camera at origin, 6 x 90deg
    /// views) using the same procedural shader path as render(). Returns false
    /// if the cubemap could not be allocated. Call once per system entry.
    bool bake(const std::vector<Backdrop>& backdrops,
              Pipeline& pipeline,
              float now_seconds);

    /// Draw the skybox sampling the baked cubemap by view direction into the
    /// currently-bound framebuffer. No-op if no successful bake exists.
    void render_cubemap(const scenegraph::Camera& camera, Pipeline& pipeline);

    bool has_cubemap() const { return cubemap_.valid(); }
    int  bakes_count() const { return bakes_count_; }

private:
    /// Shared per-sphere draw loop used by render() and bake(). Caller sets the
    /// target framebuffer/viewport and (for bake) the per-face view/proj.
    void draw_backdrops(const std::vector<Backdrop>& backdrops,
                        const glm::mat4& view_no_translation,
                        const glm::mat4& proj,
                        Pipeline& pipeline,
                        bool procedural,
                        float now_seconds,
                        float warp_streak,
                        glm::vec3 warp_travel);

    /// Lazy-tessellated UV sphere keyed by target_poly_count. Most BC
    /// systems use 256; cache grows on demand if a script requests
    /// something different.
    std::unordered_map<int, std::unique_ptr<assets::Mesh>> sphere_cache_;

    /// Texture cache keyed by absolute path. Sentinel entries (with
    /// id() == 0) mark previously-failed loads to suppress per-frame
    /// retries.
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    assets::Mesh*    ensure_sphere(int target_poly_count);
    assets::Texture* ensure_texture(const std::string& path);

    CubemapTarget cubemap_;
    int bakes_count_ = 0;
    static constexpr int kSkyFaceSize = 1024;
};

/// True iff `backdrops` is non-empty and every entry is procedural (empty
/// texture_path) — the map-driven sky case that the cubemap bake handles.
bool backdrops_are_procedural(const std::vector<Backdrop>& backdrops);

/// True iff `a` and `b` are the same length and every field of every entry is
/// equal. Used to detect when the per-frame descriptor list actually changed
/// (and the cubemap must be re-baked).
bool backdrops_equal(const std::vector<Backdrop>& a,
                     const std::vector<Backdrop>& b);

}  // namespace renderer
