#include "material_build.h"

namespace assets::detail {

namespace {

void apply_material_property(Material& m, const nif::NiMaterialProperty& src) {
    m.ambient    = {src.ambient.r, src.ambient.g, src.ambient.b};
    m.diffuse    = {src.diffuse.r, src.diffuse.g, src.diffuse.b};
    m.specular   = {src.specular.r, src.specular.g, src.specular.b};
    m.emissive   = {src.emissive.r, src.emissive.g, src.emissive.b};
    m.glossiness = src.glossiness;
    m.alpha      = src.alpha;
}

void apply_alpha_property(Material& m, const nif::NiAlphaProperty& src) {
    // Decode the legacy NiAlphaProperty bitfield (D3D7-era):
    //   bit 0     : alpha-blend enable
    //   bits 1-4  : src blend factor (D3DBLEND_*)
    //   bits 5-8  : dst blend factor (D3DBLEND_*)
    //   bit 9     : alpha-test enable
    //   bits 10-12: alpha-test func (D3DCMP_*)
    //   bit 13    : zwrite-when-blended enable
    auto f = src.flags;
    m.blend_enabled        = (f & 0x0001) != 0;
    m.blend_src_factor     = (f >> 1) & 0x0F;
    m.blend_dst_factor     = (f >> 5) & 0x0F;
    m.alpha_test_enabled   = (f & 0x0200) != 0;
    m.alpha_test_func      = (f >> 10) & 0x07;
    m.zwrite_when_blended  = (f & 0x2000) != 0;
    m.alpha_test_threshold = src.threshold;
}

void apply_zbuffer_property(Material& m, const nif::NiZBufferProperty& src) {
    auto f = src.flags;
    m.depth_test_enabled  = (f & 0x01) != 0;
    m.depth_write_enabled = (f & 0x02) != 0;
    m.depth_func          = (f >> 2) & 0x07;
}

void apply_vertex_color_property(Material& m, const nif::NiVertexColorProperty& src) {
    m.vc_source        = src.vertex_mode;
    m.vc_lighting_mode = src.lighting_mode;
}

void apply_stage(
    Material::TextureStage& stage,
    const nif::TexDesc& src,
    std::uint32_t apply_mode,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    if (!src.has) return;
    int tex_idx = -1;
    if (image_to_texture) {
        if (auto it = image_to_texture->find(src.source_link); it != image_to_texture->end()) {
            tex_idx = it->second;
        }
    }
    stage.texture_index = tex_idx;
    stage.clamp_mode    = src.clamp_mode;
    stage.filter_mode   = src.filter_mode;
    stage.uv_set        = src.uv_set;
    stage.apply_mode    = apply_mode;
}

void apply_texture_property(
    Material& m,
    const nif::NiTextureProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture,
    const std::unordered_set<std::uint32_t>* glow_image_links,
    const std::unordered_set<std::uint32_t>* specular_image_links,
    const std::unordered_map<std::uint32_t, int>* sibling_specular_for_image)
{
    // Single-texture v3.x property — usually populates the Base stage.
    //
    // BC's AddLOD suffix conventions reinterpret this binding at runtime:
    //
    //   "_glow"     — image is the hull's diffuse (RGB) AND its self-
    //                 illumination mask (alpha). Bind to BOTH Base and
    //                 Glow so the lit term uses hull color and the glow
    //                 term adds emissive contribution.
    //
    //   "_specular" / "_spec" — image is a standalone per-texel specular
    //                 mask. Bind ONLY to Gloss. Do NOT dual-bind to Base
    //                 (that would replace the hull texture with the mask).
    int tex_idx = -1;
    if (image_to_texture) {
        if (auto it = image_to_texture->find(src.image_link);
            it != image_to_texture->end()) {
            tex_idx = it->second;
        }
    }
    const bool is_specular = specular_image_links &&
        specular_image_links->find(src.image_link) != specular_image_links->end();
    if (is_specular) {
        auto& gloss = m.stages[static_cast<std::size_t>(Material::StageSlot::Gloss)];
        gloss.texture_index = tex_idx;
        gloss.apply_mode    = 2;  // APPLY_MODULATE
        return;
    }
    auto& base = m.stages[static_cast<std::size_t>(Material::StageSlot::Base)];
    base.texture_index = tex_idx;
    base.apply_mode    = 2;
    const bool is_glow = glow_image_links &&
        glow_image_links->find(src.image_link) != glow_image_links->end();
    if (is_glow) {
        auto& glow = m.stages[static_cast<std::size_t>(Material::StageSlot::Glow)];
        glow.texture_index = tex_idx;
        glow.apply_mode    = 2;
    }
    // Phase 1 AddLOD shim: if the asset loader probed for a sibling
    // `_specular` texture next to this image and found one, bind it to
    // the Gloss slot. The hull texture stays in Base / Glow as above;
    // only the spec mask comes from the sibling lookup.
    if (sibling_specular_for_image) {
        auto it = sibling_specular_for_image->find(src.image_link);
        if (it != sibling_specular_for_image->end()) {
            auto& gloss = m.stages[static_cast<std::size_t>(Material::StageSlot::Gloss)];
            gloss.texture_index = it->second;
            gloss.apply_mode    = 2;
        }
    }
}

void apply_texturing_property(
    Material& m,
    const nif::NiTexturingProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    using S = Material::StageSlot;
    auto idx = [](S s) { return static_cast<std::size_t>(s); };
    apply_stage(m.stages[idx(S::Base)],   src.base,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Dark)],   src.dark,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Detail)], src.detail,   src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Gloss)],  src.gloss,    src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Glow)],   src.glow,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Bump)],   src.bump_map, src.apply_mode, image_to_texture);
    apply_stage(m.stages[idx(S::Decal0)], src.decal0,   src.apply_mode, image_to_texture);
    if (src.texture_count >= 8)
        apply_stage(m.stages[idx(S::Decal1)], src.decal1, src.apply_mode, image_to_texture);
    if (src.texture_count >= 9)
        apply_stage(m.stages[idx(S::Decal2)], src.decal2, src.apply_mode, image_to_texture);
}

