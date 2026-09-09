// native/tests/renderer/breach_pass_test.cc
//
// Tests for the breach interior BOX-PROXY pass (raymarched-breach-interior
// Task 3), which replaces the hull-breach-2b/2c per-carve sphere scoop.
//
// The pass now draws ONE box per DAMAGED instance (an instance with a
// per-instance damage-field entry — renderer::InstanceFieldCache), covering
// the field's own body-frame extent, and raymarches the field per-fragment
// (breach.frag) to find the actual cavity wall. This file exercises that
// through the REAL production shader/GL path: BreachPass::draw_instance()
// takes an already-built InstanceFieldCache::Entry (packed by hand here from
// a voxel::DistanceField, exactly the shape InstanceFieldCache::get() would
// hand back in production) plus the original hull fill, and issues real GL
// draws whose PIXELS are read back and asserted on — not a hand re-derivation
// of the shader's own logic.
//
//  GL tests (skip without a context):
//    - draw_instance with a real cavity over a solid fill: interior visible.
//    - Stencil gate: stencil==0 blocks the interior (cannot float in space).
//    - Empty fill discards every fragment (see-through).
//    - No field entry (tex2d==0): the pass is a no-op (draw_calls()==0).
//    - Molten-rim emissive: fresh breach renders brighter than cold.
//    - Task 3 obligation #1 (retires breach_raymarch_test.cc's
//      RaymarchAloneCannotDistinguishABrushBoundaryFromRealBacking): a
//      raymarch hit with no real backing material does NOT paint, paired
//      with a positive control proving the SAME geometry DOES paint once
//      real backing exists (rules out a vacuously-always-discarding check).
//    - Exactly one glDrawElements call per draw_instance(), regardless of
//      how many independent damage sites the field encodes.
//    - A field carrying MORE than HullCarveField::kMaxCarves (24) distinct
//      damage sites still renders the interior for the last of them — the
//      artifact this whole plan exists to remove — paired with a negative
//      control (an untouched gap) to rule out "everything always renders".
//    - render()'s own gate: an instance with no InstanceFieldCache entry
//      (never carved) issues zero draws, checked BEFORE any model/fill
//      lookup (a lookup that asserts if called proves the ordering).
//    - Stencil/cull GL state is restored exactly as breach_pass.cc's
//      begin_scoop_state()/end_scoop_state() document.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/breach_pass.h>
#include <renderer/carve_field_cache.h>
#include <renderer/instance_field_cache.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>

#include <voxel/distance_field.h>
#include <voxel/field_atlas.h>
#include <voxel/volume.h>

#include <array>
#include <cstdint>
#include <memory>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

// ── Fill volumes (unchanged builders from the pre-Task-3 file: these are
// plain VoxelVolume data, independent of the carve/field representation) ───

// Solid (127) everywhere in [-4,4]^3: comfortably covers every hit_point
// this file's single-site fields (below) ever raymarches to.
voxel::VoxelVolume solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {8, 8, 8};
    v.origin = {-4.f, -4.f, -4.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(8 * 8 * 8, 127);
    return v;
}

// Empty (0) everywhere in [-2,2]^3: every fragment's backing check fails.
voxel::VoxelVolume empty_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 0);
    return v;
}

// 75 (just above kIsovalue=64, inside the rim band) everywhere in [-2,2]^3.
voxel::VoxelVolume rim_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 75);
    return v;
}

// Solid (127) everywhere in a big box covering the multi-site field below,
// INCLUDING its trailing untouched pad (x:[-2,14], y:[-2,14], z:[-5,895] --
// make_multi_site_field(30)'s own box tops out at 21*30+3*80=870).
voxel::VoxelVolume wide_solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 90};
    v.origin = {-2.f, -2.f, -5.f};
    v.cell   = {4.f, 4.f, 10.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 90), 127);
    return v;
}

// Solid (127) in ONLY a single 1-unit-thick z-slice, z in [2,3], covering
// x:[-2,2], y:[-2,2] — a "thin plate" for the floating-hit test below.
// Outside that z range the fill's own texture-coordinate range check
// (breach.frag main()) discards, same as "no material".
voxel::VoxelVolume thin_plate_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 1};
    v.origin = {-2.f, -2.f, 2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 1, 127);
    return v;
}

// ── Damage fields (voxel::DistanceField, hand-built for exact analytic
// control over which cells are "carved" — the same technique
// breach_raymarch_test.cc's make_slab_field uses, duplicated here per this
// project's per-file test convention; see instance_field_cache_test.cc's own
// header comment for that convention). Every (x,y) at a given Z slice gets
// the same value: a pure single-axis slab, varied along Z to match this
// file's cam_looking_at_origin()-style cameras (which all look along -Z). ──

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

