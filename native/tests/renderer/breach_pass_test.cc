// native/tests/renderer/breach_pass_test.cc
//
// Tests for the breach interior pass (raymarched-breach-interior Task 3,
// round 3), which draws the REAL hull mesh under the carve stencil instead
// of a synthetic proxy (round 1: a per-carve sphere; round 2: a per-instance
// box plus an entry search). A fragment reaching breach.frag's main() now
// sits, by construction, exactly on the hull surface at a point the damage
// field already reads as carved -- the SAME condition that made the opaque
// pass discard it and the stencil pass mark it 1 -- so there is no search:
// raymarch_breach_cavity marches straight from there to the cavity's far
// wall. This file exercises that through the REAL production shader/GL
// path: BreachPass::draw_instance() takes an already-built
// InstanceFieldCache::Entry (packed by hand here from a voxel::DistanceField,
// exactly the shape InstanceFieldCache::get() would hand back in production)
// plus the original hull fill and a small hand-built assets::Model (one
// node, one uploaded quad mesh standing in for "a patch of hull surface"),
// and issues real GL draws whose PIXELS are read back and asserted on -- not
// a hand re-derivation of the shader's own logic.
//
// SCALE: every carved field cell here is placed using REAL carve geometry
// where the test is ABOUT geometry (see NarrowRealisticCarveCavityStillRenders
// below) -- MIN_CARVE_RADIUS_GU / hull_carve_strength_to_radius_gu
// (engine/appc/hull_carve.py) put a real carve's radius at 3-30 model units,
// and field_brush.h's kCarveDepthFactor=0.45 (centred ON the hull surface,
// so the FULL along-normal extent is 2x that, 0.9x radius) puts a real
// carve's along-normal depth at 2.7-27 model units. A round-2 fix to this
// same file sized test fields against an IMPLEMENTATION constant
// (kBreachCoarseStride) rather than real carve geometry, and a review
// caught that as backwards: the test should prove the implementation
// handles real carves, not prove the implementation handles inputs shaped
// like itself.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/breach_pass.h>
#include <renderer/carve_field_cache.h>
#include <renderer/instance_field_cache.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <assets/mesh.h>
#include <assets/model.h>

#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>
#include <voxel/volume.h>

#include <array>
#include <cmath>
#include <cstdint>
#include <memory>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

// ── Fill volumes ─────────────────────────────────────────────────────────

// Solid (127) everywhere in x,y=[-20,20], z=[-30,60]: comfortably covers
// every hit_point this file's fields ever raymarch to.
voxel::VoxelVolume solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 9};
    v.origin = {-20.f, -20.f, -30.f};
    v.cell   = {10.f, 10.f, 10.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 9), 127);
    return v;
}

// Empty (0) over the same box as solid_fill(): every fragment's backing
// check fails.
voxel::VoxelVolume empty_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 9};
    v.origin = {-20.f, -20.f, -30.f};
    v.cell   = {10.f, 10.f, 10.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 9), 0);
    return v;
}

// 75 (just above kIsovalue=64, inside the rim band) over the same box as
// solid_fill().
voxel::VoxelVolume rim_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 9};
    v.origin = {-20.f, -20.f, -30.f};
    v.cell   = {10.f, 10.f, 10.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 9), 75);
    return v;
}

// Solid (127) in ONLY a single 3-unit-thick z-slice, z in [12,15] -- right
// at make_single_cavity_field()'s own carved band's HIGH-z (entry) edge --
// for the floating-hit test below. hit_point (the far/EXIT crossing, near
// z=0 -- see that field's own comment) sits nowhere near this slice.
voxel::VoxelVolume thin_plate_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 1};
    v.origin = {-20.f, -20.f, 12.f};
    v.cell   = {10.f, 10.f, 3.f};
    v.occ.assign(4 * 4 * 1, 127);
    return v;
}

// Solid (127) everywhere across the multi-site field below (x,y in
// [-20,20], z in [-10,760] -- make_multi_site_field(30)'s own box tops out
// at 30*25=750).
voxel::VoxelVolume wide_solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 77};
    v.origin = {-20.f, -20.f, -10.f};
    v.cell   = {10.f, 10.f, 10.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 77), 127);
    return v;
}

// ── Damage fields (voxel::DistanceField, hand-built for exact analytic
// control over which cells are "carved" — the same technique
// breach_raymarch_test.cc's make_slab_field uses, duplicated here per this
// project's per-file test convention; see instance_field_cache_test.cc's own
// header comment for that convention). Every (x,y) at a given Z slice gets
// the same value: a pure single-axis slab. ──────────────────────────────

voxel::DistanceField make_z_slab_field(glm::ivec3 dims, glm::vec3 origin, glm::vec3 cell,
                                       const std::vector<std::int8_t>& z_values) {
    voxel::DistanceField f;
    f.dims   = dims;
    f.origin = origin;
    f.cell   = cell;
    f.scale  = 1.0f;
    f.dist.assign(static_cast<std::size_t>(dims.x) * dims.y * dims.z, 0);
    for (int z = 0; z < dims.z; ++z) {
        for (int y = 0; y < dims.y; ++y) {
            for (int x = 0; x < dims.x; ++x) {
                f.dist[f.index(x, y, z)] = z_values.at(static_cast<std::size_t>(z));
            }
        }
    }
    return f;
}

