// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include "renderer/gl_caps.h"

#include <assets/texture.h>

#include <fstream>
#include <iterator>
#include <span>
#include <vector>

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
#include "embedded_subsystem_pin_vs.h"
#include "embedded_subsystem_pin_fs.h"
#include "embedded_target_reticle_vs.h"
#include "embedded_target_reticle_fs.h"
#include "embedded_bridge_vs.h"
#include "embedded_bridge_fs.h"
#include "embedded_skinned_bridge_vs.h"
#include "embedded_lightmap_vs.h"
#include "embedded_lightmap_fs.h"
#include "embedded_opaque_deform_vs.h"
#include "embedded_opaque_deform_tcs.h"
#include "embedded_opaque_deform_tes.h"

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
    subsystem_pin_ = std::make_unique<Shader>(shader_src::subsystem_pin_vs, shader_src::subsystem_pin_fs);
    target_reticle_ = std::make_unique<Shader>(shader_src::target_reticle_vs, shader_src::target_reticle_fs);
    bridge_        = std::make_unique<Shader>(shader_src::bridge_vs,        shader_src::bridge_fs);
    skinned_bridge_ = std::make_unique<Shader>(shader_src::skinned_bridge_vs, shader_src::bridge_fs);
    lightmap_   = std::make_unique<Shader>(shader_src::lightmap_vs,   shader_src::lightmap_fs);
    // Hull-deformation tessellation program (GL 4.0+). Reuses opaque.frag as
    // the fragment stage (the TES emits the matching varyings). Falls back to
    // the static opaque path when tessellation is unavailable (spec §8).
    tessellation_available_ = query_gl_caps().tessellation_available;
    if (tessellation_available_) {
        deform_ = std::make_unique<Shader>(shader_src::opaque_deform_vs,
                                           shader_src::opaque_deform_tcs,
                                           shader_src::opaque_deform_tes,
                                           shader_src::opaque_fs);
    }
    // Shared hull-damage interior texture for gouge shading. Loaded once; bound
    // to unit 3 per ship draw. game/ is gitignored (absent in CI) — fall back
    // silently to no texture (gouges then sample the unit-3 black fallback).
    try {
        std::ifstream in("game/data/Textures/Effects/Damage.tga", std::ios::binary);
        if (in) {
            std::vector<std::uint8_t> bytes(
                (std::istreambuf_iterator<char>(in)),
                std::istreambuf_iterator<char>());
            assets::Image img = assets::decode_tga(
                std::span<const std::uint8_t>(bytes));
            damage_texture_ =
                std::make_unique<assets::Texture>(assets::upload_image(img, true));
        }
    } catch (const std::exception&) {
        damage_texture_.reset();  // decode/upload failure -> no gouge texture
    }

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    // NIFs come from Gamebryo/NetImmerse, which targeted Direct3D first;
    // BC's triangle indices are wound clockwise for front-facing triangles
    // (D3D default). With glFrontFace(GL_CCW) — OpenGL's default — every
    // front face would be culled and only the back faces drawn, which from
    // outside the model looks like the inside of the hull (the original
    // "inside-out" report).
    glFrontFace(GL_CW);
}

}  // namespace renderer
