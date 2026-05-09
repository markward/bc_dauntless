// native/tests/nif/ni_tri_shape_test.cc — synthetic unit tests for the
// NiTriShape and NiTriShapeData parsers. End-to-end testing on real BC
// files requires the property-block parsers (Tasks 23-24) so the walker
// can progress past the first NiZBufferProperty.
#include <gtest/gtest.h>

#include <nif/block.h>
#include <nif/error.h>

#include "../../src/nif/src/dispatch.h"
#include "../../src/nif/src/reader.h"

#include <cstdint>
#include <cstring>
#include <variant>
#include <vector>

namespace {

// Pack helpers — append little-endian primitives to a buffer.
void put_u16(std::vector<unsigned char>& v, std::uint16_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
}
void put_u32(std::vector<unsigned char>& v, std::uint32_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
    v.push_back((x >> 16) & 0xFF);
    v.push_back((x >> 24) & 0xFF);
}
void put_f32(std::vector<unsigned char>& v, float x) {
    std::uint32_t u;
    std::memcpy(&u, &x, 4);
    put_u32(v, u);
}
void put_str_u32(std::vector<unsigned char>& v, const std::string& s) {
    put_u32(v, static_cast<std::uint32_t>(s.size()));
    for (char c : s) v.push_back(static_cast<unsigned char>(c));
}

void put_av_object_base_minimal(std::vector<unsigned char>& v,
                                const std::string& name) {
    put_str_u32(v, name);
    put_u32(v, 0);                    // extra_data_link
    put_u32(v, 0);                    // controller_link
    put_u16(v, 0x000c);               // flags
    for (int i = 0; i < 3; ++i) put_f32(v, 0.0f);   // translation
    for (int i = 0; i < 9; ++i) {                   // rotation = identity
        put_f32(v, (i == 0 || i == 4 || i == 8) ? 1.0f : 0.0f);
    }
    put_f32(v, 1.0f);                                // scale
    for (int i = 0; i < 3; ++i) put_f32(v, 0.0f);    // velocity
    put_u32(v, 0);                                   // num_properties
    put_u32(v, 0);                                   // has_bounding_volume = false
}

}  // namespace

TEST(NiTriShape, ParsesAvBaseAndDataLink) {
    std::vector<unsigned char> bytes;
    put_av_object_base_minimal(bytes, "MyShape");
    put_u32(bytes, /*data_link=*/0xDEADBEEF);

    nif::Reader r(bytes.data(), bytes.size(), "<test>");
    nif::Block block = nif::Dispatch::instance().get("NiTriShape")(r);
    auto* shape = std::get_if<nif::NiTriShape>(&block);
    ASSERT_NE(shape, nullptr);
    EXPECT_EQ(shape->av.obj.name, "MyShape");
    EXPECT_EQ(shape->data_link, 0xDEADBEEFu);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}

// NiTriShapeData unit tests removed pending v3.1 layout investigation.
// The schema-derived field order (Num Vertices, then Has Vertices uint32
// bool, then vertices...) doesn't match BC's actual files — hand-decoding
// Galaxy.nif's first NiTriShapeData at offset 0x553 shows non-bool bytes
// immediately after Num Vertices. Once the real layout is figured out,
// fresh tests will be written that match it.