// ONE bounded cavity: cell=5, intact (idx 0-1, body z in [-10,0]), CARVED
// (idx 2-4, body z in [0,15]), intact (idx 5-6, body z in [15,25]). Box:
// x,y in [-10,10], z in [-10,25].
//
// Reused by BOTH the "single cavity" tests (solid/empty/rim fill covering
// the whole box) and the "floating hit" tests (a fill covering only part of
// it) -- it is the SAME field either way; only the fill and the question
// asked of hit_point differ. kCavitySurfaceCenter (below) sits mid-band;
// the mesh patch's own vertex position there is the raymarch's `ro` (no
// entry search any more -- see this file's header comment), and
// raymarch_breach_cavity marches -Z (into the "intact before" region,
// AWAY from the camera which sits at +Z) to find the EXIT crossing near
// z=0 (between idx2's carved cell and idx1's intact one) -- this is
// hit_point for every test using this field.
voxel::DistanceField make_single_cavity_field() {
    const std::vector<std::int8_t> z_values = {
        -100, -100,        // idx 0-1: intact,  z in [-10, 0]
         100,  100,  100,  // idx 2-4: CARVED,  z in [  0,15]
        -100, -100,        // idx 5-6: intact,  z in [ 15,25]
    };
    return make_z_slab_field(glm::ivec3(4, 4, 7), glm::vec3(-10.0f, -10.0f, -10.0f),
                             glm::vec3(5.0f), z_values);
}

// Mid-band point of make_single_cavity_field()'s carved region (x,y=0,
// z=7.5 -- the middle of [0,15]). This IS the raymarch's `ro`: round 3 has
// no entry search, so the mesh patch placed here (see make_surface_patch_
// model below) is what the fragment shader starts marching from.
constexpr glm::vec3 kCavitySurfaceCenter(0.0f, 0.0f, 7.5f);

// `n` independent damage sites along Z, each a 3-cell carved band (idx
// 5*i+2 .. 5*i+4) preceded by 2 cells (10 model units) of untouched field,
// period 5 cells = 25 model units: site i's carved z-range is
// [25*i+10, 25*i+25]. Box: x,y in [-10,10], z in [0, 25*n].
//
// n=30 is used deliberately, not an arbitrary "a lot": scenegraph::
// HullCarveField::kMaxCarves is 24, so a field encoding 30 independent
// sites -- built here with NO HullCarveField anywhere in this file, since
// draw_instance()'s signature does not take one -- is structurally beyond
// anything a 24-slot sphere ring could ever represent, by construction
// rather than by argument.
//
// Round 3 needs no "reach" margin here (round 2's version did, and a review
// found even THAT was tuned to an implementation constant rather than real
// geometry -- see this file's header comment): the mesh patch is placed
// EXACTLY where the test means the ray to start, so there is nothing for a
// search budget to fail to reach.
voxel::DistanceField make_multi_site_field(int n) {
    const int period = 5;
    const int dims_z = period * n;
    std::vector<std::int8_t> z_values(static_cast<std::size_t>(dims_z), -100);
    for (int i = 0; i < n; ++i) {
        z_values[static_cast<std::size_t>(period * i + 2)] = 100;
        z_values[static_cast<std::size_t>(period * i + 3)] = 100;
        z_values[static_cast<std::size_t>(period * i + 4)] = 100;
    }
    return make_z_slab_field(glm::ivec3(4, 4, dims_z), glm::vec3(0.0f), glm::vec3(5.0f),
                             z_values);
}

// Body-frame Z centre of multi-site field site `i`'s MIDDLE carved cell
// (5*i+3), matching make_multi_site_field's own layout above.
float multi_site_z(int i) {
    return (5.0f * static_cast<float>(i) + 3.5f) * 5.0f;
}

// Body-frame Z centre of an UNTOUCHED cell (5*i, always -100) in site i's
// own "before" gap. Used by the negative control below: raymarch_breach_
// cavity's OWN precondition (sample_hull_field(ro) > margin) rejects a ray
// that starts here immediately -- no search, no reach, nothing to tune.
float multi_site_gap_z(int i) {
    return (5.0f * static_cast<float>(i) + 0.5f) * 5.0f;
}

// A carved region sized from REAL carve geometry, not from an
// implementation constant -- the review-round-3 requirement. cell=3 (a
// realistic field cell -- BC's authored cell runs 3.0-7.5 model units
// across the fleet, docs/engine/damagetool-and-hull-damage-gaps.md), ONE
// carved cell (idx 1, body z in [-1.5,1.5] -- 3 model units wide). That is
// close to the SMALLEST real carve's own along-normal extent:
// MIN_CARVE_RADIUS_GU=0.25 GU=25 model units is the floor for carves that
// carry their own authored size (not combat hits, which floor at 0), but
// hull_carve_strength_to_radius_gu's combat floor is 0.03 GU=3 model units
// at the iso -- 0.9 * 3 = 2.7 model units of along-normal extent
// (field_brush.h's kCarveDepthFactor=0.45, centred ON the surface, so the
// FULL extent is 2x that). 3 model units (this field's one carved cell) is
// the closest a whole-cell-quantised field can get to that 2.7 target
// without going narrower than raymarch_breach_cavity's own fine step
// (0.5*cell=1.5) can resolve at all. Box: x,y in [-10,10], z in [-4.5,4.5].
voxel::DistanceField make_narrow_realistic_cavity_field() {
    const std::vector<std::int8_t> z_values = {-100, 100, -100};
    return make_z_slab_field(glm::ivec3(4, 4, 3), glm::vec3(-10.0f, -10.0f, -4.5f),
                             glm::vec3(3.0f), z_values);
}

// Centre of make_narrow_realistic_cavity_field()'s one carved cell.
constexpr glm::vec3 kNarrowCavitySurfaceCenter(0.0f, 0.0f, 0.0f);

// Pack `f` into a GL_R8 2D atlas exactly as InstanceFieldCache::upload()
// does (voxel::pack_field_to_atlas / atlas_layout_for), returning a
// caller-owned texture id. Duplicated from breach_raymarch_test.cc's own
// upload_field_atlas rather than shared — this project's per-file test
// convention (see instance_field_cache_test.cc's header comment) — with one
// difference: this version does not pin a specific texture unit, since
// BreachPass::draw_instance() binds field.tex2d to its own unit (2) when it
// draws; nothing here needs to leave it bound anywhere in particular.
GLuint upload_field_atlas_tex(const voxel::DistanceField& f, voxel::AtlasLayout& layout_out) {
    layout_out = voxel::atlas_layout_for(f.dims);
    const std::vector<std::uint8_t> pixels = voxel::pack_field_to_atlas(f, layout_out);

    GLint prev_bound = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev_bound);

    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    GLint prev_unpack = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev_unpack);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, layout_out.width, layout_out.height, 0,
                GL_RED, GL_UNSIGNED_BYTE, pixels.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, prev_unpack);
    glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(prev_bound));
    return tex;
}

