#include "material_build.h"

#include <cctype>
#include <string_view>

namespace assets::detail {

namespace {

/// True when `fname`'s basename (case-insensitive) ends in either
/// " lm.tga" (space-separated, as in stock BC content like
/// "door 04a lm.tga") or "_lm.tga" (underscore-separated, as a future
/// authoring-tool convention). Matches BC's baked-lightmap filename
/// rule for bridge geometry.
bool filename_is_lightmap(std::string_view fname) {
    auto lower_ends_with = [](std::string_view s, std::string_view suffix) {
        if (s.size() < suffix.size()) return false;
        for (std::size_t i = 0; i < suffix.size(); ++i) {
            char c = s[s.size() - suffix.size() + i];
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            if (c != suffix[i]) return false;
        }
        return true;
    };
    return lower_ends_with(fname, " lm.tga") ||
           lower_ends_with(fname, "_lm.tga");
}

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

void apply_multi_texture_property(
    Material& m,
    const nif::NiMultiTextureProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    // Stage→slot mapping per material_translation.md, with a UV-set-aware
    // override: BC's bridge authoring puts the floor lightmap in stage 0
    // of NiMultiTextureProperty but with `uv_set=1` to sample the
    // lightmap atlas instead of the underlying carpet tile coords. These
    // shapes ALSO inherit a separate NiTextureProperty (the carpet
    // diffuse) on UV set 0, which apply_texture_property writes into
    // StageSlot::Base FIRST. If we naively routed multi-tex stage 0 to
    // Base, the lightmap would clobber the carpet diffuse and the
    // renderer would lose the actual surface texture.
    //
    // Workaround: when a stage 0 entry has uv_set != 0 AND Base is
    // already populated, route it to StageSlot::Dark (the conventional
    // NetImmerse lightmap slot). The diffuse stays in Base; the
    // lightmap goes to Dark; both can be sampled at draw time.
    using S = Material::StageSlot;
    static constexpr S slot_map[5] = {S::Base, S::Dark, S::Detail, S::Glow, S::Gloss};
    for (std::size_t i = 0; i < 5; ++i) {
        const auto& el = src.elements[i];
        if (!el.has_image) continue;

        S target = slot_map[i];
        if (i == 0 && el.uv_set != 0) {
            auto& base = m.stages[static_cast<std::size_t>(S::Base)];
            if (base.texture_index >= 0) {
                target = S::Dark;
            }
        }

        auto& stage = m.stages[static_cast<std::size_t>(target)];
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
    if (in.multi_texture) apply_multi_texture_property(m, *in.multi_texture, in.image_to_texture);

    // Apply BC's lightmap-filename convention. Looks up the source
    // filename for whichever NiImage actually landed in the resolved
    // Base stage of the final Material (i.e. after both
    // NiTextureProperty and NiMultiTextureProperty have run — DBridge
    // shapes inherit BOTH from different ancestor NiNodes, with the
    // multi-texture's lightmap correctly overwriting the texture
    // property's base). Sets m.lightmap_pass if that filename matches
    // "* lm.tga" / "*_lm.tga".
    if (in.image_filename_for_link && in.image_to_texture) {
        const int base_tex_idx = m.stages[
            static_cast<std::size_t>(Material::StageSlot::Base)].texture_index;
        if (base_tex_idx >= 0) {
            // Reverse-lookup: which NiImage link_id maps to this
            // texture_index? Image count is typically tens; linear scan
            // is fine.
            for (const auto& [link_id, tex_idx] : *in.image_to_texture) {
                if (tex_idx != base_tex_idx) continue;
                auto fn_it = in.image_filename_for_link->find(link_id);
                if (fn_it == in.image_filename_for_link->end()) continue;
                if (filename_is_lightmap(fn_it->second)) {
                    m.lightmap_pass = true;
                }
                break;
            }
        }
    }

    return m;
}

}  // namespace assets::detail
