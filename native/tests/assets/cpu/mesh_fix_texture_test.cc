// Tests for the mesh-fix per-shape albedo texture op (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md §6).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>

#include "model_build.h"
#include "support/content_root.h"

#include <filesystem>
#include <iterator>
#include <fstream>
#include <string>
#include <vector>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

// Root NiNode (id 1) carrying texture property (id 10 -> image id 11,
// "a.tga") and two child shapes "Left" (id 2, data 3) and "Right" (id 4,
// data 5). Both inherit a.tga -- the DBridge layout: one ancestor texture
// shared by many unnamed shapes.
nif::NiTriShapeData tri() {
    nif::NiTriShapeData d;
    d.num_vertices = 3;
    d.has_vertices = d.has_uv = true;
    d.vertices = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
    d.uv_sets = {{{0, 0}, {1, 0}, {0, 1}}};
    d.num_triangles = 1; d.num_triangle_points = 3;
    d.triangles = {{0, 1, 2}};
    return d;
}

nif::File make() {
    nif::File f;
    nif::NiNode root; root.av.obj.name = "root";
    root.child_links = {2, 4};
    root.av.property_links = {10};
    nif::NiTriShape left;  left.av.obj.name = "Left";  left.data_link = 3;
    nif::NiTriShape right; right.av.obj.name = "Right"; right.data_link = 5;
    nif::NiTextureProperty tex; tex.flags = 0x0000; tex.image_link = 11;
    nif::NiImage img; img.use_external = 1; img.file_name = "a.tga";
    f.blocks = {root, left, tri(), right, tri(), tex, img};
    f.block_ids = {1, 2, 3, 4, 5, 10, 11};
    f.root = nif::BlockHandle{&f.blocks.front()};
    return f;
}

assets::MeshFix fix_of(std::uint32_t block, std::string albedo) {
    assets::MeshFix fix;
    fix.textures = {{block, std::move(albedo)}};
    return fix;
}

assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(0, 0, 0, static_cast<std::uint32_t>(cpu.indices.size()),
                        cpu.material_index, cpu.node_index);
}

// Minimal valid 2x1 24-bit uncompressed TGA.
void write_tga(const fs::path& p) {
    const std::vector<std::uint8_t> b = {0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0,
                                         24, 0, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
    std::ofstream(p, std::ios::binary).write(reinterpret_cast<const char*>(b.data()),
                                             static_cast<std::streamsize>(b.size()));
}

fs::path temp_dir(const char* tag) {
#ifdef _WIN32
    const int pid = _getpid();
#else
    const int pid = ::getpid();
#endif
    auto d = fs::temp_directory_path() /
             ("mesh-fix-tex-" + std::string(tag) + "-" + std::to_string(pid));
    fs::remove_all(d);
    fs::create_directories(d);
    return d;
}

// Authored source basename of the Base-stage texture of every mesh built
// from the shape named `shape`; all must agree. "" if no such mesh.
std::string base_source_of(const assets::Model& m,
                           const std::vector<std::string>& sources,
                           const std::string& shape) {
    std::string out;
    for (const auto& mesh : m.meshes) {
        if (mesh.shape_name() != shape) continue;
        const auto& mat = m.materials.at(static_cast<std::size_t>(mesh.material_index()));
        const int ti = mat.stages[static_cast<std::size_t>(
            assets::Material::StageSlot::Base)].texture_index;
        const std::string src = ti >= 0 ? sources.at(static_cast<std::size_t>(ti)) : "<none>";
        if (!out.empty() && out != src) return "<mixed>";
        out = src;
    }
    return out;
}

assets::Model build(const nif::File& f, assets::PathResolver& resolver,
                    std::vector<fs::path> dirs, std::vector<std::string>* sources) {
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = std::move(dirs);
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    ctx.out_texture_sources = sources;
    return assets::detail::build_model(f, ctx);
}

}  // namespace