// Build a minimal assets::Model standing in for "a patch of hull surface":
// one node, one small quad (2 triangles) centred at `center`, in the plane
// perpendicular to `normal` (the direction the camera approaches from --
// see cam_facing below), wound CCW as seen from `normal`'s side so it
// survives this pass's glFrontFace(GL_CCW) + glCullFace(GL_BACK) -- the same
// convention the opaque pass draws real hull meshes under (pipeline.cc).
//
// `node_xf` is the model's single node's local_transform. The vertices are
// emitted PRE-multiplied by its inverse, so the composed body-frame geometry
// (node_xf * a_pos, what draw_model_positions_only feeds the shader through
// u_model) is identical for every node_xf -- which is exactly what
// NonIdentityNodeTransformRendersIdenticallyToIdentity below relies on.
// `half_size` should be large enough that the pixels read_center()/
// read_inner_max() sample land on it at the test's camera distance.
assets::Model make_surface_patch_model(glm::vec3 center, glm::vec3 normal, float half_size,
                                       const glm::mat4& node_xf = glm::mat4(1.0f)) {
    normal = glm::normalize(normal);
    const glm::vec3 ref = (std::fabs(normal.z) < 0.9f) ? glm::vec3(0.f, 0.f, 1.f)
                                                        : glm::vec3(1.f, 0.f, 0.f);
    const glm::vec3 u = glm::normalize(glm::cross(ref, normal));
    const glm::vec3 v = glm::cross(normal, u);  // cross(u, v) == normal (u is unit length)

    assets::MeshCpu cpu;
    const glm::vec3 p00 = center - half_size * u - half_size * v;
    const glm::vec3 p01 = center - half_size * u + half_size * v;
    const glm::vec3 p10 = center + half_size * u - half_size * v;
    const glm::vec3 p11 = center + half_size * u + half_size * v;
    // Store vertices NODE-LOCAL: node_xf * stored == the body-frame point
    // above, whatever node_xf is. With the default identity the stored
    // positions are the body-frame ones unchanged.
    const glm::mat4 node_inv = glm::inverse(node_xf);
    for (const glm::vec3& p : {p00, p01, p10, p11}) {
        assets::MeshCpu::Vertex vert;
        vert.position = glm::vec3(node_inv * glm::vec4(p, 1.0f));
        vert.normal   = normal;
        cpu.vertices.push_back(vert);
    }
    // p00=0, p01=1, p10=2, p11=3. CCW-from-outside: (p00,p11,p01), (p00,p10,p11).
    cpu.indices = {0, 3, 1, 0, 2, 3};

    assets::Model m;
    m.meshes.push_back(assets::upload_mesh(cpu));
    assets::Node node;
    node.parent_index    = -1;
    node.local_transform = node_xf;
    node.meshes          = {0};
    m.nodes.push_back(node);
    m.root_node = 0;
    return m;
}

// Two parallel sheets of hull, the minimum geometry that can express "you are
// looking THROUGH a hole in the near plating at the far plating" -- which
// make_surface_patch_model's single quad structurally cannot, because its only
// back face is CO-PLANAR with its own front face.
//
// `near_center` faces +normal (toward the camera: a front face under this
// pass's glFrontFace(GL_CCW) + cull BACK, the sheet the carve cut through).
// `far_center` faces -normal (AWAY from the camera), so from the camera's side
// it is a BACK face -- culled by the opaque pass and by the scoop, and drawn
// ONLY by the interior shell. That asymmetry is the whole point: a real BC
// hull is a single-sided shell, so once the near sheet is discarded there is
// nothing left in front of the skybox unless something draws that back face.
assets::Model make_two_plate_model(glm::vec3 near_center, glm::vec3 far_center,
                                   glm::vec3 normal, float half_size) {
    normal = glm::normalize(normal);
    assets::Model near_m = make_surface_patch_model(near_center,  normal, half_size);
    assets::Model far_m  = make_surface_patch_model(far_center,  -normal, half_size);

    assets::Model m;
    m.meshes.push_back(std::move(near_m.meshes[0]));
    m.meshes.push_back(std::move(far_m.meshes[0]));
    assets::Node node;
    node.parent_index    = -1;
    node.local_transform = glm::mat4(1.0f);
    node.meshes          = {0, 1};
    m.nodes.push_back(node);
    m.root_node = 0;
    return m;
}

class BreachPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;
    std::vector<GLuint>                 field_textures_;  // freed in TearDown

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "breach-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    void TearDown() override {
        for (GLuint t : field_textures_) {
            if (t) glDeleteTextures(1, &t);
        }
        field_textures_.clear();
    }

    // Build a real InstanceFieldCache::Entry from `f`, uploading its atlas
    // and tracking the texture for cleanup. Mirrors exactly what
    // InstanceFieldCache::get() hands back in production (same fields,
    // same packing) — see instance_field_cache.h's Entry doc.
    renderer::InstanceFieldCache::Entry make_field_entry(const voxel::DistanceField& f) {
        renderer::InstanceFieldCache::Entry e;
        GLuint tex = upload_field_atlas_tex(f, e.layout);
        field_textures_.push_back(tex);
        e.tex2d  = tex;
        e.origin = f.origin;
        e.cell   = f.cell;
        e.dims   = f.dims;
        e.scale  = f.scale;
        return e;
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    // Brightest RGB sum over the inner half of the framebuffer — see the
    // pre-Task-3 file's identical helper for why (an off-centre wall from a
    // noise-deformed / not-exactly-on-axis cavity).
    int read_inner_max() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<unsigned char> buf(kW * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        int best = 0;
        for (int y = kH / 4; y < 3 * kH / 4; ++y) {
            for (int x = kW / 4; x < 3 * kW / 4; ++x) {
                int i = (y * kW + x) * 4;
                int s = buf[i] + buf[i + 1] + buf[i + 2];
                if (s > best) best = s;
            }
        }
        return best;
    }

    long long read_frame_sum() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<unsigned char> buf(kW * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        long long s = 0;
        for (int i = 0; i < kW * kH; ++i) {
            s += buf[i * 4 + 0];
            s += buf[i * 4 + 1];
            s += buf[i * 4 + 2];
        }
        return s;
    }

    // Camera looking at `center` from along `normal` (the SAME normal the
    // surface patch there was built facing) at `distance`, so the centre
    // pixel's ray hits the patch (and hence starts the raymarch) very close
    // to `center` itself.
    static scenegraph::Camera cam_facing(glm::vec3 center, glm::vec3 normal, float distance) {
        normal = glm::normalize(normal);
        scenegraph::Camera c;
        c.eye    = center + normal * distance;
        c.target = center;
        // up must not be parallel to the view direction; normal==(0,0,1) is
        // this file's common case, so pick a world-Y up unless that would
        // be near-parallel, matching make_surface_patch_model's own ref
        // fallback logic.
        c.up = (std::fabs(normal.z) < 0.9f) ? glm::vec3(0.f, 0.f, 1.f) : glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = distance + 500.f;
        return c;
    }

    void clear_framebuffer() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        // Stencil starts at 0 = "no hull was cut here", which BLOCKS the interior.
        glStencilMask(0xFF);
        glClearStencil(0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    }

    // Stand in for FrameSubmitter::submit_carve_stencil: stamp the whole
    // frame as "hull was cut away here" so the stencil test passes.
    void mark_hull_cut() {
        glStencilMask(0xFF);
        glClearStencil(1);
        glClear(GL_STENCIL_BUFFER_BIT);
        glClearStencil(0);
    }

    static bool has_stencil() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        GLint bits = 0;
        glGetFramebufferAttachmentParameteriv(
            GL_FRAMEBUFFER, GL_STENCIL,
            GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &bits);
        return bits > 0;
    }
};

}  // namespace

// ── Basic interior render / masking ─────────────────────────────────────

TEST_F(BreachPassGLTest, SolidFillDrawsInterior) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    mark_hull_cut();   // the interior draws only where hull was cut away
    pass.draw_instance(/*instance_key=*/1, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in solid-fill interior draw";
    EXPECT_EQ(pass.draw_calls(), 1u) << "one draw_instance() call must issue exactly one proxy submission";
    EXPECT_GT(read_inner_max(), 24)
        << "Inner region is background — solid fill: the cavity's interior wall "
           "should be visible around the raymarch axis";
}

// ── Node-chain frame: BODY frame, not a mesh node's LOCAL frame ────────────
//
// renderer::draw_model_positions_only sets u_model = instance_world *
// node_chain, so a vertex ATTRIBUTE is NODE-LOCAL and the ship's BODY frame is
// node_chain * a_pos. Body frame is the frame everything this pass reads lives
// in: the damage field (voxel/voxelize.cc's collect_hull_triangles composes
// the same node chain when BAKING it), the fill volume, u_camera_pos_body,
// u_breach_center -- and the frame opaque.frag reconstructs (p_body =
// u_ship_world_inv * v_position_ws, frame.cc) before running the very carve
// discard that stamps the stencil this pass draws under. Mixing the two frames
// makes every field lookup here read the wrong point.
//
// Every OTHER GL test in this file builds its model with an identity node
// transform, which makes them blind to that distinction BY CONSTRUCTION: with
// one identity node, node-local IS body frame, so a shader that confuses them
// still passes. Real hulls are not identity -- Galaxy.nif's chain is the pure
// translation below (measured: the NIF's node-local vertex bounds have
// identical widths on all three axes to voxel_inspect --dump-hull-obj's
// body-frame bounds, so the chain is a translation, and this is its offset).
// At Galaxy's 5.0 field cell that is ~27 cells in Y, against carves whose
// entire along-normal extent is 2.7-27 model units.
constexpr glm::vec3 kGalaxyNodeChain(0.0f, 128.447f, 38.005f);

// Draw the SAME body-frame geometry as SolidFillDrawsInterior, with the SAME
// field, fill and camera, changing ONLY how the transform is split: the node
// carries kGalaxyNodeChain and make_surface_patch_model stores its vertices
// pre-multiplied by that node's inverse. So u_model (= instance_world *
// node_chain, instance_world identity here) maps the stored vertices back onto
// the identical world positions -- gl_Position, the body-frame surface point,
// the camera's body-frame position and the world-space shading point are ALL
// unchanged. A frame-exact match against the identity-node baseline is
// therefore the correct expectation, not an approximation of one; the 1%
// tolerance covers only float round-trip noise through node_xf * inverse(
// node_xf) (~1e-6 model units here, sub-nanopixel).
//
// Discrimination -- this fails, loudly, if either frame is mixed:
//   * breach.vert setting v_body_pos = a_pos (node-local) instead of
//     composing the node chain: ro becomes body z 7.5 - 38.005 = -30.5, which
//     clamps to the field's slice 0 (INTACT, -100), so
//     raymarch_breach_cavity's own opening precondition (sample_hull_field(ro)
//     > kHullFieldIsoMargin) returns false and main() discards EVERY fragment.
//     The frame goes black: read_inner_max drops from ~hundreds to 0.
//   * breach.frag shading with u_model instead of u_ship_world: hit_world is
//     displaced by kGalaxyNodeChain (hit_point is already body frame), swinging
//     view_dir off the field gradient and dropping the diffuse term
//     0.35 + 0.55*ndl from ~0.90 to ~0.61 -- a ~32% fall in frame sum, well
//     past the 1% tolerance. The identity-node baseline cannot catch this one
//     at all (there u_model == u_ship_world == identity), which is exactly why
//     this test compares the two splits rather than asserting on one frame.
TEST_F(BreachPassGLTest, NonIdentityNodeTransformRendersIdenticallyToIdentity) {
    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const scenegraph::Camera cam =
        cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    // Baseline: identity node, exactly as every other test here builds it.
    const assets::Model flat =
        make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/1, fill, entry, flat,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();
    ASSERT_EQ(glGetError(), GL_NO_ERROR) << "GL error in identity-node baseline draw";
    const long long flat_sum = read_frame_sum();
    ASSERT_GT(read_inner_max(), 24)
        << "identity-node baseline drew nothing — the comparison below would be "
           "vacuous (black == black)";

    // Same geometry in body frame; the node carries Galaxy's measured chain.
    const glm::mat4 node_xf = glm::translate(glm::mat4(1.0f), kGalaxyNodeChain);
    const assets::Model chained =
        make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f, node_xf);
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/1, fill, entry, chained,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();
    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in node-chained draw";
    EXPECT_EQ(pass.draw_calls(), 2u) << "two draw_instance() calls, two submissions";

    const long long chained_sum = read_frame_sum();
    EXPECT_GT(read_inner_max(), 24)
        << "A hull mesh whose node chain is a real BC translation rendered NO "
           "interior. The shaders are sampling the damage field at the "
           "node-LOCAL vertex position instead of the body-frame one "
           "(node_chain * a_pos) — see this test's own comment.";
    EXPECT_NEAR(static_cast<double>(chained_sum), static_cast<double>(flat_sum),
                0.01 * static_cast<double>(flat_sum))
        << "Identical body-frame geometry rendered differently depending on how "
           "the transform is split between the node chain and the instance world "
           "matrix. Some part of this pass is using u_model (which carries the "
           "node chain) where it needs the instance world matrix alone, or vice "
           "versa — see this test's own comment. flat=" << flat_sum
        << " chained=" << chained_sum;
}

