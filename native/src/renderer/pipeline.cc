// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include "embedded_opaque_vs.h"
#include "embedded_opaque_fs.h"
#include "embedded_backdrop_vs.h"
#include "embedded_backdrop_fs.h"
#include "embedded_sun_vs.h"
#include "embedded_sun_fs.h"
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
#include "embedded_bridge_vs.h"
#include "embedded_bridge_fs.h"
#include "embedded_lightmap_vs.h"
#include "embedded_lightmap_fs.h"

namespace renderer {

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    backdrop_ = std::make_unique<Shader>(shader_src::backdrop_vs, shader_src::backdrop_fs);
    sun_ = std::make_unique<Shader>(shader_src::sun_vs, shader_src::sun_fs);
    dust_ = std::make_unique<Shader>(shader_src::dust_vs, shader_src::dust_fs);
    shield_ = std::make_unique<Shader>(shader_src::shield_vs, shader_src::shield_fs);
    lens_flare_ = std::make_unique<Shader>(shader_src::lens_flare_vs, shader_src::lens_flare_fs);
    torpedo_    = std::make_unique<Shader>(shader_src::torpedo_vs,    shader_src::torpedo_fs);
    hit_vfx_    = std::make_unique<Shader>(shader_src::hit_vfx_vs,    shader_src::hit_vfx_fs);
    phaser_     = std::make_unique<Shader>(shader_src::phaser_vs,     shader_src::phaser_fs);
    bridge_     = std::make_unique<Shader>(shader_src::bridge_vs,     shader_src::bridge_fs);
    lightmap_   = std::make_unique<Shader>(shader_src::lightmap_vs,   shader_src::lightmap_fs);
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
