// native/src/renderer/include/renderer/pipeline.h
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept     { return *opaque_; }
    Shader& backdrop_shader() noexcept   { return *backdrop_; }
    Shader& sun_shader() noexcept        { return *sun_; }
    Shader& dust_shader() noexcept       { return *dust_; }
    Shader& shield_shader() noexcept     { return *shield_; }
    Shader& lens_flare_shader() noexcept { return *lens_flare_; }
    Shader& torpedo_shader() noexcept    { return *torpedo_; }
    Shader& hit_vfx_shader() noexcept    { return *hit_vfx_; }
    Shader& phaser_shader() noexcept     { return *phaser_; }
    Shader& bridge_shader() noexcept     { return *bridge_; }
    Shader& lightmap_shader() noexcept   { return *lightmap_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
    std::unique_ptr<Shader> dust_;
    std::unique_ptr<Shader> shield_;
    std::unique_ptr<Shader> lens_flare_;
    std::unique_ptr<Shader> torpedo_;
    std::unique_ptr<Shader> hit_vfx_;
    std::unique_ptr<Shader> phaser_;
    std::unique_ptr<Shader> bridge_;
    std::unique_ptr<Shader> lightmap_;
};

}  // namespace renderer
