// Tests for the mesh-fix texture op's flipbook extension (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md §6): a
// shape's albedo becomes a looping frame set driven by a spliced
// NiFlipController, shaped like BC's only stock one (EBridge.nif block 550).
#include <gtest/gtest.h>
#include <assets/flip_frame.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>

#include "model_build.h"
#include "support/content_root.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

// Same layout as mesh_fix_texture_test.cc: root NiNode (id 1) with texture
// property 10 -> image 11 ("a.tga") shared by shapes "Left" (block 1) and
// "Right" (block 3).
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

std::vector<std::string> frame_names(int n) {
    std::vector<std::string> out;
    for (int i = 0; i < n; ++i) out.push_back("f" + std::to_string(i) + ".tga");
    return out;
}

assets::MeshFix flip_fix(std::uint32_t block, std::vector<std::string> frames, float fps) {
    assets::MeshFix fix;
    assets::MeshFixTexture t;
    t.block = block;
    t.albedo = frames.empty() ? std::string("f0.tga") : frames.front();
    t.flipbook = assets::MeshFixFlipbook{std::move(frames), fps};
    fix.textures = {std::move(t)};
    return fix;
}

assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/0, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(0, 0, 0, static_cast<std::uint32_t>(cpu.indices.size()),
                        cpu.material_index, cpu.node_index);
}

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
             ("mesh-fix-flip-" + std::string(tag) + "-" + std::to_string(pid));
    fs::remove_all(d);
    fs::create_directories(d);
    return d;
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

// The material of the (single, or all-agreeing) mesh built from `shape`.
const assets::Material* material_of(const assets::Model& m, const std::string& shape) {
    const assets::Material* out = nullptr;
    for (const auto& mesh : m.meshes) {
        if (mesh.shape_name() != shape) continue;
        out = &m.materials.at(static_cast<std::size_t>(mesh.material_index()));
    }
    return out;
}

// Source basename `shape` binds as Base at game time `t`.
std::string base_at(const assets::Model& m, const std::vector<std::string>& sources,
                    const std::string& shape, double t) {
    const auto* mat = material_of(m, shape);
    if (!mat) return "<no mesh>";
    const int ti = assets::animated_base_texture(m, *mat, t);
    return ti >= 0 ? sources.at(static_cast<std::size_t>(ti)) : "<none>";
}

std::size_t index_of_id(const nif::File& f, std::uint32_t id) {
    for (std::size_t i = 0; i < f.block_ids.size(); ++i)
        if (f.block_ids[i] == id) return i;
    return static_cast<std::size_t>(-1);
}

}  // namespace

TEST(MeshFixFlipbookParse, ParsesFramesAndFps) {
    std::string err;
    auto fix = assets::parse_mesh_fix(
        R"({"format":1,"textures":[{"block":688,"albedo":"running_0.tga",
             "flipbook":{"frames":["running_0.tga","running_1.tga","running_2.tga"],
                         "fps":5.0}},
            {"block":29,"albedo":"Map 7.tga"}]})", &err);
    ASSERT_TRUE(fix.has_value()) << err;
    ASSERT_EQ(fix->textures.size(), 2u);
    ASSERT_TRUE(fix->textures[0].flipbook.has_value());
    EXPECT_EQ(fix->textures[0].flipbook->frames,
              (std::vector<std::string>{"running_0.tga", "running_1.tga", "running_2.tga"}));
    EXPECT_FLOAT_EQ(fix->textures[0].flipbook->fps, 5.0f);
    EXPECT_FALSE(fix->textures[1].flipbook.has_value());
}

TEST(MeshFixFlipbookParse, RefusesMalformedFlipbook) {
    std::string err;
    for (const char* bad : {
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":{"fps":5}}]})",
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":{"frames":["a.tga","b.tga"]}}]})",
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":{"frames":"a.tga","fps":5}}]})",
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":{"frames":["a.tga",3],"fps":5}}]})",
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":{"frames":["a.tga","b.tga"],"fps":"5"}}]})",
             R"({"format":1,"textures":[{"block":1,"albedo":"a.tga","flipbook":7}]})",
         }) {
        EXPECT_FALSE(assets::parse_mesh_fix(bad, &err).has_value()) << bad;
    }
}