// The same invariance argument as the node-chain test above, applied to the
// OTHER half of the transform: a ROTATED instance world matrix.
//
// This one exists for a defect the node-chain test structurally cannot see:
// both of its legs use an identity instance world, so body space and world
// space coincide there and a shader that mixes the two still passes. The
// diffuse term used to do exactly that -- `n` is the damage FIELD's own
// gradient at hit_point, a BODY-frame direction, while view_dir was built
// from a world-space hit point and a world-space camera. The dot product of
// the two is only correct when the instance world matrix carries no rotation,
// i.e. never for a ship that is moving or turning. It never blanked anything
// (light stays in [0.35, 0.90]), so nothing but a frame-aware test can catch
// it: it reads as interior shading that goes flat, or swims, as the hull
// turns.
//
// Rotating the instance world by R and the camera's eye/target/up by the SAME
// R leaves the view matrix as view*inverse(R), so view*inverse(R) * (R*p) ==
// view*p: the rasterised image, every body-frame quantity (v_body_pos,
// u_camera_pos_body, hit_point, the field gradient) and the body-frame
// geometry are all unchanged, and only world space moves. A frame-exact match
// against the unrotated baseline is therefore the correct expectation, same as
// for the node-chain test; the 1% tolerance covers only float round-trip noise
// through R * inverse(R).
//
// 60 degrees about body X is picked so the error is large and computable, not
// because anything special happens there: it swings the world-space view
// direction to (0, -sin60, cos60), whose dot with the body-frame gradient
// (0,0,1) is 0.5 instead of 1.0, i.e. light 0.35+0.55*0.5 = 0.625 against a
// correct 0.90 -- a ~31% fall in frame sum, far outside the tolerance.
constexpr float kRotatedWorldPitchDeg = 60.0f;

TEST_F(BreachPassGLTest, RotatedInstanceWorldShadesIdenticallyToUnrotated) {
    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch =
        make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    const scenegraph::Camera cam =
        cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    // Baseline: identity instance world (what every other test here uses).
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/1, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();
    ASSERT_EQ(glGetError(), GL_NO_ERROR) << "GL error in unrotated baseline draw";
    const long long flat_sum = read_frame_sum();
    ASSERT_GT(read_inner_max(), 24)
        << "unrotated baseline drew nothing — the comparison below would be "
           "vacuous (black == black)";

    // Rotate the ship AND the camera by the same R: identical picture, identical
    // body frame, different world frame.
    const glm::mat4 R = glm::rotate(glm::mat4(1.0f),
                                    glm::radians(kRotatedWorldPitchDeg),
                                    glm::vec3(1.f, 0.f, 0.f));
    scenegraph::Camera rot_cam = cam;
    rot_cam.eye    = glm::vec3(R * glm::vec4(cam.eye, 1.0f));
    rot_cam.target = glm::vec3(R * glm::vec4(cam.target, 1.0f));
    rot_cam.up     = glm::vec3(R * glm::vec4(cam.up, 0.0f));

    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/1, fill, entry, patch, R, rot_cam, *pipeline);
    glFinish();
    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in rotated-world draw";
    EXPECT_EQ(pass.draw_calls(), 2u) << "two draw_instance() calls, two submissions";

    const long long rot_sum = read_frame_sum();
    EXPECT_GT(read_inner_max(), 24)
        << "A rotated instance world rendered NO interior — this pass should be "
           "orientation-invariant in body frame";
    EXPECT_NEAR(static_cast<double>(rot_sum), static_cast<double>(flat_sum),
                0.01 * static_cast<double>(flat_sum))
        << "The same ship, same damage, same view, shaded differently purely "
           "because the hull is turned. Something in this pass is combining a "
           "BODY-frame vector with a WORLD-space one — the field gradient `n` "
           "with a world-space view direction is how this went wrong before. "
           "flat=" << flat_sum << " rotated=" << rot_sum;
}

