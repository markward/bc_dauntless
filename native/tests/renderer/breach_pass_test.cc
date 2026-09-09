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
// SCALE: every carved band in every field here is at least 75 model units
// wide (3 * 25). This is not arbitrary — it matches breach.frag's
// find_breach_entry, whose coarse search stride (kBreachCoarseStride = 25,
// derived from MIN_CARVE_RADIUS_GU, engine/appc/hull_carve.py) is sized
// against the SMALLEST LEGAL carve's diameter (50 model units), an
// absolute, cell-independent quantity. A code review caught that this
// file's ORIGINAL fields used 1-9-model-unit-wide bands (fine for the
// pre-fix, cell-relative entry search, which has since been replaced) —
// those would now be silently stepped over by the coarse search, which
// would make every "should render" test in this file pass for the WRONG
// reason (a stale field this pass can't actually find, not a working
// search). See breach.frag's find_breach_entry for the coarse-stride
// derivation itself.
//
// make_single_cavity_field() additionally uses a SMALL cell (5, not 25) to
// grow the field's own box diagonal well past the reach the PRE-fix entry
// search (cell-relative, like raymarch_breach_cavity's own march) would
// have had — see that function's own comment for why band width and box
// reach are two SEPARATE things to get right, and why the same review
// caught this file's tests initially passing even with the reach half of
// the fix reverted.
//
//  GL tests (skip without a context):
//    - draw_instance with a real cavity over a solid fill: interior visible.
//    - Stencil gate: stencil==0 blocks the interior (cannot float in space).
//    - Empty fill discards every fragment (see-through).
//    - No field entry (tex2d==0): the pass is a no-op (draw_calls()==0).
//    - Molten-rim emissive: fresh breach renders brighter than cold, AND
//      (Task 3 obligation #2) a fresh event far from the shaded point does
//      NOT reignite it — age alone is not enough now that one draw covers
//      the whole instance, not one carve.
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
//      control (a camera inside the field's own untouched tail, looking
//      AWAY from every site, toward the box's own edge) to rule out
//      "everything always renders" regardless of the search's own reach.
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

// ── Fill volumes ─────────────────────────────────────────────────────────
// All rescaled to match this file's realistic cell=25 fields (see this
// file's header comment) — the pre-fix versions covered only a few model
// units and no longer reach any hit_point these fields raymarch to.

// Solid (127) everywhere in x,y=[-10,10], z=[-50,275]: comfortably covers
// every hit_point make_single_cavity_field() (below) ever raymarches to.
// Deliberately a SMALL cell (5, not 25): see make_single_cavity_field's own
// header comment for why the fill's cell size does not need to match the
// field's (it never did -- u_fill and u_hull_field are independent volumes
// in the shader).
voxel::VoxelVolume solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 66};
    v.origin = {-10.f, -10.f, -50.f};
    v.cell   = {5.f, 5.f, 5.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 66), 127);
    return v;
}

// Empty (0) over the same box as solid_fill(): every fragment's backing
// check fails.
voxel::VoxelVolume empty_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 66};
    v.origin = {-10.f, -10.f, -50.f};
    v.cell   = {5.f, 5.f, 5.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 66), 0);
    return v;
}

// 75 (just above kIsovalue=64, inside the rim band) over the same box as
// solid_fill().
voxel::VoxelVolume rim_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 66};
    v.origin = {-10.f, -10.f, -50.f};
    v.cell   = {5.f, 5.f, 5.f};
    v.occ.assign(static_cast<std::size_t>(4 * 4 * 66), 75);
    return v;
}

// Solid (127) everywhere in a big box covering the multi-site field below
// (x,y in [-10,115], z in [-10,3890] -- make_multi_site_field(30)'s own box
// tops out at 153*25=3825, see that function's own comment).
voxel::VoxelVolume wide_solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {5, 5, 156};
    v.origin = {-10.f, -10.f, -10.f};
    v.cell   = {25.f, 25.f, 25.f};
    v.occ.assign(static_cast<std::size_t>(5 * 5 * 156), 127);
    return v;
}

// Solid (127) in ONLY a single 10-unit-thick z-slice, z in [65,75],
// covering x,y=[-10,10] -- a "thin plate" right at make_single_cavity_field()'s
// own carved band's HIGH-z (camera-entry) edge, for the floating-hit test
// below. hit_point (the far/EXIT crossing, near z=0 -- see that field's own
// comment) sits nowhere near this slice. Outside this z range the fill's own
// texture-coordinate range check (breach.frag main()) discards, same as "no
// material".
voxel::VoxelVolume thin_plate_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 1};
    v.origin = {-10.f, -10.f, 65.f};
    v.cell   = {5.f, 5.f, 10.f};
    v.occ.assign(4 * 4 * 1, 127);
    return v;
}