TEST(MeshFixTextureParse, TexturesOnlyFileParses) {
    std::string err;
    auto fix = assets::parse_mesh_fix(
        R"({"format":1,"textures":[{"block":29,"albedo":"g_imp_connops.tga"},
                                   {"block":45,"albedo":"Map 7.tga"}]})", &err);
    ASSERT_TRUE(fix.has_value()) << err;
    EXPECT_TRUE(fix->merges.empty());
    EXPECT_TRUE(fix->shape_edits.empty());
    ASSERT_EQ(fix->textures.size(), 2u);
    EXPECT_EQ(fix->textures[0].block, 29u);
    EXPECT_EQ(fix->textures[0].albedo, "g_imp_connops.tga");
    EXPECT_EQ(fix->textures[1].albedo, "Map 7.tga");
}

TEST(MeshFixTextureParse, RefusesMalformedTextureEntry) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(
        R"({"format":1,"textures":[{"block":29}]})", &err).has_value());
    EXPECT_FALSE(assets::parse_mesh_fix(
        R"({"format":1,"textures":[{"block":29,"albedo":7}]})", &err).has_value());
}

TEST(MeshFixTexture, SwapsOnlyTheListedShapeNotItsSibling) {
    auto f = make();
    ASSERT_EQ(assets::apply_mesh_fix(f, fix_of(1, "b.tga")), "");
    // Root still points at block 0 after the block vector grew.
    EXPECT_EQ(f.root.ptr, &f.blocks.front());
    EXPECT_EQ(f.blocks.size(), f.block_ids.size());

    auto dir = temp_dir("swap");
    write_tga(dir / "a.tga");
    write_tga(dir / "b.tga");
    assets::PathResolver resolver;
    std::vector<std::string> sources;
    auto model = build(f, resolver, {dir}, &sources);
    EXPECT_EQ(base_source_of(model, sources, "Left"), "b.tga");
    EXPECT_EQ(base_source_of(model, sources, "Right"), "a.tga");
    fs::remove_all(dir);
}

TEST(MeshFixTexture, CoexistsWithAShapeEditOnTheSameBlock) {
    auto f = make();
    auto fix = fix_of(1, "b.tga");
    assets::ShapeEdit e;
    e.block = 1; e.orig_vertex_count = 3; e.orig_triangle_count = 1;
    e.moves = {{0, {0.5f, 0.5f, 0.5f}}};
    fix.shape_edits = {e};
    ASSERT_EQ(assets::apply_mesh_fix(f, fix), "");
    EXPECT_FLOAT_EQ(std::get<nif::NiTriShapeData>(f.blocks[2]).vertices[0].x, 0.5f);
    EXPECT_EQ(std::get<nif::NiTriShape>(f.blocks[1]).av.property_links.size(), 1u);
}

namespace {
void expect_refused(const assets::MeshFix& fix, const char* why) {
    auto f = make();
    const auto n_blocks = f.blocks.size();
    EXPECT_NE(assets::apply_mesh_fix(f, fix), "") << why;
    EXPECT_EQ(f.blocks.size(), n_blocks) << why;
    EXPECT_EQ(f.block_ids.size(), n_blocks) << why;
    EXPECT_TRUE(std::get<nif::NiTriShape>(f.blocks[1]).av.property_links.empty()) << why;
    EXPECT_TRUE(std::get<nif::NiTriShape>(f.blocks[3]).av.property_links.empty()) << why;
}
}  // namespace