void apply_multi_texture_property(
    Material& m,
    const nif::NiMultiTextureProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    // Mapping per material_translation.md (subject to revision once we observe
    // real BC NIFs that use NiMultiTextureProperty).
    using S = Material::StageSlot;
    static constexpr S slot_map[5] = {S::Base, S::Dark, S::Detail, S::Glow, S::Gloss};
    for (std::size_t i = 0; i < 5; ++i) {
        const auto& el = src.elements[i];
        if (!el.has_image) continue;
        auto& stage = m.stages[static_cast<std::size_t>(slot_map[i])];
        int tex_idx = -1;
        if (image_to_texture) {
            if (auto it = image_to_texture->find(el.image_link); it != image_to_texture->end()) {
                tex_idx = it->second;
            }
        }
        stage.texture_index = tex_idx;
        stage.clamp_mode    = el.clamp_mode;
        stage.filter_mode   = el.filter_mode;
        stage.uv_set        = el.uv_set;
        stage.apply_mode    = 2;  // APPLY_MODULATE — niflib default
    }
}

}  // namespace

Material build_material(const MaterialInputs& in) {
    Material m;
    if (in.material)      apply_material_property(m, *in.material);
    if (in.alpha)         apply_alpha_property(m, *in.alpha);
    if (in.zbuffer)       apply_zbuffer_property(m, *in.zbuffer);
    if (in.vertex_color)  apply_vertex_color_property(m, *in.vertex_color);
    if (in.texture) apply_texture_property(m, *in.texture,
        in.image_to_texture, in.glow_image_links, in.specular_image_links,
        in.sibling_specular_for_image);
    if (in.texturing)     apply_texturing_property(m, *in.texturing, in.image_to_texture);
    if (in.multi_texture) apply_multi_texture_property(m, *in.multi_texture, in.image_to_texture);
    return m;
}

}  // namespace assets::detail
