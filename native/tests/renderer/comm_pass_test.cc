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

TEST(CommPass, SetCommSetIdFiltersInstances) {
    scenegraph::World w;
    auto a = w.create_instance(0); w.set_pass(a, scenegraph::Pass::Comm);
    auto b = w.create_instance(0); w.set_pass(b, scenegraph::Pass::Comm);
    w.set_comm_set_id(a, 7);
    w.set_comm_set_id(b, 9);
    int only7 = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance& i){ if (i.comm_set_id == 7) ++only7; });
    EXPECT_EQ(only7, 1);
}