TEST_F(BreachPassGLTest, StencilZeroBlocksInteriorSoItCannotFloatInOpenSpace) {
    if (!has_stencil())
        GTEST_SKIP() << "framebuffer has no stencil plane — the stencil test "
                        "would always pass and this would assert nothing";
    clear_framebuffer();          // stencil = 0, deliberately NOT marked
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();   // fill says "material here"
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/2, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in stencil-blocked draw";
    // The draw call is still ISSUED (one proxy submitted, same as every
    // other draw_instance() call) -- it is the RASTERISED PIXELS the stencil
    // test blocks, not the CPU-side draw count. See draw_calls()'s own doc.
    EXPECT_EQ(pass.draw_calls(), 1u);
    EXPECT_LT(read_inner_max(), 16)
        << "Interior drew with stencil 0 — it would appear in open space wherever "
           "the fill mask balloons past the hull";
}

TEST_F(BreachPassGLTest, EmptyFillDiscardsInterior) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = empty_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/3, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-fill interior draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is bright (R=" << (int)px[0]
        << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") — empty fill: every fragment's backing check should discard (see-through)";
}

// ── Interior shell: a hole is never a window to the skybox ────────────────
//
// THE BUG THIS EXISTS TO CATCH. BC's authored hull volumes are only a handful
// of nodes deep through a ship's vertical axis (measured: Galaxy 9, Vorcha 7,
// BirdOfPrey 6, Sovereign 5, Akira 5, Galor 3 -- see carve_cavity_test.cc), so
// a carve routinely marches straight out of the fill and the scoop's backing
// gate discards ("a hole is a hole"). The hull is a single-sided shell drawn
// cull BACK, so the far plating's inside face is culled too and the pixel
// resolves to the skybox: a hole you can see space through from the struck
// side, while the same ship from the far side shows intact hull. That
// asymmetry is what this shell removes.
//
// empty_fill() is the exact production condition (no backing anywhere, so the
// scoop discards every fragment -- EmptyFillDiscardsInterior above asserts
// precisely that on a single sheet). The difference here is purely geometric:
// there IS a far sheet, and it must be drawn.
//
// Discrimination: with the shell removed this reads background (0,0,0) --
// which is the shipped behaviour today, not a hypothetical.
TEST_F(BreachPassGLTest, HoleWithNoBackingShowsFarPlatingNotBackground) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = empty_fill();   // no backing: the scoop discards everywhere
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);

    // Near sheet sits mid-carve (z=7.5, inside the field's carved band
    // [0,15]); far sheet at z=-20 is below the field box entirely, so it
    // samples the clamped idx-0 slice (-100, intact) and is NOT carved.
    const glm::vec3 far_center(0.0f, 0.0f, -20.0f);
    const assets::Model plates =
        make_two_plate_model(kCavitySurfaceCenter, far_center, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/70, fill, entry, plates,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in interior-shell draw";
    auto px = read_center();
    EXPECT_GT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is background (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — you are looking through the hull at the "
           "skybox. The far plating's inside face must be drawn.";
}

// The shell must NOT plug the hole with the very sheet the carve cut through.
// A closed mesh's near sheet has a back face CO-PLANAR with the front face
// that was just discarded; drawing it would fill every breach with its own
// plating at zero depth -- the "breach reads as a crust rather than a hole"
// failure carve_cavity_test.cc's header describes. The shell therefore runs
// the SAME field test the opaque pass does, inverted: it survives only where
// the hull was NOT carved.
//
// Single sheet, so the ONLY thing the shell could draw is that co-planar back
// face. Must stay background.
TEST_F(BreachPassGLTest, ShellDoesNotPlugTheHoleWithItsOwnCarvedSheet) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = empty_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch =
        make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/71, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in shell self-plug draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit (R=" << (int)px[0] << " G=" << (int)px[1]
        << " B=" << (int)px[2] << ") — the shell painted the carved sheet's own "
           "back face, plugging the hole it was cut from";
}

// One shell draw per INSTANCE, like the scoop -- not one per carve. A field
// carrying 30 independent damage sites (beyond HullCarveField's 24-slot ring
// by construction) still submits exactly one.
TEST_F(BreachPassGLTest, OneShellDrawIssuedRegardlessOfDamageSiteCount) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = wide_solid_fill();
    const voxel::DistanceField field = make_multi_site_field(30);
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const glm::vec3 center(0.f, 0.f, multi_site_z(29));
    const assets::Model patch = make_surface_patch_model(center, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(center, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/72, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_EQ(pass.shell_draw_calls(), 1u)
        << "draw_instance() issued " << pass.shell_draw_calls()
        << " interior-shell submissions for one instance -- expected exactly one";
}

// GL: an entry with no uploaded atlas (tex2d==0 — the same state an instance
// that was never carved has: InstanceFieldCache::get() returns nullptr for
// it, so draw_instance() is simply never called in production) is a no-op.
// Discrimination: draw_calls() would read 1 (not 0) if the tex2d==0 guard
// were removed or inverted, and the centre pixel would light up if the pass
// somehow still issued the draw with an unbound/garbage sampler.
TEST_F(BreachPassGLTest, NoFieldEntryDrawsNothing) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const renderer::InstanceFieldCache::Entry entry;  // tex2d == 0, default
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/4, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-field draw";
    EXPECT_EQ(pass.draw_calls(), 0u) << "no field entry -- draw_instance() must return early";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no field entry — the pass should be a no-op";
}

// hit_point for make_single_cavity_field() + cam_facing(kCavitySurfaceCenter, ...):
// the EXIT crossing near body z=0 (see that field's own comment), x,y~=0
// for the screen-centre ray. Used by the rim-emissive tests below to place
// u_breach_center where hit_point actually lands -- Task 3 obligation #2
// (breach.frag's u_breach_center comment) means heat is gated by distance
// from that centre too, not just by age, so a test of the AGE gate
// specifically must put the "fresh" event's centre where the shaded point
// actually is, or the position gate would zero heat regardless of age and
// the test would prove nothing about age at all.
constexpr glm::vec3 kCavityHitPoint(0.0f, 0.0f, 0.0f);

TEST_F(BreachPassGLTest, HotBreachBrighterThanCold) {
    const voxel::DistanceField field = make_single_cavity_field();
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    clear_framebuffer();
    mark_hull_cut();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    long long cold_sum = 0;
    {
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        pass.draw_instance(/*instance_key=*/10, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline,
                           scenegraph::kRimLife + 1.f,  // cold
                           kCavityHitPoint, 100.f);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in cold breach draw";
        cold_sum = read_frame_sum();
    }

    clear_framebuffer();
    mark_hull_cut();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    long long hot_sum = 0;
    {
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        // breach_radius=100: generous relative to kEventFalloffMul=3 (see
        // breach.frag) so the whole visible interior -- not just the exact
        // centre pixel -- stays within the positional falloff; this test is
        // about the AGE gate, so the position gate should not be the
        // limiting factor here (that gets its own test below).
        pass.draw_instance(/*instance_key=*/11, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline,
                           0.f,  // fresh (hot)
                           kCavityHitPoint, 100.f);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in hot breach draw";
        hot_sum = read_frame_sum();
    }

    EXPECT_GT(hot_sum, cold_sum + 512)
        << "Hot breach (age=0) frame sum=" << hot_sum
        << " should be significantly brighter than cold (age>=kRimLife) sum="
        << cold_sum << " — rim emissive did not contribute";
}

// Task 3 obligation #2 (breach.frag's u_breach_center comment): a FRESH
// event (age=0) whose centre is nowhere near the shaded hit_point must NOT
// light it up -- this is what stops one fresh hit from re-igniting every
// OTHER, already-cooled hole on the same instance, now that there is one
// draw per instance instead of one per carve. Same field/camera/fill as
// HotBreachBrighterThanCold's hot case (so the ONLY variable is the
// event's position), compared against that SAME test's cold baseline:
// if the position gate were missing (or always-open), this frame's sum
// would match a genuinely hot frame's, not a cold one's.
TEST_F(BreachPassGLTest, HotBreachFarFromHitPointDoesNotReignite) {
    const voxel::DistanceField field = make_single_cavity_field();
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    // "Hot but positionally irrelevant": age=0 (would be maximally hot at
    // the RIGHT location -- see HotBreachBrighterThanCold) but centred
    // 10000 units away with a small radius, far outside even a generous
    // falloff.
    long long far_sum = 0;
    {
        clear_framebuffer();
        mark_hull_cut();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        pass.draw_instance(/*instance_key=*/12, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline,
                           0.f,
                           glm::vec3(10000.f, 10000.f, 10000.f), 25.f);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in far-event breach draw";
        far_sum = read_frame_sum();
    }

    // Genuinely cold baseline (age >= kRimLife), same field/camera/fill.
    long long cold_sum = 0;
    {
        clear_framebuffer();
        mark_hull_cut();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        pass.draw_instance(/*instance_key=*/13, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline,
                           scenegraph::kRimLife + 1.f);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in cold breach draw";
        cold_sum = read_frame_sum();
    }

    // Same threshold logic as HotBreachBrighterThanCold: a cold frame and
    // this "hot but positionally irrelevant" frame should be
    // indistinguishable (both have heat==0 at every fragment), so this must
    // NOT exceed the cold baseline by the margin a genuinely hot,
    // correctly-positioned frame does.
    EXPECT_LE(far_sum, cold_sum + 32)
        << "A fresh (age=0) event centred 10000 units from hit_point lit the frame up "
           "(sum=" << far_sum << " vs cold baseline=" << cold_sum << ") -- the emissive "
           "term must be gated by distance from the event's own centre, not by age alone";
}

// ── Task 3 obligation #1: a raymarch hit with no real backing material must
// not paint (retires breach_raymarch_test.cc's
// RaymarchAloneCannotDistinguishABrushBoundaryFromRealBacking, which
// documented this as an open gap through raymarch_breach_cavity() in
// isolation -- that function is UNCHANGED across every round of this task;
// the fix lives in main(), which this pair exercises end-to-end through the
// real production shader). ──────────────────────────────────────────────

// Negative: make_single_cavity_field()'s hit_point (the EXIT crossing, near
// z=0) sits well outside thin_plate_fill()'s only solid material
// (z=[12,15], near the band's OTHER edge). Must discard: "a hole is a hole".
TEST_F(BreachPassGLTest, HitWithNoBackingMaterialDoesNotPaint) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = thin_plate_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/20, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in floating-hit draw";
    EXPECT_EQ(pass.draw_calls(), 1u) << "a draw IS issued -- the fix discards fragments, not the draw call";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit (R=" << (int)px[0] << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") -- the raymarch found a wall but there is no real hull material there; "
           "it must not paint";
}

