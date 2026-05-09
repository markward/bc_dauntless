// native/src/nif/src/blocks/scene.cc
//
// NiCamera, NiPointLight, NiSpotLight parsers for NIF v3.x.
//
// Per niflib (BSD), v3.x layouts:
//
// NiDynamicEffect (base for lights) for version <= 4.0.0.2:
//   NiAVObject body
//   num_affected_node_list_pointers (uint32)
//   affected_node_list_pointers (uint32 × num)
//
// NiLight = NiDynamicEffect + dimmer (float) + ambient/diffuse/specular Color3.
//
// NiPointLight = NiLight + 3 attenuation floats.
// NiSpotLight  = NiPointLight + cutoff_angle + exponent.
//
// NiCamera (v3.x):
//   NiAVObject body
//   6 frustum floats, 4 viewport floats, lod_adjust
//   scene_link (uint32), unknown_int (uint32)
//   unknown_int_3 (uint32) — only when version <= 3.1

#include "../dispatch.h"
#include "../reader.h"
#include "av_object_base.h"

#include <nif/block.h>

namespace nif {

namespace {

DynamicEffectBase parse_dynamic_effect_base(Reader& r, const char* block_type) {
    DynamicEffectBase d;
    d.av = parse_av_object_base(r, block_type);
    // For version <= 0x04000002 niflib reads numAffectedNodeListPointers
    // followed by the array. For v3.x this branch always applies.
    d.num_affected_node_pointers = r.read_uint32();
    d.affected_node_pointers.reserve(d.num_affected_node_pointers);
    for (std::uint32_t i = 0; i < d.num_affected_node_pointers; ++i) {
        d.affected_node_pointers.push_back(r.read_uint32());
    }
    return d;
}

LightCommon parse_light_common(Reader& r, const char* block_type) {
    LightCommon l;
    l.dyn = parse_dynamic_effect_base(r, block_type);
    l.dimmer = r.read_float();
    l.ambient_color = r.read_color3();
    l.diffuse_color = r.read_color3();
    l.specular_color = r.read_color3();
    return l;
}

}  // namespace

NIF_REGISTER_BLOCK(NiCamera, [](Reader& r) -> Block {
    NiCamera c;
    c.av = parse_av_object_base(r, "NiCamera");
    // NiCamera's "unknown_short" is since 10.1.0.0; absent in v3.x.
    c.frustum_left = r.read_float();
    c.frustum_right = r.read_float();
    c.frustum_top = r.read_float();
    c.frustum_bottom = r.read_float();
    c.frustum_near = r.read_float();
    c.frustum_far = r.read_float();
    // useOrthographicProjection is since 10.1.0.0; absent in v3.x.
    c.viewport_left = r.read_float();
    c.viewport_right = r.read_float();
    c.viewport_top = r.read_float();
    c.viewport_bottom = r.read_float();
    c.lod_adjust = r.read_float();
    c.scene_link = r.read_uint32();
    c.unknown_int = r.read_uint32();
    // unknown_int_2 is since 4.2.1.0 — absent in v3.x.
    if (r.version().value <= 0x03010000) {
        c.unknown_int_3 = r.read_uint32();
    }
    return c;
});

NIF_REGISTER_BLOCK(NiPointLight, [](Reader& r) -> Block {
    NiPointLight p;
    p.light = parse_light_common(r, "NiPointLight");
    p.constant_attenuation = r.read_float();
    p.linear_attenuation = r.read_float();
    p.quadratic_attenuation = r.read_float();
    return p;
});

NIF_REGISTER_BLOCK(NiSpotLight, [](Reader& r) -> Block {
    NiSpotLight s;
    s.light = parse_light_common(r, "NiSpotLight");
    s.constant_attenuation = r.read_float();
    s.linear_attenuation = r.read_float();
    s.quadratic_attenuation = r.read_float();
    s.cutoff_angle = r.read_float();
    // unknownFloat (between cutoff and exponent) is since 20.2.0.7; absent
    // in v3.x.
    s.exponent = r.read_float();
    return s;
});

NIF_REGISTER_BLOCK(NiAmbientLight, [](Reader& r) -> Block {
    NiAmbientLight a;
    a.light = parse_light_common(r, "NiAmbientLight");
    return a;
});

NIF_REGISTER_BLOCK(NiDirectionalLight, [](Reader& r) -> Block {
    NiDirectionalLight d;
    d.light = parse_light_common(r, "NiDirectionalLight");
    return d;
});

}  // namespace nif
