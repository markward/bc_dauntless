// native/tests/nif/animation_parse_test.cc — unit tests for legacy
// animation-data body parsers that go through the dispatch table.
#include <gtest/gtest.h>

#include <nif/block.h>
#include <nif/error.h>

#include "../../src/nif/src/dispatch.h"
#include "../../src/nif/src/reader.h"

#include <variant>
#include <vector>

namespace {

nif::Reader make_reader(std::vector<unsigned char>& bytes) {
    return nif::Reader(bytes.data(), bytes.size(), "<test>");
}

void put_u32(std::vector<unsigned char>& out, std::uint32_t v) {
    out.push_back(static_cast<unsigned char>(v & 0xFF));
    out.push_back(static_cast<unsigned char>((v >> 8) & 0xFF));
    out.push_back(static_cast<unsigned char>((v >> 16) & 0xFF));
    out.push_back(static_cast<unsigned char>((v >> 24) & 0xFF));
}

}  // namespace

// rotation_type == 4 (EULERKEY) is a container, not a per-key indicator.
// The SDK asserts num_rotation_keys == 1 in this case. Our parser must
// raise ParseError when the file claims a different count, since that
// would mean either corrupt content or a parser misread.
TEST(NiKeyframeDataParse, EulerRotationTypeRequiresExactlyOneKey) {
    std::vector<unsigned char> bytes;
    put_u32(bytes, 2);  // num_rotation_keys = 2 (illegal for EULER)
    put_u32(bytes, 4);  // rotation_type = EULER
    auto r = make_reader(bytes);
    const auto& parser = nif::Dispatch::instance().get("NiKeyframeData");
    EXPECT_THROW(parser(r), nif::ParseError);
}

TEST(NiKeyframeDataParse, EulerRotationTypeAcceptsOneKey) {
    std::vector<unsigned char> bytes;
    put_u32(bytes, 1);  // num_rotation_keys = 1 (legal for EULER)
    put_u32(bytes, 4);  // rotation_type = EULER
    // unknown_float (consumed by the parser when type == 4)
    put_u32(bytes, 0);
    // Three xyz_rotations float-key arrays, each with zero keys.
    for (int axis = 0; axis < 3; ++axis) {
        put_u32(bytes, 0);  // num_keys = 0
    }
    // Position and scale channels, both empty.
    put_u32(bytes, 0);  // num_translation_keys
    put_u32(bytes, 0);  // num_scale_keys
    auto r = make_reader(bytes);
    const auto& parser = nif::Dispatch::instance().get("NiKeyframeData");
    auto block = parser(r);
    const auto* kd = std::get_if<nif::NiKeyframeData>(&block);
    ASSERT_NE(kd, nullptr);
    EXPECT_EQ(kd->num_rotation_keys, 1u);
    EXPECT_EQ(kd->rotation_type, 4u);
}
