// native/src/renderer/include/renderer/backdrop_pass.h
#pragma once

#include <renderer/frame.h>          // Backdrop, BackdropKind
#include <assets/mesh.h>
#include <assets/texture.h>

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
                Pipeline& pipeline);

private:
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
};

}  // namespace renderer