TEST(MeshFixFlipbook, AnimatesTheListedShapeAtFpsAndLoops) {
    auto f = make();
    const int n = 4;
    const float fps = 5.0f;
    ASSERT_EQ(assets::apply_mesh_fix(f, flip_fix(1, frame_names(n), fps)), "");
    EXPECT_EQ(f.root.ptr, &f.blocks.front());
    EXPECT_EQ(f.blocks.size(), f.block_ids.size());

    auto dir = temp_dir("anim");
    write_tga(dir / "a.tga");
    for (const auto& name : frame_names(n)) write_tga(dir / name);
    assets::PathResolver resolver;
    std::vector<std::string> sources;
    auto model = build(f, resolver, {dir}, &sources);

    const auto* left = material_of(model, "Left");
    ASSERT_NE(left, nullptr);
    ASSERT_GE(left->animation_index, 0);
    ASSERT_LT(left->animation_index, static_cast<int>(model.texture_animations.size()));
    EXPECT_EQ(model.texture_animations[static_cast<std::size_t>(left->animation_index)]
                  .texture_indices.size(), static_cast<std::size_t>(n));

    constexpr double eps = 1e-3;
    for (int k = 0; k < n; ++k)
        EXPECT_EQ(base_at(model, sources, "Left", k / double(fps) + eps),
                  "f" + std::to_string(k) + ".tga") << k;
    EXPECT_EQ(base_at(model, sources, "Left", n / double(fps) + eps), "f0.tga");     // wraps
    EXPECT_EQ(base_at(model, sources, "Left", (n + 1) / double(fps) + eps), "f1.tga");

    const auto* right = material_of(model, "Right");
    ASSERT_NE(right, nullptr);
    EXPECT_EQ(right->animation_index, -1);
    EXPECT_EQ(base_at(model, sources, "Right", 0.5), "a.tga");
    fs::remove_all(dir);
}

// The spliced property/controller/images carry exactly the stock EBridge
// shape (see MeshFixFlipbook.RealEbridgeStockControllerHasTheMirroredShape).
TEST(MeshFixFlipbook, SplicedBlocksMirrorTheStockFlipController) {
    auto f = make();
    ASSERT_EQ(assets::apply_mesh_fix(f, flip_fix(1, frame_names(3), 4.0f)), "");
    const auto& shape = std::get<nif::NiTriShape>(f.blocks[1]);
    ASSERT_EQ(shape.av.property_links.size(), 1u);
    const std::uint32_t prop_id = shape.av.property_links[0];
    const auto prop_idx = index_of_id(f, prop_id);
    ASSERT_LT(prop_idx, f.blocks.size());
    const auto& prop = std::get<nif::NiTextureProperty>(f.blocks[prop_idx]);
    EXPECT_EQ(prop.flags, 0u);
    EXPECT_EQ(prop.image_link, 0u);  // stock: the controller alone supplies images
    const auto ctrl_idx = index_of_id(f, prop.obj.controller_link);
    ASSERT_LT(ctrl_idx, f.blocks.size());
    const auto& c = std::get<nif::NiFlipController>(f.blocks[ctrl_idx]);
    EXPECT_EQ(c.next_controller_link, 0u);
    EXPECT_EQ(c.flags, 0x0009u);
    EXPECT_FLOAT_EQ(c.frequency, 1.0f);
    EXPECT_FLOAT_EQ(c.phase, 0.0f);
    EXPECT_FLOAT_EQ(c.start_time, 0.0f);
    EXPECT_FLOAT_EQ(c.delta, 0.25f);
    EXPECT_FLOAT_EQ(c.stop_time, 3 * 0.25f);
    EXPECT_EQ(c.unknown_integer, prop_id);  // v3.1 target link -> the property
    EXPECT_EQ(c.texture_slot, 0u);
    ASSERT_EQ(c.num_sources, 3u);
    ASSERT_EQ(c.image_links.size(), 3u);
    for (std::size_t k = 0; k < 3; ++k) {
        const auto img_idx = index_of_id(f, c.image_links[k]);
        ASSERT_LT(img_idx, f.blocks.size());
        const auto& img = std::get<nif::NiImage>(f.blocks[img_idx]);
        EXPECT_EQ(img.use_external, 1u);
        EXPECT_EQ(img.file_name, "f" + std::to_string(k) + ".tga");
    }
    // Link ids unique.
    std::vector<std::uint32_t> ids = f.block_ids;
    std::sort(ids.begin(), ids.end());
    EXPECT_EQ(std::adjacent_find(ids.begin(), ids.end()), ids.end());
}

namespace {
void expect_refused(const assets::MeshFix& fix, const char* why) {
    auto f = make();
    const auto n_blocks = f.blocks.size();
    EXPECT_NE(assets::apply_mesh_fix(f, fix), "") << why;
    EXPECT_EQ(f.blocks.size(), n_blocks) << why;
    EXPECT_EQ(f.block_ids.size(), n_blocks) << why;
    EXPECT_TRUE(std::get<nif::NiTriShape>(f.blocks[1]).av.property_links.empty()) << why;
}
}  // namespace