TEST(MeshFixTexture, RefusalsLeaveFileUntouched) {
    expect_refused(fix_of(99, "b.tga"), "block out of range");
    expect_refused(fix_of(0, "b.tga"), "not a trishape (NiNode)");
    expect_refused(fix_of(2, "b.tga"), "not a trishape (data)");
    expect_refused(fix_of(1, ""), "empty albedo");
    expect_refused(fix_of(1, "High/b.tga"), "forward slash");
    expect_refused(fix_of(1, "High\\b.tga"), "backslash");
    expect_refused(fix_of(1, "b"), "no extension");
    expect_refused(fix_of(1, "b.txt"), "not an image");
    // Reserved suffixes bind to a non-Base slot (model_build.cc filename_is_*).
    expect_refused(fix_of(1, "panel_glow.tga"), "glow suffix");
    expect_refused(fix_of(1, "panel_GLOW.TGA"), "glow suffix, uppercase");
    expect_refused(fix_of(1, "panel_specular.tga"), "specular suffix");
    expect_refused(fix_of(1, "panel_spec.tga"), "spec suffix");
    expect_refused(fix_of(1, "panel_normal.tga"), "normal suffix");
    expect_refused(fix_of(1, "panel_Norm.tga"), "norm suffix");
    // Emissive sibling names (task 17) are derived maps, never albedos.
    expect_refused(fix_of(1, "panel_emissive.tga"), "emissive suffix");
    expect_refused(fix_of(1, "panel_emissive_y.tga"), "yellow emissive suffix");
    expect_refused(fix_of(1, "panel_Emissive_R.TGA"), "red emissive suffix, mixed case");
    expect_refused(fix_of(1, "panel_emissive_s.tga"), "special emissive suffix");
    {
        auto fix = fix_of(1, "b.tga");
        fix.textures.push_back({1, "c.tga"});
        expect_refused(fix, "same block twice");
    }
    {   // a valid texture op does not survive a failing shape edit
        auto fix = fix_of(1, "b.tga");
        assets::ShapeEdit e;
        e.block = 3; e.orig_vertex_count = 9; e.orig_triangle_count = 1;
        fix.shape_edits = {e};
        expect_refused(fix, "valid texture + refused shape edit");
    }
}

TEST(MeshFixTexture, EmissiveRefusalNamesTheSuffix) {
    auto f = make();
    const std::string why = assets::apply_mesh_fix(f, fix_of(1, "Map 22a_emissive_y.tga"));
    EXPECT_NE(why.find("_emissive_y"), std::string::npos) << why;
    EXPECT_NE(why.find("emissive"), std::string::npos) << why;
}

TEST(MeshFixTexture, AcceptsUppercaseTgaExtension) {
    auto f = make();
    EXPECT_EQ(assets::apply_mesh_fix(f, fix_of(1, "B.TGA")), "");
}

// Real DBridge: blocks 29 and 59 are unnamed shapes that both inherit
// "Map 22.tga" from an ancestor. A texture op on 29 must retexture 29 alone.
// The shapes are unnamed, so the test names them in memory (after the fix,
// before the build) to find their meshes via Mesh::shape_name().
TEST(MeshFixTexture, RealDbridgeBlock29TakesTheNewTextureAndBlock59KeepsItsOwn) {
    const fs::path nif = test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF";
    const fs::path tex = test_support::game_root() / "data/Models/Sets/DBridge/High";
    if (!fs::exists(nif)) GTEST_SKIP() << "DBridge not installed";

    auto f = nif::load(nif);
    ASSERT_TRUE(std::holds_alternative<nif::NiTriShape>(f.blocks.at(29)));
    ASSERT_TRUE(std::holds_alternative<nif::NiTriShape>(f.blocks.at(59)));
    ASSERT_EQ(assets::apply_mesh_fix(f, fix_of(29, "Map 7.tga")), "");
    std::get<nif::NiTriShape>(f.blocks[29]).av.obj.name = "T29";
    std::get<nif::NiTriShape>(f.blocks[59]).av.obj.name = "T59";

    assets::PathResolver resolver;
    std::vector<std::string> sources;
    auto model = build(f, resolver, {tex}, &sources);
    EXPECT_EQ(base_source_of(model, sources, "T29"), "Map 7.tga");
    EXPECT_EQ(base_source_of(model, sources, "T59"), "Map 22.tga");
}