// Positive control: IDENTICAL field/camera, but fill now covers the whole
// box (solid_fill(), which spans z=[-30,60] -- past both thin_plate_fill's
// z=[12,15] and hit_point's z~=0). Proves the negative result above is not
// a vacuously-always-discarding check -- flipping only the fill flips the
// outcome.
TEST_F(BreachPassGLTest, HitWithRealBackingMaterialPaints) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();   // covers [-30,60] on Z -- includes hit_point~z=0
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/21, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in backed-hit draw";
    EXPECT_GT(read_inner_max(), 24)
        << "Same field/camera as HitWithNoBackingMaterialDoesNotPaint, but with backing "
           "material actually present at hit_point -- must paint, proving the fill check "
           "genuinely discriminates rather than always discarding";
}

// ── A carved region sized from REAL carve geometry (not from an
// implementation constant) still renders its interior -- see
// make_narrow_realistic_cavity_field's own comment for the derivation. ───

TEST_F(BreachPassGLTest, NarrowRealisticCarveCavityStillRenders) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_narrow_realistic_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch =
        make_surface_patch_model(kNarrowCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kNarrowCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);

    pass.draw_instance(/*instance_key=*/22, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in narrow-carve draw";
    EXPECT_GT(read_inner_max(), 24)
        << "A carved region 3 model units wide (approximating the smallest real combat "
           "carve's ~2.7-unit along-normal extent, see make_narrow_realistic_cavity_field's "
           "own comment) should still render an interior wall";
}

// ── One draw per instance, not per damage site; and the plan's payoff test:
// interior renders for a carve beyond the 24-slot sphere ring's cap. ───────

