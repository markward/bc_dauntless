// native/tests/nif/resolver_test.cc — synthetic in-memory tests for the
// resolver helper. The resolver walks each block's reference fields after
// load and converts BlockId integers into BlockHandle pointers.
#include <gtest/gtest.h>

#include <nif/error.h>
#include <nif/file.h>

#include "../../src/nif/src/resolver.h"

TEST(Resolver, EmptyFileResolvesNoOp) {
    nif::File f;
    f.blocks.resize(3);
    EXPECT_NO_THROW(nif::resolve_references(f));
}

TEST(Resolver, NullSentinelResolvesToFalsyHandle) {
    nif::File f;
    f.blocks.resize(2);
    auto h = nif::resolve_handle(f, /*id=*/-1);
    EXPECT_FALSE(static_cast<bool>(h));
}

TEST(Resolver, ValidIndexResolvesToHandle) {
    nif::File f;
    f.blocks.resize(2);
    auto h = nif::resolve_handle(f, /*id=*/1);
    EXPECT_TRUE(static_cast<bool>(h));
    EXPECT_EQ(h.ptr, &f.blocks[1]);
}

TEST(Resolver, OutOfRangeIndexThrows) {
    nif::File f;
    f.blocks.resize(2);
    EXPECT_THROW(nif::resolve_handle(f, /*id=*/99), nif::ParseError);
}

TEST(Resolver, NegativeIndexOtherThanNullSentinelThrows) {
    nif::File f;
    f.blocks.resize(2);
    EXPECT_THROW(nif::resolve_handle(f, /*id=*/-2), nif::ParseError);
}
