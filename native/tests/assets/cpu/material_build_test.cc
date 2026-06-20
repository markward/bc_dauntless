#include <gtest/gtest.h>
#include "material_build.h"

namespace {

assets::detail::MaterialInputs basic_inputs() {
    return {};
}

}  // namespace

TEST(MaterialBuild, NiMaterialPropertyCopiesColors) {
    nif::NiMaterialProperty mat;
    mat.ambient   = {0.1f, 0.2f, 0.3f};
    mat.diffuse   = {0.4f, 0.5f, 0.6f};
    mat.specular  = {0.7f, 0.8f, 0.9f};
    mat.emissive  = {1.0f, 1.0f, 1.0f};
    mat.glossiness = 32.0f;
    mat.alpha     = 0.5f;

    auto in = basic_inputs();
    in.material = &mat;
    auto m = assets::detail::build_material(in);
    EXPECT_FLOAT_EQ(m.ambient.x, 0.1f);
    EXPECT_FLOAT_EQ(m.diffuse.y, 0.5f);
    EXPECT_FLOAT_EQ(m.specular.z, 0.9f);
    EXPECT_FLOAT_EQ(m.emissive.x, 1.0f);
    EXPECT_FLOAT_EQ(m.glossiness, 32.0f);
    EXPECT_FLOAT_EQ(m.alpha, 0.5f);
}

TEST(MaterialBuild, NiAlphaPropertyDecodesFlags) {
    nif::NiAlphaProperty alpha;
    alpha.flags = 0x0001u;  // only "blend enabled" bit
    alpha.threshold = 128;

    auto in = basic_inputs();
    in.alpha = &alpha;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.blend_enabled);
    EXPECT_FALSE(m.alpha_test_enabled);
    EXPECT_EQ(m.alpha_test_threshold, 128);
}

TEST(MaterialBuild, NiAlphaPropertyAdditiveBlend) {
    // src=ONE (0x02 in D3DBLEND), dst=ONE — additive
    nif::NiAlphaProperty alpha;
    alpha.flags = (0x02 << 1) | (0x02 << 5) | 0x0001;
    auto in = basic_inputs();
    in.alpha = &alpha;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.blend_enabled);
    EXPECT_EQ(m.blend_src_factor, 0x02u);
    EXPECT_EQ(m.blend_dst_factor, 0x02u);
}

TEST(MaterialBuild, NiZBufferPropertyDecodesFlags) {
    nif::NiZBufferProperty zb;
    zb.flags = 0b11;  // bit 0 test, bit 1 write

    auto in = basic_inputs();
    in.zbuffer = &zb;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.depth_test_enabled);
    EXPECT_TRUE(m.depth_write_enabled);
}

TEST(MaterialBuild, NiMultiTexturePropertyMaps5Slots) {
    nif::NiMultiTextureProperty nmt;
    nmt.elements[0].has_image  = true;
    nmt.elements[0].image_link = 5;
    nmt.elements[3].has_image  = true;  // slot 3 → Glow
    nmt.elements[3].image_link = 9;

    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}, {9, 1}};

    auto in = basic_inputs();
    in.multi_texture = &nmt;
    in.image_to_texture = &image_to_texture;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Base)].texture_index, 0);
    EXPECT_EQ(m.stages[i(S::Glow)].texture_index, 1);
    EXPECT_EQ(m.stages[i(S::Detail)].texture_index, -1);
}

TEST(MaterialBuild, NiVertexColorPropertyCopiesModes) {
    nif::NiVertexColorProperty vc;
    vc.vertex_mode = 2;
    vc.lighting_mode = 1;

    auto in = basic_inputs();
    in.vertex_color = &vc;
    auto m = assets::detail::build_material(in);
    EXPECT_EQ(m.vc_source, 2u);
    EXPECT_EQ(m.vc_lighting_mode, 1u);
}

TEST(MaterialBuild, DefaultsWhenNoPropertiesPresent) {
    auto m = assets::detail::build_material(basic_inputs());
    EXPECT_FLOAT_EQ(m.alpha, 1.0f);
    EXPECT_FALSE(m.blend_enabled);
    EXPECT_TRUE(m.depth_test_enabled);
    EXPECT_TRUE(m.depth_write_enabled);
}

TEST(MaterialBuild, SpecularImageBindsToGlossSlotOnly) {
    // _specular images are standalone masks; unlike _glow, they do NOT
    // dual-bind to Base. Base must remain empty.
    nif::NiTextureProperty tex;
    tex.image_link = 42;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{42, 7}};
    std::unordered_set<std::uint32_t> spec_links = {42};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.specular_image_links = &spec_links;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Gloss)].texture_index, 7);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 0)
        << "_specular images must not dual-bind to Base";
}

TEST(MaterialBuild, NonSpecularImageStillBindsToBase) {
    // Sanity: when specular_image_links is provided but the image_link
    // is NOT in it, behavior is unchanged from before this feature.
    nif::NiTextureProperty tex;
    tex.image_link = 100;

    std::unordered_map<std::uint32_t, int> img_to_tex = {{100, 3}};
    std::unordered_set<std::uint32_t> spec_links = {99};  // a different image

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &img_to_tex;
    in.specular_image_links = &spec_links;

    auto m = assets::detail::build_material(in);
    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[static_cast<std::size_t>(S::Base)].texture_index, 3);
    EXPECT_LT(m.stages[static_cast<std::size_t>(S::Gloss)].texture_index, 0);
}