// Every block the first texture round targets (console top panels 29/59,
// wall inset slots 45/479) must take a swapped albedo: none may sit under an
// ancestor NiMultiTextureProperty whose stage 0 would overwrite Base after
// the NiTextureProperty is applied (material_build.cc ordering).
TEST(MeshFixTexture, RealDbridgeRoundTwoTargetsAllTakeTheSwap) {
    const fs::path nif = test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF";
    const fs::path tex = test_support::game_root() / "data/Models/Sets/DBridge/High";
    if (!fs::exists(nif)) GTEST_SKIP() << "DBridge not installed";

    auto f = nif::load(nif);
    assets::MeshFix fix;
    for (std::uint32_t b : {29u, 45u, 59u, 479u}) fix.textures.push_back({b, "Map 7.tga"});
    ASSERT_EQ(assets::apply_mesh_fix(f, fix), "");
    for (std::uint32_t b : {29u, 45u, 59u, 479u})
        std::get<nif::NiTriShape>(f.blocks[b]).av.obj.name = "T" + std::to_string(b);

    assets::PathResolver resolver;
    std::vector<std::string> sources;
    auto model = build(f, resolver, {tex}, &sources);
    for (std::uint32_t b : {29u, 45u, 59u, 479u})
        EXPECT_EQ(base_source_of(model, sources, "T" + std::to_string(b)), "Map 7.tga") << b;
}

