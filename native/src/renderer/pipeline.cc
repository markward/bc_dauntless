// native/src/renderer/pipeline.cc
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include "embedded_opaque_vs.h"
#include "embedded_opaque_fs.h"
#include "embedded_backdrop_vs.h"
#include "embedded_backdrop_fs.h"
#include "embedded_sun_vs.h"
#include "embedded_sun_fs.h"

namespace renderer {

Pipeline::Pipeline() {
    opaque_ = std::make_unique<Shader>(shader_src::opaque_vs, shader_src::opaque_fs);
    backdrop_ = std::make_unique<Shader>(shader_src::backdrop_vs, shader_src::backdrop_fs);
    sun_ = std::make_unique<Shader>(shader_src::sun_vs, shader_src::sun_fs);
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