// ONE cavity: intact (idx 0-2, z centres -1.5/-0.5/0.5), carved (idx 3-4,
// z centres 1.5/2.5), intact again (idx 5, z centre 3.5). Box: x,y in
// [-2,2], z in [-2,4] — inside solid_fill()'s [-4,4]^3.
voxel::DistanceField make_single_cavity_field() {
    const std::vector<std::int8_t> z_values = {-100, -100, -100, 100, 100, -100};
    return make_z_slab_field(glm::ivec3(4, 4, 6), glm::vec3(-2.0f), glm::vec3(1.0f), z_values);
}

// A carve BRUSH punched clean through a "thin plate": intact (idx 0-1, z
// centres -1.5/-0.5), carved (idx 2-4, z centres 0.5/1.5/2.5 — a 3-cell-thick
// bounded brush, standing in for field_carve_oblate's own bounded shape),
// intact again (idx 5-7, z centres 3.5/4.5/5.5). Box: x,y in [-2,2],
// z in [-2,6].
//
// The camera below enters from +Z (idx 7 first) and finds ITS ENTRY crossing
// around z~3 (between idx5 intact and idx4 carved), then raymarch_breach_
// cavity finds the FAR/EXIT crossing around z~0 (between idx2 carved and
// idx1 intact) -- well below thin_plate_fill()'s solid slice at z=[2,3], and
// well within wide-enough fills that DO cover z~0.
voxel::DistanceField make_through_plate_field() {
    const std::vector<std::int8_t> z_values = {-100, -100, 100, 100, 100, -100, -100, -100};
    return make_z_slab_field(glm::ivec3(4, 4, 8), glm::vec3(-2.0f), glm::vec3(1.0f), z_values);
}

// `n` independent damage sites along Z, each a 3-cell carved band separated
// by 4 cells of untouched field, period 7 cells: site i's carved cells are
// [7*i+2, 7*i+4]. cell=3 model units, so site i's carved z-range (cell
// centres) is [(7*i+2.5)*3, (7*i+4.5)*3] = [21*i+7.5, 21*i+13.5].
//
// n=30 is used deliberately, not an arbitrary "a lot": scenegraph::
// HullCarveField::kMaxCarves is 24, so a field encoding 30 independent sites
// — built here with NO HullCarveField anywhere in this file, since
// draw_instance()'s new signature no longer takes one — is structurally
// beyond anything a 24-slot sphere ring could ever represent, by
// construction rather than by argument.
//
// A `kPadCells`-cell untouched buffer follows the last site, deliberately
// wider (240 model units) than breach.frag's own search budget
// (kBreachMaxSteps * kHullFieldStepFrac * cell = 64*0.5*3 = 96 model units):
// the negative-control test below places its camera in the MIDDLE of this
// buffer specifically so that budget, searching in EITHER direction from
// there, cannot reach site (n-1)'s band (up to 96 units away is not enough
// to cross a 240-unit clear buffer) -- see cam_at_site's own comment for why
// this matters (an early version of this test put the camera far from every
// site and let it search inward, which meant the fixed 96-unit budget could
// reach an adjacent site from ANY point when sites were only 21 units
// apart, making a "negative control" meaningless).
// Box: x,y in [0,12], z in [0, 21*n + 3*kPadCells].
voxel::DistanceField make_multi_site_field(int n) {
    const int period    = 7;
    const int kPadCells = 80;
    const int dims_z    = period * n + kPadCells;
    std::vector<std::int8_t> z_values(static_cast<std::size_t>(dims_z), -100);
    for (int i = 0; i < n; ++i) {
        z_values[static_cast<std::size_t>(period * i + 2)] = 100;
        z_values[static_cast<std::size_t>(period * i + 3)] = 100;
        z_values[static_cast<std::size_t>(period * i + 4)] = 100;
    }
    return make_z_slab_field(glm::ivec3(4, 4, dims_z), glm::vec3(0.0f), glm::vec3(3.0f),
                             z_values);
}

// Body-frame Z centre of multi-site field site `i`'s MIDDLE carved cell
// (7*i+3), matching make_multi_site_field's own layout above.
float multi_site_z(int i) {
    return (7.0f * static_cast<float>(i) + 3.5f) * 3.0f;
}