TEST(MeshFixFlipbook, RefusalsLeaveFileUntouched) {
    expect_refused(flip_fix(1, frame_names(1), 5.0f), "one frame");
    expect_refused(flip_fix(1, frame_names(257), 5.0f), "257 frames");
    expect_refused(flip_fix(1, {"f0.tga", "High/f1.tga"}, 5.0f), "frame with a directory");
    expect_refused(flip_fix(1, {"f0.tga", "High\\f1.tga"}, 5.0f), "frame with a backslash");
    expect_refused(flip_fix(1, {"f0.tga", ""}, 5.0f), "empty frame");
    expect_refused(flip_fix(1, {"f0.tga", "f1.png"}, 5.0f), "non-tga frame");
    expect_refused(flip_fix(1, {"f0.tga", "f1_glow.tga"}, 5.0f), "reserved-suffix frame");
    expect_refused(flip_fix(1, frame_names(3), 0.0f), "fps zero");
    expect_refused(flip_fix(1, frame_names(3), -5.0f), "fps negative");
    expect_refused(flip_fix(1, frame_names(3), std::numeric_limits<float>::quiet_NaN()),
                   "fps NaN");
    expect_refused(flip_fix(1, frame_names(3), std::numeric_limits<float>::infinity()),
                   "fps inf");
    {
        auto fix = flip_fix(1, frame_names(3), 5.0f);
        fix.textures[0].albedo = "f1.tga";
        expect_refused(fix, "albedo is not frames[0]");
    }
    {   // a valid flipbook does not survive a failing sibling op
        auto fix = flip_fix(1, frame_names(3), 5.0f);
        fix.textures.push_back({3, "b_glow.tga"});
        expect_refused(fix, "valid flipbook + refused texture op");
    }
}

TEST(MeshFixFlipbook, AcceptsTheBoundaryFrameCounts) {
    auto f2 = make();
    EXPECT_EQ(assets::apply_mesh_fix(f2, flip_fix(1, frame_names(2), 5.0f)), "");
    auto f256 = make();
    EXPECT_EQ(assets::apply_mesh_fix(f256, flip_fix(1, frame_names(256), 5.0f)), "");
}

// The fields the splice mirrors, read from BC's only stock flip controller
// (EBridge.nif: NiTextureProperty 549 -> NiFlipController 550, 8 LCARS
// frames at delta 1/6). Guards the constants in apply_texture against the
// real data rather than against a remembered value.
TEST(MeshFixFlipbook, RealEbridgeStockControllerHasTheMirroredShape) {
    const fs::path nif = test_support::game_root() / "data/Models/Sets/EBridge/EBridge.nif";
    if (!fs::exists(nif)) GTEST_SKIP() << "EBridge not installed";
    auto f = nif::load(nif);
    std::size_t found = 0;
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* prop = std::get_if<nif::NiTextureProperty>(&f.blocks[i]);
        if (!prop || prop->obj.controller_link == 0) continue;
        const auto ci = index_of_id(f, prop->obj.controller_link);
        ASSERT_LT(ci, f.blocks.size());
        const auto& c = std::get<nif::NiFlipController>(f.blocks[ci]);
        ++found;
        EXPECT_EQ(prop->flags, 0u);
        EXPECT_EQ(prop->image_link, 0u);
        EXPECT_EQ(c.next_controller_link, 0u);
        EXPECT_EQ(c.flags, 0x0009u);
        EXPECT_FLOAT_EQ(c.frequency, 1.0f);
        EXPECT_FLOAT_EQ(c.phase, 0.0f);
        EXPECT_FLOAT_EQ(c.start_time, 0.0f);
        EXPECT_NEAR(c.stop_time, static_cast<float>(c.num_sources) * c.delta, 1e-5f);
        EXPECT_EQ(c.unknown_integer, f.block_ids[i]);
        EXPECT_EQ(c.texture_slot, 0u);
        for (std::uint32_t link : c.image_links) {
            const auto& img = std::get<nif::NiImage>(f.blocks.at(index_of_id(f, link)));
            EXPECT_EQ(img.use_external, 1u);
            EXPECT_EQ(img.unknown_int, nif::NiImage{}.unknown_int);
            EXPECT_FLOAT_EQ(img.unknown_float, nif::NiImage{}.unknown_float);
        }
    }
    EXPECT_EQ(found, 1u);
}

// Real DBridge block 688 (the LCARS strip Mark rebuilds) animates between
// two stock textures.
TEST(MeshFixFlipbook, RealDbridgeBlock688Animates) {
    const fs::path nif = test_support::game_root() / "data/Models/Sets/DBridge/Dbridge.NIF";
    const fs::path tex = test_support::game_root() / "data/Models/Sets/DBridge/High";
    if (!fs::exists(nif)) GTEST_SKIP() << "DBridge not installed";

    auto f = nif::load(nif);
    ASSERT_TRUE(std::holds_alternative<nif::NiTriShape>(f.blocks.at(688)));
    assets::MeshFix fix;
    assets::MeshFixTexture t;
    t.block = 688;
    t.albedo = "Map 7.tga";
    t.flipbook = assets::MeshFixFlipbook{{"Map 7.tga", "Map 8.tga"}, 5.0f};
    fix.textures = {t};
    ASSERT_EQ(assets::apply_mesh_fix(f, fix), "");
    std::get<nif::NiTriShape>(f.blocks[688]).av.obj.name = "T688";

    assets::PathResolver resolver;
    std::vector<std::string> sources;
    auto model = build(f, resolver, {tex}, &sources);
    EXPECT_EQ(base_at(model, sources, "T688", 0.01), "Map 7.tga");
    EXPECT_EQ(base_at(model, sources, "T688", 0.21), "Map 8.tga");
    EXPECT_EQ(base_at(model, sources, "T688", 0.41), "Map 7.tga");
}
