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