namespace {
// A valid merge (target "saucer" idx1/data idx2, patch "id" idx3/data idx4),
// the same layout as mesh_fix_shape_edit_test.cc's merge fixture.
nif::NiTriShapeData merge_quad(float x0, float x1, float u0, float u1) {
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_normals = d.has_uv = true;
    d.vertices = {{x0,0,0},{x1,0,0},{x1,1,0},{x0,1,0}};
    d.normals  = {{0,0,1},{0,0,1},{0,0,1},{0,0,1}};
    d.uv_sets  = {{{u0,0},{u1,0},{u1,1},{u0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    return d;
}
}  // namespace

TEST(MeshFixTexture, RefusesATextureOpOnAMergesHiddenPatch) {
    nif::File f;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4};
    nif::NiTriShape target; target.av.obj.name = "saucer"; target.data_link = 3;
    nif::NiTriShape patch;  patch.av.obj.name  = "id";     patch.data_link  = 5;
    f.blocks = {root, target, merge_quad(0, 1, 0, 0.5f), patch, merge_quad(1, 2, 0, 1)};
    f.block_ids = {1, 2, 3, 4, 5};
    f.root = nif::BlockHandle{&f.blocks.front()};
    assets::MeshFixMerge m;
    m.patch = {3, "id"}; m.target = {1, "saucer"};
    m.uvs = {{0.5f,0},{1.0f,0},{1.0f,1},{0.5f,1}};
    m.weld = {{0,1},{3,2}};
    assets::MeshFix fix;
    fix.merges = {m};
    fix.textures = {{3, "b.tga"}};
    EXPECT_NE(assets::apply_mesh_fix(f, fix), "");
    EXPECT_EQ(f.blocks.size(), 5u);
    EXPECT_FALSE(std::get<nif::NiTriShape>(f.blocks[3]).av.flags & 0x0001u);  // merge not applied
    fix.textures = {{1, "b.tga"}};                          // the TARGET is fine
    EXPECT_EQ(assets::apply_mesh_fix(f, fix), "");
}

// Task 17: the real DBridge through the COMMITTED mesh fix and the project
// replacements overlay, loaded with the interior sibling policy exactly as
// host_loop.realize_set does (overlay dir first in the search list, and as the
// sibling overlay). The fix's spliced albedos pick up their `_emissive*`
// siblings from the overlay: Map 22a has all three; g_imp_redbars the default
// only. g_imp_connops has a Lottie panel (`g_imp_connops.json`, bridge Lottie
// panels spec §6), which sets its `_emissive` sibling aside: both tops share
// one panel instead.
namespace {
// Emissive-slot texture index of every mesh built from shape `shape`; all
// must agree. -2 if no such mesh, -3 if they disagree.
int emissive_slot_of(const assets::Model& m, const std::string& shape,
                     assets::Material::StageSlot slot) {
    int out = -2;
    for (const auto& mesh : m.meshes) {
        if (mesh.shape_name() != shape) continue;
        const auto& mat = m.materials.at(static_cast<std::size_t>(mesh.material_index()));
        const int ti = mat.stages[static_cast<std::size_t>(slot)].texture_index;
        if (out != -2 && out != ti) return -3;
        out = ti;
    }
    return out;
}

// Material::panel_index of every mesh built from shape `shape`; -2 if no
// such mesh, -3 if they disagree.
int panel_of(const assets::Model& m, const std::string& shape) {
    int out = -2;
    for (const auto& mesh : m.meshes) {
        if (mesh.shape_name() != shape) continue;
        const int pi = m.materials.at(static_cast<std::size_t>(mesh.material_index())).panel_index;
        if (out != -2 && out != pi) return -3;
        out = pi;
    }
    return out;
}
}  // namespace

TEST(MeshFixTexture, RealDbridgeCommittedFixShapesGetTheirEmissiveSiblings) {
    const fs::path nif = test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF";
    const fs::path stock = test_support::game_root() / "data/Models/Sets/DBridge/High";
    const fs::path overlay = test_support::project_root() /
        "native/assets/replacements/data/Models/Sets/DBridge/High";
    if (!fs::exists(nif)) GTEST_SKIP() << "DBridge not installed";

    std::ifstream in(nif, std::ios::binary);
    const std::string bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    const fs::path fix_path = test_support::project_root() / "native/assets/mesh_fixes" /
                              (assets::fnv1a64_hex(bytes) + ".json");
    ASSERT_TRUE(fs::exists(fix_path)) << "no committed fix for this Dbridge.NIF: " << fix_path;
    std::ifstream fin(fix_path, std::ios::binary);
    const std::string text((std::istreambuf_iterator<char>(fin)), std::istreambuf_iterator<char>());
    std::string err;
    auto fix = assets::parse_mesh_fix(text, &err);
    ASSERT_TRUE(fix.has_value()) << err;

    auto f = nif::load(nif);
    ASSERT_EQ(assets::apply_mesh_fix(f, *fix), "");
    const std::vector<std::uint32_t> map22a = {395, 471};
    const std::vector<std::uint32_t> redbars = {45, 479, 697};
    const std::vector<std::uint32_t> connops = {29, 59};
    const std::vector<std::uint32_t> map22d = {121, 124};    // round 7: seat panels
    for (const auto* group : {&map22a, &redbars, &connops, &map22d})
        for (std::uint32_t b : *group)
            std::get<nif::NiTriShape>(f.blocks.at(b)).av.obj.name = "T" + std::to_string(b);

    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {overlay, stock};
    ctx.sibling_overlay_dirs = {overlay};
    ctx.interior_sibling_policy = true;
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;
    auto model = assets::detail::build_model(f, ctx);

    using S = assets::Material::StageSlot;
    for (std::uint32_t b : map22a) {
        const std::string n = "T" + std::to_string(b);
        EXPECT_GE(emissive_slot_of(model, n, S::Emissive), 0) << n;
        EXPECT_GE(emissive_slot_of(model, n, S::EmissiveYellow), 0) << n;
        EXPECT_GE(emissive_slot_of(model, n, S::EmissiveRed), 0) << n;
    }
    for (std::uint32_t b : redbars) {
        const std::string n = "T" + std::to_string(b);
        EXPECT_GE(emissive_slot_of(model, n, S::Emissive), 0) << n;
        EXPECT_EQ(emissive_slot_of(model, n, S::EmissiveYellow), -1) << n;
        EXPECT_EQ(emissive_slot_of(model, n, S::EmissiveRed), -1) << n;
    }
    for (std::uint32_t b : connops) {
        const std::string n = "T" + std::to_string(b);
        EXPECT_EQ(emissive_slot_of(model, n, S::Emissive), -1) << n;
        EXPECT_GE(panel_of(model, n), 0) << n;
    }
    EXPECT_EQ(panel_of(model, "T29"), panel_of(model, "T59"));   // one panel per file
    for (std::uint32_t b : map22d) {
        const std::string n = "T" + std::to_string(b);
        EXPECT_GE(emissive_slot_of(model, n, S::Emissive), 0) << n;
        EXPECT_EQ(emissive_slot_of(model, n, S::EmissiveYellow), -1) << n;
        EXPECT_EQ(emissive_slot_of(model, n, S::EmissiveRed), -1) << n;
    }
}