// ── Damage fields (voxel::DistanceField, hand-built for exact analytic
// control over which cells are "carved" — the same technique
// breach_raymarch_test.cc's make_slab_field uses, duplicated here per this
// project's per-file test convention; see instance_field_cache_test.cc's own
// header comment for that convention). Every (x,y) at a given Z slice gets
// the same value: a pure single-axis slab, varied along Z to match this
// file's cameras (which all look along Z, one axis or the other). ─────────

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

// ONE bounded cavity, sized to discriminate the reach fix, not just the
// stride fix. A field with cell=25 (matching kBreachCoarseStride) and a
// small overall box has a diagonal too short to distinguish the fixed
// entry search from the ORIGINAL BUG (reusing raymarch_breach_cavity's
// fine, cell-relative step): a code review caught that an earlier version
// of this field -- cell=25, box diagonal ~266 model units -- passed EVERY
// test in this file even with the entry search's stride/budget reverted to
// the pre-fix cell-relative pair (fine_step=0.5*cell=12.5, kBreachMaxSteps
// steps => reach=800, comfortably more than 266). That defeated the whole
// point: the tests would have stayed green through the exact regression
// this task exists to catch.
//
// So the CELL here is small (5, distinct from kBreachCoarseStride, and
// deliberately NOT what governs whether a carve gets stepped over -- see
// below) but the CARVED BAND is still 15 cells = 75 model units wide (the
// smallest legal carve's diameter, same requirement as ever -- carve size
// is absolute, not cell-relative, so widening the band in CELL count while
// shrinking the cell is exactly how to keep the band's ABSOLUTE width fixed
// while growing the field's overall extent). The camera below (cam_through_
// cavity) then sits far enough from the band that the OLD fine-relative
// reach (64 * 0.5 * 5 = 160 model units) cannot reach it, while the FIXED
// coarse reach (64 * 25 = 1600) comfortably can.
//
// Layout: intact (idx 0-9, body z in [-50,0]), CARVED (idx 10-24, body z in
// [0,75] -- 75 model units), intact (idx 25-64, body z in [75,275]).
// Box: x,y in [-10,10], z in [-50,275] -- inside solid_fill()'s x,y=[-10,10],
// z=[-50,275].
//
// Reused by BOTH the "single cavity" tests (solid/empty/rim fill covering
// the whole box) and the "floating hit" tests (a fill covering only part of
// it) -- it is the SAME field either way; only the fill and the question
// asked of hit_point differ. cam_through_cavity finds its COARSE entry
// somewhere in the carved band (idx 10-24) after crossing ~195 model units
// of the intact-after region (idx 25-64), then raymarch_breach_cavity's own
// FINE march finds the EXIT crossing near z=0 (between idx10's carved cell
// and idx9's intact one) -- this is hit_point for every test using this
// field.
voxel::DistanceField make_single_cavity_field() {
    std::vector<std::int8_t> z_values(65, -100);
    for (int i = 10; i <= 24; ++i) z_values[static_cast<std::size_t>(i)] = 100;
    return make_z_slab_field(glm::ivec3(4, 4, 65), glm::vec3(-10.0f, -10.0f, -50.0f),
                             glm::vec3(5.0f), z_values);
}

// `n` independent damage sites along Z, each a realistic 3-cell (75 model
// unit) carved band separated by 2 cells (50 model units) of untouched
// field, period 5 cells (125 model units): site i's carved cells are
// [5*i+2, 5*i+4], body z in [25*(5*i+2), 25*(5*i+5)] = [125*i+50, 125*i+125].
//
// n=30 is used deliberately, not an arbitrary "a lot": scenegraph::
// HullCarveField::kMaxCarves is 24, so a field encoding 30 independent sites
// — built here with NO HullCarveField anywhere in this file, since
// draw_instance()'s new signature no longer takes one — is structurally
// beyond anything a 24-slot sphere ring could ever represent, by
// construction rather than by argument.
//
// `kPadCells` (3 cells = 75 model units) of untouched field follow the
// last site. The negative-control test below does NOT rely on this pad
// being wider than the search budget (an EARLIER version of this field and
// its camera did exactly that, and the fix that widened
// find_breach_entry's own reach to properly span a whole box -- see that
// function's derivation in breach.frag -- broke it: a "negative control"
// whose only defence is "the search can't reach that far" stops being a
// negative control once the search CAN reach that far, which was the whole
// point of the fix). Instead the negative-control camera sits INSIDE this
// pad and looks AWAY from every site (toward increasing Z, out of the
// box) -- see cam_looking_away's own comment -- so the ENTIRE remaining
// ray, out to the box's own edge, is genuinely, unconditionally untouched
// field, regardless of how large the search's own budget is.
// Box: x,y in [0,100], z in [0, 125*n + 25*kPadCells].
voxel::DistanceField make_multi_site_field(int n) {
    const int period    = 5;
    const int kPadCells = 3;
    const int dims_z    = period * n + kPadCells;
    std::vector<std::int8_t> z_values(static_cast<std::size_t>(dims_z), -100);
    for (int i = 0; i < n; ++i) {
        z_values[static_cast<std::size_t>(period * i + 2)] = 100;
        z_values[static_cast<std::size_t>(period * i + 3)] = 100;
        z_values[static_cast<std::size_t>(period * i + 4)] = 100;
    }
    return make_z_slab_field(glm::ivec3(4, 4, dims_z), glm::vec3(0.0f), glm::vec3(25.0f),
                             z_values);
}