TEST(MaterialBuild, MultiTexLightmapInGlowStageRoutesToDark) {
    // EBridge ceiling/roof convention: the baked lightmap is authored in
    // multitexture stage 3 (positionally the Glow slot) at uv_set=2, while
    // the diffuse comes from a separate NiTextureProperty in Base. The
    // lightmap must land in StageSlot::Dark (the only lightmap slot
    // bridge.frag samples) with its uv_set preserved — NOT stay stranded
    // in the unsampled Glow slot (which renders the ceiling flat).
    nif::NiTextureProperty tex;          // diffuse -> Base, uv0
    tex.image_link = 5;
    nif::NiMultiTextureProperty nmt;
    nmt.elements[3].has_image  = true;   // stage 3 = Glow positionally
    nmt.elements[3].image_link = 9;
    nmt.elements[3].uv_set     = 2;

    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}, {9, 1}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {5, "ceilingwhite.tga"}, {9, "./../../Data/Sets/EBridge/ceiling lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.multi_texture = &nmt;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Base)].texture_index, 0) << "diffuse must stay in Base";
    EXPECT_EQ(m.stages[i(S::Dark)].texture_index, 1) << "lightmap must route to Dark";
    EXPECT_EQ(m.stages[i(S::Dark)].uv_set, 2u) << "lightmap uv_set must be preserved";
    EXPECT_EQ(m.stages[i(S::Glow)].texture_index, -1) << "lightmap must not stay in Glow";
}

TEST(MaterialBuild, MultiTexLightmapInBaseStageStillRoutesToDark) {
    // EBridge/DBridge floor convention: lightmap authored in multitexture
    // stage 0 at uv_set=1, diffuse in a separate NiTextureProperty. The
    // existing behaviour (lightmap -> Dark, diffuse stays in Base) must
    // survive the generalised filename-driven routing.
    nif::NiTextureProperty tex;
    tex.image_link = 5;
    nif::NiMultiTextureProperty nmt;
    nmt.elements[0].has_image  = true;   // stage 0 = Base positionally
    nmt.elements[0].image_link = 9;
    nmt.elements[0].uv_set     = 1;

    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}, {9, 1}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {5, "carpet.tga"}, {9, "DBridge/floor lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.multi_texture = &nmt;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Base)].texture_index, 0) << "diffuse must stay in Base";
    EXPECT_EQ(m.stages[i(S::Dark)].texture_index, 1) << "lightmap must route to Dark";
    EXPECT_EQ(m.stages[i(S::Dark)].uv_set, 1u);
}

TEST(MaterialBuild, LightmapUvSetClampedToAvailableGeometrySets) {
    // EBridge ceiling shapes reference the lightmap on uv_set=2, but their
    // geometry only carries 2 UV sets (indices 0,1). BC's fixed-function
    // multitexture clamps an out-of-range coordinate set to the highest
    // available one. Replicate that: with 2 geometry UV sets, a Dark-stage
    // lightmap authored at uv_set=2 must clamp to uv_set=1 (so the renderer
    // samples the real set-1 lightmap UVs instead of falling off the end of
    // the vertex data — which would sample the lightmap's black corner).
    nif::NiTextureProperty tex;          // diffuse -> Base, uv0
    tex.image_link = 5;
    nif::NiMultiTextureProperty nmt;
    nmt.elements[3].has_image  = true;   // ceiling convention: stage 3
    nmt.elements[3].image_link = 9;
    nmt.elements[3].uv_set     = 2;      // one past the available sets

    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}, {9, 1}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {5, "ceilingwhite.tga"}, {9, "ceiling lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.multi_texture = &nmt;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    in.geometry_uv_set_count = 2;        // geometry has sets 0 and 1 only
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Dark)].texture_index, 1) << "lightmap routed to Dark";
    EXPECT_EQ(m.stages[i(S::Dark)].uv_set, 1u)
        << "out-of-range uv_set=2 must clamp to the last available set (1)";
}

TEST(MaterialBuild, InRangeUvSetNotClamped) {
    // The floor convention (lightmap on uv_set=1, geometry has 2 sets) is
    // in range and must be left untouched by the clamp.
    nif::NiTextureProperty tex;
    tex.image_link = 5;
    nif::NiMultiTextureProperty nmt;
    nmt.elements[0].has_image  = true;
    nmt.elements[0].image_link = 9;
    nmt.elements[0].uv_set     = 1;

    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}, {9, 1}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {5, "carpet.tga"}, {9, "floor lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.multi_texture = &nmt;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    in.geometry_uv_set_count = 2;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Dark)].uv_set, 1u) << "in-range uv_set must be preserved";
}

TEST(MaterialBuild, LightmapPassFlagSetForLmFilename) {
    nif::NiTextureProperty tex;
    tex.image_link = 7;
    std::unordered_map<std::uint32_t, int> image_to_texture = {{7, 0}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {7, "DBridge/door 04a lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.lightmap_pass);
}

TEST(MaterialBuild, LightmapPassFlagFalseForRegularBase) {
    nif::NiTextureProperty tex;
    tex.image_link = 5;
    std::unordered_map<std::uint32_t, int> image_to_texture = {{5, 0}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {5, "Map 19.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    auto m = assets::detail::build_material(in);
    EXPECT_FALSE(m.lightmap_pass);
}

TEST(MaterialBuild, LightmapPassFlagSetForUnderscoreLmFilename) {
    nif::NiTextureProperty tex;
    tex.image_link = 8;
    std::unordered_map<std::uint32_t, int> image_to_texture = {{8, 0}};
    std::unordered_map<std::uint32_t, std::string> filenames = {
        {8, "modder_panel_lm.tga"}};

    auto in = basic_inputs();
    in.texture = &tex;
    in.image_to_texture = &image_to_texture;
    in.image_filename_for_link = &filenames;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.lightmap_pass);
}
