// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <string>

#include <glad/glad.h>

#include "embedded_opaque_vs.h"
#include "embedded_opaque_fs.h"
#include "embedded_skinned_vs.h"
#include "embedded_minor_vs.h"
#include "embedded_impostor_vs.h"
#include "embedded_speck_vs.h"
#include "embedded_speck_fs.h"
#include "embedded_rock_speck_vs.h"
#include "embedded_rock_speck_fs.h"
#include "embedded_far_haze_fs.h"
#include "embedded_backdrop_vs.h"
#include "embedded_backdrop_fs.h"
#include "embedded_sun_vs.h"
#include "embedded_sun_fs.h"
#include "embedded_sun_flare_vs.h"
#include "embedded_sun_flare_fs.h"
#include "embedded_dust_vs.h"
#include "embedded_dust_fs.h"
#include "embedded_nebula_vs.h"
#include "embedded_nebula_fs.h"
#include "embedded_nebula_shell_vs.h"
#include "embedded_nebula_shell_fs.h"
#include "embedded_nebula_volumetric_vs.h"
#include "embedded_nebula_volumetric_fs.h"
#include "embedded_nebula_upsample_fs.h"
#include "embedded_system_nebula_fs.h"
#include "embedded_nebula_godray_vs.h"
#include "embedded_nebula_godray_fs.h"
#include "embedded_shield_vs.h"
#include "embedded_shield_fs.h"
#include "embedded_lens_flare_vs.h"
#include "embedded_lens_flare_fs.h"
#include "embedded_torpedo_vs.h"
#include "embedded_torpedo_fs.h"
#include "embedded_disruptor_vs.h"
#include "embedded_disruptor_fs.h"
#include "embedded_hit_vfx_vs.h"
#include "embedded_hit_vfx_fs.h"
#include "embedded_hull_discharge_vs.h"
#include "embedded_hull_discharge_fs.h"
#include "embedded_nebula_wake_vs.h"
#include "embedded_nebula_wake_fs.h"
#include "embedded_phaser_vs.h"
#include "embedded_phaser_fs.h"
#include "embedded_hologram_vs.h"
#include "embedded_hologram_fs.h"
#include "embedded_breach_vs.h"
#include "embedded_breach_fs.h"
#include "embedded_subsystem_pin_vs.h"
#include "embedded_subsystem_pin_fs.h"
#include "embedded_target_reticle_vs.h"
#include "embedded_target_reticle_fs.h"
#include "embedded_starmap_vs.h"
#include "embedded_starmap_fs.h"
#include "embedded_bridge_vs.h"
#include "embedded_bridge_fs.h"
#include "embedded_skinned_bridge_vs.h"
#include "embedded_lightmap_vs.h"
#include "embedded_lightmap_fs.h"
#include "embedded_viewscreen_static_vs.h"
#include "embedded_viewscreen_static_fs.h"
#include "embedded_shadow_vs.h"
#include "embedded_shadow_fs.h"
#include "embedded_shockwave_vs.h"
#include "embedded_shockwave_fs.h"
#include "embedded_skybox_vs.h"
#include "embedded_skybox_fs.h"
#include "embedded_cloak_refraction_vs.h"
#include "embedded_cloak_refraction_fs.h"

