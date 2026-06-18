// native/tests/renderer/comm_pass_test.cc
#include <gtest/gtest.h>
#include "scenegraph/world.h"
#include "scenegraph/instance.h"

TEST(CommPass, InstanceCarriesCommSetIdAndPass) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    w.set_pass(id, scenegraph::Pass::Comm);
    int count = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 1);
}
