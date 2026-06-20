// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include "embedded_opaque_vs.h"
#include "embedded_opaque_fs.h"
#include "embedded_skinned_vs.h"
#include "embedded_backdrop_vs.h"
#include "embedded_backdrop_fs.h"
#include "embedded_sun_vs.h"
#include "embedded_sun_fs.h"
#include "embedded_sun_flare_vs.h"
#include "embedded_sun_flare_fs.h"
#include "embedded_dust_vs.h"
#include "embedded_dust_fs.h"
#include "embedded_shield_vs.h"
#include "embedded_shield_fs.h"
#include "embedded_lens_flare_vs.h"
#include "embedded_lens_flare_fs.h"
#include "embedded_torpedo_vs.h"
#include "embedded_torpedo_fs.h"
#include "embedded_hit_vfx_vs.h"
#include "embedded_hit_vfx_fs.h"
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

namespace renderer {

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    skinned_ = std::make_unique<Shader>(shader_src::skinned_vs, shader_src::opaque_fs);
    backdrop_ = std::make_unique<Shader>(shader_src::backdrop_vs, shader_src::backdrop_fs);
    sun_ = std::make_unique<Shader>(shader_src::sun_vs, shader_src::sun_fs);
    sun_flare_ = std::make_unique<Shader>(shader_src::sun_flare_vs, shader_src::sun_flare_fs);
    dust_ = std::make_unique<Shader>(shader_src::dust_vs, shader_src::dust_fs);
    shield_ = std::make_unique<Shader>(shader_src::shield_vs, shader_src::shield_fs);
    lens_flare_ = std::make_unique<Shader>(shader_src::lens_flare_vs, shader_src::lens_flare_fs);
    torpedo_    = std::make_unique<Shader>(shader_src::torpedo_vs,    shader_src::torpedo_fs);
    hit_vfx_    = std::make_unique<Shader>(shader_src::hit_vfx_vs,    shader_src::hit_vfx_fs);
    phaser_        = std::make_unique<Shader>(shader_src::phaser_vs,        shader_src::phaser_fs);
    hologram_      = std::make_unique<Shader>(shader_src::hologram_vs,      shader_src::hologram_fs);
    breach_        = std::make_unique<Shader>(shader_src::breach_vs,        shader_src::breach_fs);
    subsystem_pin_ = std::make_unique<Shader>(shader_src::subsystem_pin_vs, shader_src::subsystem_pin_fs);
    target_reticle_ = std::make_unique<Shader>(shader_src::target_reticle_vs, shader_src::target_reticle_fs);
    bridge_        = std::make_unique<Shader>(shader_src::bridge_vs,        shader_src::bridge_fs);
    skinned_bridge_ = std::make_unique<Shader>(shader_src::skinned_bridge_vs, shader_src::bridge_fs);
    lightmap_   = std::make_unique<Shader>(shader_src::lightmap_vs,   shader_src::lightmap_fs);
    viewscreen_static_ = std::make_unique<Shader>(
        shader_src::viewscreen_static_vs, shader_src::viewscreen_static_fs);
    shadow_depth_ = std::make_unique<Shader>(
        shader_src::shadow_vs, shader_src::shadow_fs);
    shockwave_ = std::make_unique<Shader>(shader_src::shockwave_vs,
                                          shader_src::shockwave_fs);
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