namespace renderer {

namespace {
// `src` with "#define <name> 1" inserted right after its #version line.
std::string with_define(const char* src, const char* name) {
    std::string out(src);
    const std::size_t eol = out.find('\n');
    out.insert(eol == std::string::npos ? out.size() : eol + 1,
               std::string("#define ") + name + " 1\n");
    return out;
}
}  // namespace

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    skinned_ = std::make_unique<Shader>(shader_src::skinned_vs, shader_src::opaque_fs);
    // Minor rocks: per-instance model matrix, the SAME opaque.frag (minor-rocks
    // spec §2), so its fixed sampler units are assigned with opaque's below.
    minor_ = std::make_unique<Shader>(shader_src::minor_vs, shader_src::opaque_fs);
    // Far-tier impostors: a quad per instance, the SAME opaque.frag (far-tier
    // spec §3), so its fixed sampler units are assigned with opaque's too.
    // Rock-blend (2026-10-03): compiled with IMPOSTOR_VIEWS, which adds the
    // blended multi-view sampling; every other program compiles the
    // unchanged source.
    impostor_ = std::make_unique<Shader>(shader_src::impostor_vs,
                                         with_define(shader_src::opaque_fs, "IMPOSTOR_VIEWS"));
    // opaque.frag's collision-scuff normal map (renderer/scuff_texture.h)
    // lives on unit 7 for the program's whole life. Assigned HERE, once, not
    // per draw: every path that draws with this program (draw_model, the
    // carve-stencil pass, the hull-clip / cloak parity test rigs) would
    // otherwise leave it at unit 0 with the base texture. Harmless for two
    // sampler2Ds, but the predecessor was a samplerBuffer and two sampler
    // TYPES on one unit is GL_INVALID_OPERATION at draw -- keep the habit.
    // Same for the hull-decal masks: u_decal_mask0..3 live on units 8..11
    // (draw_model binds the textures there once per model, frame.cc).
    for (Shader* sh : {opaque_.get(), skinned_.get(), minor_.get(), impostor_.get()}) {
        sh->use();
        sh->set_int("u_scuff_map", 7);
        sh->set_int("u_decal_mask0", 8);
        sh->set_int("u_decal_mask1", 9);
        sh->set_int("u_decal_mask2", 10);
        sh->set_int("u_decal_mask3", 11);
    }
    // Far-tier specks: a lit, area-weighted screen quad per sub-1.5-px rock.
    speck_ = std::make_unique<Shader>(shader_src::speck_vs, shader_src::speck_fs);
    rock_speck_ = std::make_unique<Shader>(shader_src::rock_speck_vs, shader_src::rock_speck_fs);
    // Far-tier belt haze: the fullscreen-triangle vertex shader (outputs v_uv).
    far_haze_ = std::make_unique<Shader>(shader_src::nebula_volumetric_vs, shader_src::far_haze_fs);
    backdrop_ = std::make_unique<Shader>(shader_src::backdrop_vs, shader_src::backdrop_fs);
    sun_ = std::make_unique<Shader>(shader_src::sun_vs, shader_src::sun_fs);
    sun_flare_ = std::make_unique<Shader>(shader_src::sun_flare_vs, shader_src::sun_flare_fs);
    dust_ = std::make_unique<Shader>(shader_src::dust_vs, shader_src::dust_fs);
    nebula_ = std::make_unique<Shader>(shader_src::nebula_vs, shader_src::nebula_fs);
    nebula_shell_ = std::make_unique<Shader>(shader_src::nebula_shell_vs, shader_src::nebula_shell_fs);
    nebula_volumetric_ = std::make_unique<Shader>(shader_src::nebula_volumetric_vs, shader_src::nebula_volumetric_fs);
    // The upsample reuses the fullscreen-triangle vertex shader (outputs v_uv).
    nebula_upsample_ = std::make_unique<Shader>(shader_src::nebula_volumetric_vs, shader_src::nebula_upsample_fs);
    // System-scale nebula haze: same fullscreen-triangle vertex shader.
    system_nebula_ = std::make_unique<Shader>(shader_src::nebula_volumetric_vs, shader_src::system_nebula_fs);
    nebula_godray_ = std::make_unique<Shader>(shader_src::nebula_godray_vs, shader_src::nebula_godray_fs);
    shield_ = std::make_unique<Shader>(shader_src::shield_vs, shader_src::shield_fs);
    lens_flare_ = std::make_unique<Shader>(shader_src::lens_flare_vs, shader_src::lens_flare_fs);
    torpedo_    = std::make_unique<Shader>(shader_src::torpedo_vs,    shader_src::torpedo_fs);
    disruptor_  = std::make_unique<Shader>(shader_src::disruptor_vs,  shader_src::disruptor_fs);
    hit_vfx_    = std::make_unique<Shader>(shader_src::hit_vfx_vs,    shader_src::hit_vfx_fs);
    hull_discharge_ = std::make_unique<Shader>(shader_src::hull_discharge_vs, shader_src::hull_discharge_fs);
    nebula_wake_ = std::make_unique<Shader>(shader_src::nebula_wake_vs, shader_src::nebula_wake_fs);
    phaser_        = std::make_unique<Shader>(shader_src::phaser_vs,        shader_src::phaser_fs);
    hologram_      = std::make_unique<Shader>(shader_src::hologram_vs,      shader_src::hologram_fs);
    breach_        = std::make_unique<Shader>(shader_src::breach_vs,        shader_src::breach_fs);
    subsystem_pin_ = std::make_unique<Shader>(shader_src::subsystem_pin_vs, shader_src::subsystem_pin_fs);
    target_reticle_ = std::make_unique<Shader>(shader_src::target_reticle_vs, shader_src::target_reticle_fs);
    starmap_       = std::make_unique<Shader>(shader_src::starmap_vs,        shader_src::starmap_fs);
    bridge_        = std::make_unique<Shader>(shader_src::bridge_vs,        shader_src::bridge_fs);
    skinned_bridge_ = std::make_unique<Shader>(shader_src::skinned_bridge_vs, shader_src::bridge_fs);
    lightmap_   = std::make_unique<Shader>(shader_src::lightmap_vs,   shader_src::lightmap_fs);
    viewscreen_static_ = std::make_unique<Shader>(
        shader_src::viewscreen_static_vs, shader_src::viewscreen_static_fs);
    shadow_depth_ = std::make_unique<Shader>(
        shader_src::shadow_vs, shader_src::shadow_fs);
    shockwave_ = std::make_unique<Shader>(shader_src::shockwave_vs,
                                          shader_src::shockwave_fs);
    skybox_ = std::make_unique<Shader>(shader_src::skybox_vs, shader_src::skybox_fs);
    cloak_refraction_ = std::make_unique<Shader>(
        shader_src::cloak_refraction_vs, shader_src::cloak_refraction_fs);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    // NIFs come from Gamebryo/NetImmerse, which targeted Direct3D first; BC's
    // triangle indices are wound clockwise for front-facing triangles (D3D
    // default). Ship model matrices are now right-handed (det > 0, no
    // reflection — see host_loop._world_matrix_from / AlignToVectors), so a
    // CW-wound NIF presents CCW front faces in screen space. Front-facing is
    // therefore GL_CCW. (Was GL_CW back when every model matrix was reflected
    // to det < 0; see docs/superpowers/plans/2026-06-18-render-handedness-
    // unmirror.md.)
    glFrontFace(GL_CCW);
}

}  // namespace renderer
