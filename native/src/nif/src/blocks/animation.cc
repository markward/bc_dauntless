// native/src/nif/src/blocks/animation.cc
//
// NiKeyframeController parser for NIF v3.1.
//
// Per niflib (BSD): NiKeyframeController inherits NiSingleInterpController
// → NiInterpController → NiTimeController. For v3.1 only NiTimeController
// fields are present, plus the v3.1-conditional unknown_integer, plus the
// NiKeyframeController-specific data_link.
//
// v3.1 NiKeyframeController body (per niflib's auto-gen Read):
//   next_controller_link (uint32)   // NiTimeController
//   flags                (uint16)
//   frequency            (float)
//   phase                (float)
//   start_time           (float)
//   stop_time            (float)
//   // skin instance ref since 3.3.0.13 — absent in v3.1
//   unknown_integer      (uint32)   // version <= 3.1
//   data_link            (uint32)   // version <= 10.1.0.0

#include "../dispatch.h"
#include "../reader.h"

#include <nif/block.h>

namespace nif {

namespace {

NiKeyframeController parse_NiKeyframeController_body(Reader& r) {
    NiKeyframeController k;
    k.next_controller_link = r.read_uint32();
    k.flags = r.read_uint16();
    k.frequency = r.read_float();
    k.phase = r.read_float();
    k.start_time = r.read_float();
    k.stop_time = r.read_float();
    k.unknown_integer = r.read_uint32();
    k.data_link = r.read_uint32();
    return k;
}

// NiTriShapeSkinController v3.1: NiTimeController fields, then per-bone
// vertex counts, bone links, and (bone, vertex) weight tuples.
//
// Per niflib's auto-gen Read:
//   NiTimeController fields
//   numBones (uint32)
//   vertexCounts (uint32 × numBones)
//   bones (uint32 × numBones)  -- block links
//   boneData (per bone, per vertex_count[bone]):
//     vertexWeight (float)
//     vertexIndex (uint16)
//     unknownVector (Vec3)
NiTriShapeSkinController parse_NiTriShapeSkinController_body(Reader& r) {
    NiTriShapeSkinController c;
    c.next_controller_link = r.read_uint32();
    c.flags = r.read_uint16();
    c.frequency = r.read_float();
    c.phase = r.read_float();
    c.start_time = r.read_float();
    c.stop_time = r.read_float();
    c.unknown_integer = r.read_uint32();

    c.num_bones = r.read_uint32();
    c.vertex_counts_per_bone.reserve(c.num_bones);
    for (std::uint32_t i = 0; i < c.num_bones; ++i) {
        c.vertex_counts_per_bone.push_back(r.read_uint32());
    }
    c.bone_links.reserve(c.num_bones);
    for (std::uint32_t i = 0; i < c.num_bones; ++i) {
        c.bone_links.push_back(r.read_uint32());
    }
    c.bone_weights.resize(c.num_bones);
    for (std::uint32_t i = 0; i < c.num_bones; ++i) {
        auto count = c.vertex_counts_per_bone[i];
        c.bone_weights[i].reserve(count);
        for (std::uint32_t j = 0; j < count; ++j) {
            OldSkinWeight w;
            w.weight = r.read_float();
            w.vertex_index = r.read_uint16();
            w.unknown_vector = r.read_vec3();
            c.bone_weights[i].push_back(w);
        }
    }
    return c;
}

// Per niflib's Key<T> NifStream specialization:
//   time (float)
//   data (T) — the per-key value
//   if interpolation == 2 (QUADRATIC): forward_tangent + backward_tangent (T-typed)
//   if interpolation == 3 (TBC): tension + bias + continuity (3 floats)
// Quaternion key specialization skips QUADRATIC tangents (TBC only).
template <typename Reader>
void read_float_key(Reader& r, NiKeyframeData::FloatKeyArray::K& k,
                    std::uint32_t interp) {
    k.time = r.read_float();
    k.value = r.read_float();
    if (interp == 2) {
        k.fwd_tan = r.read_float();
        k.bwd_tan = r.read_float();
    } else if (interp == 3) {
        k.tension = r.read_float();
        k.bias = r.read_float();
        k.continuity = r.read_float();
    }
}

template <typename Reader>
void read_vec3_key(Reader& r, NiKeyframeData::Vec3KeyArray::K& k,
                   std::uint32_t interp) {
    k.time = r.read_float();
    k.value = r.read_vec3();
    if (interp == 2) {
        k.fwd_tan = r.read_vec3();
        k.bwd_tan = r.read_vec3();
    } else if (interp == 3) {
        k.tension = r.read_float();
        k.bias = r.read_float();
        k.continuity = r.read_float();
    }
}

NiKeyframeData parse_NiKeyframeData_body(Reader& r) {
    NiKeyframeData d;
    d.num_rotation_keys = r.read_uint32();
    if (d.num_rotation_keys != 0) {
        d.rotation_type = r.read_uint32();
    }
    if (d.rotation_type != 4) {
        d.quaternion_keys.resize(d.num_rotation_keys);
        for (auto& k : d.quaternion_keys) {
            k.time = r.read_float();
            k.value = r.read_quat();
            // Quaternion keys: QUADRATIC tangents are SKIPPED per niflib's
            // specialization. Only TBC adds extra fields.
            if (d.rotation_type == 3) {
                k.tension = r.read_float();
                k.bias = r.read_float();
                k.continuity = r.read_float();
            }
        }
    }
    // unknown_float is read for v3.1 (version <= 0x0A010000) only when
    // rotation_type == 4.
    if (d.rotation_type == 4) {
        d.unknown_float = r.read_float();
        for (auto& xyz : d.xyz_rotations) {
            xyz.num_keys = r.read_uint32();
            if (xyz.num_keys != 0) {
                xyz.interpolation = r.read_uint32();
            }
            xyz.keys.resize(xyz.num_keys);
            for (auto& k : xyz.keys) {
                read_float_key(r, k, xyz.interpolation);
            }
        }
    }
    d.translations.num_keys = r.read_uint32();
    if (d.translations.num_keys != 0) {
        d.translations.interpolation = r.read_uint32();
    }
    d.translations.keys.resize(d.translations.num_keys);
    for (auto& k : d.translations.keys) {
        read_vec3_key(r, k, d.translations.interpolation);
    }
    d.scales.num_keys = r.read_uint32();
    if (d.scales.num_keys != 0) {
        d.scales.interpolation = r.read_uint32();
    }
    d.scales.keys.resize(d.scales.num_keys);
    for (auto& k : d.scales.keys) {
        read_float_key(r, k, d.scales.interpolation);
    }
    return d;
}

}  // namespace

NIF_REGISTER_BLOCK(NiKeyframeController, [](Reader& r) -> Block {
    return parse_NiKeyframeController_body(r);
});

NIF_REGISTER_BLOCK(NiTriShapeSkinController, [](Reader& r) -> Block {
    return parse_NiTriShapeSkinController_body(r);
});

NIF_REGISTER_BLOCK(NiKeyframeData, [](Reader& r) -> Block {
    return parse_NiKeyframeData_body(r);
});

// NiVisController v3.x: NiTimeController fields + data_link (NiVisData ref).
NIF_REGISTER_BLOCK(NiVisController, [](Reader& r) -> Block {
    NiVisController c;
    c.next_controller_link = r.read_uint32();
    c.flags = r.read_uint16();
    c.frequency = r.read_float();
    c.phase = r.read_float();
    c.start_time = r.read_float();
    c.stop_time = r.read_float();
    c.unknown_integer = r.read_uint32();
    c.data_link = r.read_uint32();
    return c;
});

// NiLookAtController v3.x: NiTimeController fields + look_at_node_link.
NIF_REGISTER_BLOCK(NiLookAtController, [](Reader& r) -> Block {
    NiLookAtController c;
    c.next_controller_link = r.read_uint32();
    c.flags = r.read_uint16();
    c.frequency = r.read_float();
    c.phase = r.read_float();
    c.start_time = r.read_float();
    c.stop_time = r.read_float();
    c.unknown_integer = r.read_uint32();
    c.look_at_node_link = r.read_uint32();
    return c;
});

// NiRollController v3.x: NiTimeController fields + data_link.
NIF_REGISTER_BLOCK(NiRollController, [](Reader& r) -> Block {
    NiRollController c;
    c.next_controller_link = r.read_uint32();
    c.flags = r.read_uint16();
    c.frequency = r.read_float();
    c.phase = r.read_float();
    c.start_time = r.read_float();
    c.stop_time = r.read_float();
    c.unknown_integer = r.read_uint32();
    c.data_link = r.read_uint32();
    return c;
});

// NiFloatData v3.x: num_keys (uint32), interpolation (uint32 if num_keys>0),
// then num_keys × float-key (time + value, with QUADRATIC/TBC tail).
NIF_REGISTER_BLOCK(NiFloatData, [](Reader& r) -> Block {
    NiFloatData d;
    d.num_keys = r.read_uint32();
    if (d.num_keys != 0) {
        d.interpolation = r.read_uint32();
    }
    d.keys.reserve(d.num_keys);
    for (std::uint32_t i = 0; i < d.num_keys; ++i) {
        NiFloatData::K k;
        k.time = r.read_float();
        k.value = r.read_float();
        if (d.interpolation == 2) {  // QUADRATIC
            k.fwd_tan = r.read_float();
            k.bwd_tan = r.read_float();
        } else if (d.interpolation == 3) {  // TBC
            k.tension = r.read_float();
            k.bias = r.read_float();
            k.continuity = r.read_float();
        }
        d.keys.push_back(k);
    }
    return d;
});

// NiVisData v3.x: num_keys (uint32) + linear visibility keys (time float +
// visible byte each).
NIF_REGISTER_BLOCK(NiVisData, [](Reader& r) -> Block {
    NiVisData d;
    d.num_keys = r.read_uint32();
    d.keys.reserve(d.num_keys);
    for (std::uint32_t i = 0; i < d.num_keys; ++i) {
        VisKey k;
        k.time = r.read_float();
        k.visible = r.read_uint8();
        d.keys.push_back(k);
    }
    return d;
});

// NiFlipController v3.1: NiTimeController fields + textureSlot + delta +
// numSources + images (uint32 × numSources). The unknownInt2 + sources
// array fields are version >= 4.0.0.0 only — absent in v3.1.
NIF_REGISTER_BLOCK(NiFlipController, [](Reader& r) -> Block {
    NiFlipController c;
    c.next_controller_link = r.read_uint32();
    c.flags = r.read_uint16();
    c.frequency = r.read_float();
    c.phase = r.read_float();
    c.start_time = r.read_float();
    c.stop_time = r.read_float();
    c.unknown_integer = r.read_uint32();
    c.texture_slot = r.read_uint32();
    c.delta = r.read_float();
    c.num_sources = r.read_uint32();
    c.image_links.reserve(c.num_sources);
    for (std::uint32_t i = 0; i < c.num_sources; ++i) {
        c.image_links.push_back(r.read_uint32());
    }
    return c;
});

}  // namespace nif