// Body-frame Z centre of multi-site field site `i`'s MIDDLE carved cell
// (5*i+3), matching make_multi_site_field's own layout above.
float multi_site_z(int i) {
    return (5.0f * static_cast<float>(i) + 3.5f) * 25.0f;
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

    // Camera for make_single_cavity_field(): starts at z=270, deep in the
    // field's own "intact after" region (idx 25-64, z in [75,275]), 195
    // model units clear of the carved band's own high-z edge (75). That
    // distance is chosen to be BEYOND the pre-fix entry search's reach
    // (64 steps * 0.5 * cell(5) = 160 model units) and WITHIN the fixed
    // one's (64 * kBreachCoarseStride(25) = 1600) -- see
    // make_single_cavity_field's own comment for why this, not just a
    // wide-enough carved band, is what makes this file's tests actually
    // discriminate the reach fix rather than merely the stride fix.
    // target=(0,0,-50) (deep in the intact-before region) gives a pure -Z
    // ray direction; far=400 clears the box's own exit distance
    // (|270-(-50)|=320).
    static scenegraph::Camera cam_through_cavity() {
        scenegraph::Camera c;
        c.eye    = glm::vec3(0.f, 0.f, 270.f);
        c.target = glm::vec3(0.f, 0.f, -50.f);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = 400.f;
        return c;
    }

    // Camera aimed at Z location `target_z` in a multi_site field (x,y =
    // 50,50 -- centred on that field's x,y = [0,100] box), positioned
    // CLOSE to it (45 units of +Z head-room -- comfortably above one
    // carved band's own 75-unit thickness, half-width 37.5) rather than
    // far above the whole field, so find_breach_entry's search begins
    // exactly where the test means it to (see this file's header comment
    // and make_multi_site_field's own comment for why "far away, search
    // inward" stopped being a valid design once the search's own reach was
    // fixed to span the whole box).
    static scenegraph::Camera cam_at_site(float target_z, float far_hint) {
        scenegraph::Camera c;
        c.eye    = glm::vec3(50.f, 50.f, target_z + 45.f);
        c.target = glm::vec3(50.f, 50.f, target_z);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = far_hint;
        return c;
    }

    // Negative-control camera for the "beyond 24 carves" test: `eye_z` sits
    // INSIDE make_multi_site_field's own trailing untouched pad, and the
    // ray looks TOWARD +Z (`target_z` > `eye_z`) -- AWAY from every carved
    // site, which all sit at LOWER z. The remaining ray, from `eye_z` to
    // the box's own +Z edge, is therefore genuinely, unconditionally clear
    // of carved material, independent of the search's own budget -- unlike
    // a "camera far away, ray travels back toward the sites" design, which
    // a sufficiently large search budget will always eventually defeat
    // (see make_multi_site_field's own comment for why an earlier version
    // of this test relied on exactly that and broke when the entry search's
    // reach was fixed).
    static scenegraph::Camera cam_looking_away(float eye_z, float target_z) {
        scenegraph::Camera c;
        c.eye    = glm::vec3(50.f, 50.f, eye_z);
        c.target = glm::vec3(50.f, 50.f, target_z);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = 5000.f;
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
    scenegraph::Camera cam = cam_through_cavity();

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
    scenegraph::Camera cam = cam_through_cavity();

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
    scenegraph::Camera cam = cam_through_cavity();

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
    scenegraph::Camera cam = cam_through_cavity();

    pass.draw_instance(/*instance_key=*/4, fill, entry,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-field draw";
    EXPECT_EQ(pass.draw_calls(), 0u) << "no field entry -- draw_instance() must return early";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no field entry — the pass should be a no-op";
}

// hit_point for make_single_cavity_field() + cam_through_cavity(): the EXIT
// crossing near body z=0 (see that field's own comment), x,y~=0 for the
// screen-centre ray. Used by the rim-emissive tests below to place
// u_breach_center where hit_point actually lands -- Task 3 obligation #2
// (breach.frag's u_breach_center comment) means heat is now gated by
// distance from that centre too, not just by age, so a test of the AGE
// gate specifically must put the "fresh" event's centre where the shaded
// point actually is, or the position gate would zero heat regardless of
// age and the test would prove nothing about age at all.
constexpr float kCavityHitX = 0.0f;
constexpr float kCavityHitY = 0.0f;
constexpr float kCavityHitZ = 0.0f;

TEST_F(BreachPassGLTest, HotBreachBrighterThanCold) {
    const voxel::DistanceField field = make_single_cavity_field();
    scenegraph::Camera cam = cam_through_cavity();
    const glm::vec3 hit_center(kCavityHitX, kCavityHitY, kCavityHitZ);

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
                           scenegraph::kRimLife + 1.f,  // cold
                           hit_center, 100.f);
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
        pass.draw_instance(/*instance_key=*/11, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline,
                           0.f,  // fresh (hot)
                           hit_center, 100.f);
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
// would match HotBreachBrighterThanCold's hot_sum, not its cold_sum.
TEST_F(BreachPassGLTest, HotBreachFarFromHitPointDoesNotReignite) {
    const voxel::DistanceField field = make_single_cavity_field();
    scenegraph::Camera cam = cam_through_cavity();

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
        pass.draw_instance(/*instance_key=*/12, fill, entry,
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
        pass.draw_instance(/*instance_key=*/13, fill, entry,
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
// isolation -- that function is UNCHANGED; the fix lives in main(), which
// this pair exercises end-to-end through the real production shader). ──────

// Negative: make_single_cavity_field()'s hit_point (the EXIT crossing, near
// z=0) sits well outside thin_plate_fill()'s only solid material
// (z=[85,100], near the band's OTHER edge). Must discard: "a hole is a hole".
TEST_F(BreachPassGLTest, HitWithNoBackingMaterialDoesNotPaint) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = thin_plate_fill();
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    scenegraph::Camera cam = cam_through_cavity();

    pass.draw_instance(/*instance_key=*/20, fill, entry,
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
// box (solid_fill(), which spans z=[-50,200] -- past both thin_plate_fill's
// z=[65,75] and hit_point's z~=0). Proves the negative result above is
// not a vacuously-always-discarding check -- flipping only the fill flips
// the outcome.
TEST_F(BreachPassGLTest, HitWithRealBackingMaterialPaints) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    mark_hull_cut();

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();   // covers [-50,275] on Z -- includes hit_point~z=0
    const voxel::DistanceField field = make_single_cavity_field();
    const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
    scenegraph::Camera cam = cam_through_cavity();

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
    const float field_max_z = field.origin.z + field.dims.z * field.cell.z;  // 3825

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

    // Negative control: camera sits ONE CELL (25 units) inside the field's
    // own trailing untouched pad (dims_z=153, so pad cells are [150,153),
    // body z in [3750,3825]; eye at z=3775 is 25 units past the pad's own
    // start) and looks AWAY from every site (target_z=3825, the box's own
    // +Z edge) -- see cam_looking_away's own comment for why this, not a
    // "far away and hope the budget doesn't reach", is what makes this a
    // genuine negative control. Must stay background: rules out "this
    // field renders an interior everywhere regardless of the camera",
    // which would make the positive result above vacuous.
    {
        clear_framebuffer();
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        mark_hull_cut();

        renderer::BreachPass pass;
        const renderer::InstanceFieldCache::Entry entry = make_field_entry(field);
        scenegraph::Camera cam = cam_looking_away(/*eye_z=*/3775.f, /*target_z=*/field_max_z);

        pass.draw_instance(/*instance_key=*/32, fill, entry,
                           glm::mat4(1.0f), cam, *pipeline);
        glFinish();
        EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error looking away into the pad";
        auto px = read_center();
        EXPECT_LT(px[0] + px[1] + px[2], 16)
            << "Centre pixel lit while looking away from every site into the field's own "
               "untouched tail -- expected background, or the positive result at site 29 "
               "would not be meaningful evidence";
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
    scenegraph::Camera cam = cam_through_cavity();

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
    scenegraph::Camera cam = cam_through_cavity();

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
