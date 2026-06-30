// native/src/renderer/include/renderer/pipeline.h
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept     { return *opaque_; }
    Shader& skinned_shader() noexcept    { return *skinned_; }
    Shader& backdrop_shader() noexcept   { return *backdrop_; }
    Shader& sun_shader() noexcept        { return *sun_; }
    Shader& sun_flare_shader() noexcept  { return *sun_flare_; }
    Shader& dust_shader() noexcept       { return *dust_; }
    Shader& nebula_shader() noexcept       { return *nebula_; }
    Shader& nebula_shell_shader() noexcept { return *nebula_shell_; }
    Shader& nebula_volumetric_shader() noexcept { return *nebula_volumetric_; }
    Shader& nebula_upsample_shader() noexcept { return *nebula_upsample_; }
    Shader& nebula_godray_shader() noexcept { return *nebula_godray_; }
    Shader& shield_shader() noexcept     { return *shield_; }
    Shader& lens_flare_shader() noexcept { return *lens_flare_; }
    Shader& torpedo_shader() noexcept    { return *torpedo_; }
    Shader& hit_vfx_shader() noexcept    { return *hit_vfx_; }
    Shader& hull_discharge_shader() noexcept { return *hull_discharge_; }
    Shader& nebula_wake_shader() noexcept { return *nebula_wake_; }
    Shader& phaser_shader() noexcept          { return *phaser_; }
    Shader& hologram_shader() noexcept        { return *hologram_; }
    Shader& breach_shader() noexcept          { return *breach_; }
    Shader& subsystem_pin_shader() noexcept   { return *subsystem_pin_; }
    Shader& target_reticle_shader() noexcept  { return *target_reticle_; }
    Shader& bridge_shader() noexcept          { return *bridge_; }
    Shader& skinned_bridge_shader() noexcept  { return *skinned_bridge_; }
    Shader& lightmap_shader() noexcept        { return *lightmap_; }
    Shader& viewscreen_static_shader() noexcept { return *viewscreen_static_; }
    Shader& shadow_depth_shader() noexcept    { return *shadow_depth_; }
    Shader& shockwave_shader() noexcept       { return *shockwave_; }
    Shader& skybox_shader() noexcept          { return *skybox_; }
    Shader& cloak_refraction_shader() noexcept { return *cloak_refraction_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> skinned_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
    std::unique_ptr<Shader> sun_flare_;
    std::unique_ptr<Shader> dust_;
    std::unique_ptr<Shader> nebula_;
    std::unique_ptr<Shader> nebula_shell_;
    std::unique_ptr<Shader> nebula_volumetric_;
    std::unique_ptr<Shader> nebula_upsample_;
    std::unique_ptr<Shader> nebula_godray_;
    std::unique_ptr<Shader> shield_;
    std::unique_ptr<Shader> lens_flare_;
    std::unique_ptr<Shader> torpedo_;
    std::unique_ptr<Shader> hit_vfx_;
    std::unique_ptr<Shader> hull_discharge_;
    std::unique_ptr<Shader> nebula_wake_;
    std::unique_ptr<Shader> phaser_;
    std::unique_ptr<Shader> hologram_;
    std::unique_ptr<Shader> breach_;
    std::unique_ptr<Shader> subsystem_pin_;
    std::unique_ptr<Shader> target_reticle_;
    std::unique_ptr<Shader> bridge_;
    std::unique_ptr<Shader> skinned_bridge_;
    std::unique_ptr<Shader> lightmap_;
    std::unique_ptr<Shader> viewscreen_static_;
    std::unique_ptr<Shader> shadow_depth_;
    std::unique_ptr<Shader> shockwave_;
    std::unique_ptr<Shader> skybox_;
    std::unique_ptr<Shader> cloak_refraction_;
};

}  // namespace renderer