TEST_F(BreachPassGLTest, OneDrawIssuedRegardlessOfDamageSiteCount) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = wide_solid_fill();
    const voxel::DistanceField field = make_multi_site_field(30);
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const float z0 = multi_site_z(0);
    const glm::vec3 center(0.f, 0.f, z0);
    const assets::Model patch = make_surface_patch_model(center, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(center, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/30, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in multi-site draw";
    // draw_instance()'s signature takes ONE field entry and ONE patch mesh,
    // not a carve list -- there is structurally no per-carve loop left to
    // regress, but this is the observable proof: a field encoding 30
    // independent damage sites still issues exactly one proxy submission.
    EXPECT_EQ(pass.draw_calls(), 1u)
        << "draw_instance() issued " << pass.draw_calls()
        << " proxy submissions for a single instance whose field carries 30 damage sites -- "
           "expected exactly one, regardless of damage-site count";
}

TEST_F(BreachPassGLTest, InteriorRendersForACarveBeyondTheTwentyFourSlotRing) {
    voxel::VoxelVolume fill = wide_solid_fill();
    const voxel::DistanceField field = make_multi_site_field(30);

    // Positive: site index 29 -- the 30th site, beyond HullCarveField::
    // kMaxCarves (24) by construction (see make_multi_site_field's header
    // comment) -- must render its interior.
    {
        clear_framebuffer();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        mark_hull_cut();

        renderer::BreachPass pass;
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        const glm::vec3 center(0.f, 0.f, multi_site_z(29));
        const assets::Model patch = make_surface_patch_model(center, glm::vec3(0, 0, 1), 50.f);
        scenegraph::Camera cam = cam_facing(center, glm::vec3(0, 0, 1), 100.f);

        pass.draw_instance(/*instance_key=*/31, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error targeting site 29";
        EXPECT_GT(read_inner_max(), 24)
            << "Site 29 (the 30th independent damage site, beyond a 24-slot ring's cap) "
               "should render an interior -- this is the artifact the plan exists to remove";
    }

    // Negative control: the mesh patch (and hence the raymarch's own `ro`)
    // sits at multi_site_gap_z(29) -- a cell INSIDE site 29's own untouched
    // "before" gap, never carved. raymarch_breach_cavity's own precondition
    // (sample_hull_field(ro) > margin) rejects this immediately -- no
    // search, no budget, nothing for a future change to silently defeat by
    // reaching further. Must stay background: rules out "this field renders
    // an interior everywhere regardless of where the ray starts", which
    // would make the positive result above vacuous.
    {
        clear_framebuffer();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        mark_hull_cut();

        renderer::BreachPass pass;
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        const glm::vec3 center(0.f, 0.f, multi_site_gap_z(29));
        const assets::Model patch = make_surface_patch_model(center, glm::vec3(0, 0, 1), 50.f);
        scenegraph::Camera cam = cam_facing(center, glm::vec3(0, 0, 1), 100.f);

        pass.draw_instance(/*instance_key=*/32, fill, entry, patch,
                           glm::mat4(1.0f), cam, *pipeline);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error targeting site 29's own gap";
        auto px = read_center();
        EXPECT_LT(px[0] + px[1] + px[2], 16)
            << "Centre pixel lit while starting inside an untouched gap -- expected "
               "background, or the positive result at site 29 would not be meaningful "
               "evidence";
    }
}

// ── render()'s own gate: an undamaged instance (no InstanceFieldCache
// entry) issues zero draws, checked BEFORE any model/fill lookup. ─────────

TEST_F(BreachPassGLTest, UndamagedInstanceIssuesNoDraws) {
    scenegraph::World world;
    const scenegraph::InstanceId id = world.create_instance(/*model=*/0);
    ASSERT_TRUE(world.is_valid(id));

    renderer::InstanceFieldCache field_cache;  // nothing ever carve()'d
    renderer::CarveFieldCache    carve_cache;  // real, but must never be touched
    renderer::BreachPass         pass;
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    // A lookup that fails the test if invoked: proves field_cache->get()
    // gates BEFORE any model lookup happens at all, for the undamaged case.
    bool lookup_called = false;
    renderer::BreachPass::ModelLookup trap_lookup =
        [&](scenegraph::ModelHandle) -> const assets::Model* {
            lookup_called = true;
            ADD_FAILURE() << "model lookup must not run for an instance with no field entry";
            return nullptr;
        };

    pass.render(world, cam, *pipeline, trap_lookup, carve_cache, &field_cache, /*now=*/0.f);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_FALSE(lookup_called);
    EXPECT_EQ(pass.draw_calls(), 0u)
        << "an instance with no InstanceFieldCache entry must issue zero draws";
}

// ── Stencil/cull GL state is restored exactly as begin_scoop_state()/
// end_scoop_state() (breach_pass.cc) document. ──────────────────────────────

TEST_F(BreachPassGLTest, StencilAndCullStateRestoredAfterDrawInstance) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);

    pass.draw_instance(/*instance_key=*/40, fill, entry, patch,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    GLboolean stencil_test_enabled = GL_TRUE;
    glGetBooleanv(GL_STENCIL_TEST, &stencil_test_enabled);
    EXPECT_EQ(stencil_test_enabled, GL_FALSE)
        << "end_scoop_state() must leave GL_STENCIL_TEST disabled";

    GLint write_mask = 0;
    glGetIntegerv(GL_STENCIL_WRITEMASK, &write_mask);
    EXPECT_EQ(write_mask, 0xFF)
        << "glStencilMask must be restored to 0xFF -- breach_pass.cc's own documented trap: "
           "leaving it closed silently turns the next glClear(GL_STENCIL_BUFFER_BIT) into a "
           "no-op and lets marks accumulate across frames";

    GLint cull_mode = 0;
    glGetIntegerv(GL_CULL_FACE_MODE, &cull_mode);
    EXPECT_EQ(cull_mode, GL_BACK)
        << "glCullFace must be restored to GL_BACK after the draw";
}