// Body-frame Z centre of a cell deep inside make_multi_site_field(n)'s
// trailing untouched buffer -- always -100, and (with kPadCells=80, cell=3)
// at least 120 model units from site (n-1)'s own band in either direction,
// comfortably beyond the ~96-unit search budget. Used by the negative
// control below.
float multi_site_gap_z(int n) {
    const int period    = 7;
    const int kPadCells  = 80;
    const int idx = period * n + kPadCells / 2;
    return (static_cast<float>(idx) + 0.5f) * 3.0f;
}

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

    // Camera looking at the origin along -Z — matches every make_z_slab_
    // field above (varied along Z only), so the primary (screen-centre) ray
    // travels straight down the axis the fields vary on.
    static scenegraph::Camera cam_looking_at_origin() {
        scenegraph::Camera c;
        c.eye    = glm::vec3(0.f, 0.f, 5.f);
        c.target = glm::vec3(0.f);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = 50.f;
        return c;
    }

    // Camera looking down -Z from further out (z=7) — used by the
    // through-plate field (box z in [-2,6], vs. the single-cavity field's
    // [-2,4]), so the camera still starts outside the box.
    static scenegraph::Camera cam_looking_at_origin_from_z7() {
        scenegraph::Camera c = cam_looking_at_origin();
        c.eye    = glm::vec3(0.f, 0.f, 7.f);
        c.target = glm::vec3(0.f, 0.f, -2.f);
        return c;
    }

    // Camera aimed at Z location `target_z` in a multi_site field (x,y = 6,6
    // -- centred on that field's x,y = [0,12] box), positioned CLOSE to it
    // (8 units of +Z head-room, comfortably above one carved band's own
    // 9-unit thickness) rather than far above the whole field.
    //
    // This is deliberate, not just convenient: breach.frag's box-entry
    // search (find_breach_entry) is bounded to ~96 model units (see
    // make_multi_site_field's header comment for the derivation). Sites
    // recur every 21 units, so a camera FAR from the field searching inward
    // would have that same fixed 96-unit budget reach WHICHEVER site
    // happens to be within range of wherever the search starts -- not
    // necessarily the one `target_z` names -- making "aim at site i" and
    // "aim at the gap" indistinguishable from the search's point of view.
    // Starting close to `target_z` (eye ends up INSIDE the field's box on
    // every axis, so breach_box_entry_t's analytic entry clamps to the
    // camera's own position) makes the search begin exactly where the test
    // means it to.
    static scenegraph::Camera cam_at_site(float target_z, float far_hint) {
        scenegraph::Camera c;
        c.eye    = glm::vec3(6.f, 6.f, target_z + 8.f);
        c.target = glm::vec3(6.f, 6.f, target_z);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = far_hint;
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

// ── Basic interior render / masking (adapted from the pre-Task-3 sphere
// tests to the new box-proxy API) ───────────────────────────────────────────

TEST_F(BreachPassGLTest, SolidFillDrawsInterior) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    scenegraph::Camera cam = cam_looking_at_origin();

    mark_hull_cut();   // the interior draws only where hull was cut away
    pass.draw_instance(/*instance_key=*/1, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in solid-fill interior draw";
    EXPECT_EQ(pass.draw_calls(), 1u) << "one draw_instance() call must issue exactly one draw";
    EXPECT_GT(read_inner_max(), 24)
        << "Inner region is background — solid fill: the cavity's interior wall "
           "should be visible around the raymarch axis";
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
    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/2, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in stencil-blocked draw";
    // The draw call is still ISSUED (one box proxy submitted, same as every
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
    scenegraph::Camera cam = cam_looking_at_origin();

    mark_hull_cut();
    pass.draw_instance(/*instance_key=*/3, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-fill interior draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is bright (R=" << (int)px[0]
        << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") — empty fill: every fragment's backing check should discard (see-through)";
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
    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/4, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-field draw";
    EXPECT_EQ(pass.draw_calls(), 0u) << "no field entry -- draw_instance() must return early";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no field entry — the pass should be a no-op";
}

TEST_F(BreachPassGLTest, HotBreachBrighterThanCold) {
    const voxel::DistanceField field = make_single_cavity_field();
    scenegraph::Camera cam = cam_looking_at_origin();

    clear_framebuffer();
    mark_hull_cut();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    long long cold_sum = 0;
    {
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        pass.draw_instance(/*instance_key=*/10, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline,
                           scenegraph::kRimLife + 1.f);  // cold
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
        pass.draw_instance(/*instance_key=*/11, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline,
                           0.f);  // fresh (hot)
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in hot breach draw";
        hot_sum = read_frame_sum();
    }

    EXPECT_GT(hot_sum, cold_sum + 512)
        << "Hot breach (age=0) frame sum=" << hot_sum
        << " should be significantly brighter than cold (age>=kRimLife) sum="
        << cold_sum << " — rim emissive did not contribute";
}

// ── Task 3 obligation #1: a raymarch hit with no real backing material must
// not paint (retires breach_raymarch_test.cc's
// RaymarchAloneCannotDistinguishABrushBoundaryFromRealBacking, which
// documented this as an open gap through raymarch_breach_cavity() in
// isolation -- that function is UNCHANGED; the fix lives in main(), which
// this pair exercises end-to-end through the real production shader). ──────

// Negative: the field's carved brush has a bounded far edge (hit_point ~
// z=0), but the fill's only solid material is a thin slice at z=[2,3] --
// hit_point sits well outside it. Must discard: "a hole is a hole".
TEST_F(BreachPassGLTest, HitWithNoBackingMaterialDoesNotPaint) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = thin_plate_fill();
    const voxel::DistanceField field = make_through_plate_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    scenegraph::Camera cam = cam_looking_at_origin_from_z7();

    pass.draw_instance(/*instance_key=*/20, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in floating-hit draw";
    EXPECT_EQ(pass.draw_calls(), 1u) << "a draw IS issued -- the fix discards fragments, not the draw call";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit (R=" << (int)px[0] << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") -- the raymarch found a wall (the carve brush's bounded far edge) but there is "
           "no real hull material there; it must not paint";
}

// Positive control: IDENTICAL field/camera, but fill now covers the whole
// box (wide_solid_fill spans past both z=[2,3] and z=0). Proves the negative
// result above is not a vacuously-always-discarding check -- flipping only
// the fill flips the outcome.
TEST_F(BreachPassGLTest, HitWithRealBackingMaterialPaints) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();   // covers [-4,4]^3 -- includes hit_point~z=0
    const voxel::DistanceField field = make_through_plate_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    scenegraph::Camera cam = cam_looking_at_origin_from_z7();

    pass.draw_instance(/*instance_key=*/21, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in backed-hit draw";
    EXPECT_GT(read_inner_max(), 24)
        << "Same field/camera as HitWithNoBackingMaterialDoesNotPaint, but with backing "
           "material actually present at hit_point -- must paint, proving the fill check "
           "genuinely discriminates rather than always discarding";
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
    const float field_max_z = field.origin.z + field.dims.z * field.cell.z;
    scenegraph::Camera cam = cam_at_site(multi_site_z(0), field_max_z + 500.f);

    pass.draw_instance(/*instance_key=*/30, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in multi-site draw";
    // draw_instance()'s new signature takes ONE field entry, not a carve
    // list -- there is structurally no per-carve loop left to regress, but
    // this is the observable proof: a field encoding 30 independent damage
    // sites still issues exactly one glDrawElements call.
    EXPECT_EQ(pass.draw_calls(), 1u)
        << "draw_instance() issued " << pass.draw_calls()
        << " draws for a single instance whose field carries 30 damage sites -- "
           "expected exactly one, regardless of damage-site count";
}

TEST_F(BreachPassGLTest, InteriorRendersForACarveBeyondTheTwentyFourSlotRing) {
    voxel::VoxelVolume fill = wide_solid_fill();
    const voxel::DistanceField field = make_multi_site_field(30);
    const float field_max_z = field.origin.z + field.dims.z * field.cell.z;

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
        scenegraph::Camera cam = cam_at_site(multi_site_z(29), field_max_z + 500.f);

        pass.draw_instance(/*instance_key=*/31, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error targeting site 29";
        EXPECT_GT(read_inner_max(), 24)
            << "Site 29 (the 30th independent damage site, beyond a 24-slot ring's cap) "
               "should render an interior -- this is the artifact the plan exists to remove";
    }

    // Negative control: aim deep into the field's trailing untouched pad
    // (multi_site_gap_z(30) -- at least 120 model units from site 29's own
    // band in either direction, comfortably beyond the ~96-unit search
    // budget; see make_multi_site_field's header comment) -- must stay
    // background. Rules out "this field renders an interior everywhere
    // regardless of the camera", which would make the positive result
    // above vacuous.
    {
        clear_framebuffer();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        mark_hull_cut();

        renderer::BreachPass pass;
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        scenegraph::Camera cam = cam_at_site(multi_site_gap_z(30), field_max_z + 500.f);

        pass.draw_instance(/*instance_key=*/32, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error targeting the inter-site gap";
        auto px = read_center();
        EXPECT_LT(px[0] + px[1] + px[2], 16)
            << "Centre pixel lit at an untouched gap between sites -- expected background, "
               "or the positive result at site 29 would not be meaningful evidence";
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
    scenegraph::Camera cam = cam_looking_at_origin();

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
    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/40, fill, entry,
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
        << "glCullFace must be restored to GL_BACK after the front-face-culled draw";
}
