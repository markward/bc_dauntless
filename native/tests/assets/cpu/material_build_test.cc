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

TEST(MaterialBuild, NiTexturingPropertyMapsStagesViaImageMap) {
    nif::NiTexturingProperty tex;
    tex.apply_mode = 2;
    tex.texture_count = 7;
    tex.base.has = true;
    tex.base.source_link = 42;
    tex.base.uv_set = 0;
    tex.glow.has = true;
    tex.glow.source_link = 17;

    std::unordered_map<std::uint32_t, int> image_to_texture = {
        {42, 3},
        {17, 7},
    };

    auto in = basic_inputs();
    in.texturing = &tex;
    in.image_to_texture = &image_to_texture;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    auto i = [](S s) { return static_cast<std::size_t>(s); };
    EXPECT_EQ(m.stages[i(S::Base)].texture_index, 3);
    EXPECT_EQ(m.stages[i(S::Glow)].texture_index, 7);
    EXPECT_EQ(m.stages[i(S::Dark)].texture_index, -1);
    EXPECT_EQ(m.stages[i(S::Base)].apply_mode, 2u);
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
