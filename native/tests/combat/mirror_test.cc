#include <gtest/gtest.h>

#include <cstdint>
#include <stdexcept>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

struct Fixture {
    TransformStore store;
    Mirror m{store};
};

}  // namespace

TEST(Mirror, RegisterSetReadBack) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, 3, 4, 77);
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_f(o, Field::o_radius, 2.5);
    f.m.set_i(o, Field::_dead, 1);
    f.m.set_ref(o, Field::_sensor_subsystem, s);
    f.m.set_fv(o, Field::_seed, {1.0, 2.0, 3.0});
    f.m.set_ids(s, Field::_known_objects, {9, 3, 9, 5});
    EXPECT_EQ(f.m.get_f(o, Field::o_radius), 2.5);
    EXPECT_EQ(f.m.get_i(o, Field::_dead), 1);
    EXPECT_EQ(f.m.get_i(o, Field::xform_index), 3);
    EXPECT_EQ(f.m.get_i(o, Field::obj_id), 77);
    EXPECT_EQ(f.m.get_ref(o, Field::_sensor_subsystem), s);
    EXPECT_EQ(f.m.get_ref(o, Field::_cloaking_subsystem), -1);
    EXPECT_EQ(f.m.get_fv(o, Field::_seed), (std::vector<double>{1, 2, 3}));
    EXPECT_TRUE(f.m.get_fv(o, Field::_fbm).empty());
    EXPECT_EQ(f.m.get_ids(s, Field::_known_objects),
              (std::vector<int64_t>{3, 5, 9}));
    EXPECT_EQ(f.m.find_by_obj_id(77), o);
    f.m.set_fv(o, Field::_seed, {});
    EXPECT_TRUE(f.m.get_fv(o, Field::_seed).empty());
    // A field of another kind is rejected.
    EXPECT_THROW(f.m.set_f(s, Field::o_radius, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.set_i(o, Field::obj_id, 1), std::invalid_argument);
    EXPECT_THROW(f.m.set_f(o, Field::_dead, 1.0), std::invalid_argument);
}

TEST(Mirror, StaleHandleRejected) {
    Fixture f;
    int64_t a = f.m.register_row(Kind::Subsystem);
    f.m.unregister_row(a);
    int64_t b = f.m.register_row(Kind::Subsystem);
    EXPECT_EQ(a & 0xFFFFFFFF, b & 0xFFFFFFFF);  // the index was reused
    EXPECT_NE(a, b);
    EXPECT_THROW(f.m.set_f(a, Field::_condition, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.unregister_row(a), std::invalid_argument);
    EXPECT_NO_THROW(f.m.set_f(b, Field::_condition, 1.0));
}

TEST(Mirror, StaleRefReadsAsNone) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, -1, -1, 1);
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_ref(o, Field::_hull, s);
    f.m.unregister_row(s);
    int64_t s2 = f.m.register_row(Kind::Subsystem);  // reuses s's index
    ASSERT_NE(s, s2);
    EXPECT_EQ(f.m.get_ref(o, Field::_hull), -1);
}

TEST(Mirror, RefUnrepresentableSentinelStored) {
    // R6: a non-None Python referent the mirror cannot name (a test fake, an
    // unregistered set) is -2, distinct from None (-1), and reads back as -2.
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_ref(o, Field::_sensor_subsystem, kRefUnrepresentable);
    EXPECT_EQ(kRefUnrepresentable, -2);
    EXPECT_EQ(f.m.get_ref(o, Field::_sensor_subsystem), kRefUnrepresentable);
    EXPECT_EQ(f.m.object(o)->_sensor_subsystem, kRefUnrepresentable);
    f.m.set_ref(o, Field::_containing_set, kRefUnrepresentable);
    EXPECT_EQ(f.m.get_ref(o, Field::_containing_set), kRefUnrepresentable);
    f.m.set_ref(s, Field::_property, kRefUnrepresentable);
    EXPECT_EQ(f.m.get_ref(s, Field::_property), kRefUnrepresentable);
    f.m.set_ref(o, Field::_sensor_subsystem, -1);
    EXPECT_EQ(f.m.get_ref(o, Field::_sensor_subsystem), -1);
    // Every other non-handle value is still rejected.
    EXPECT_THROW(f.m.set_ref(o, Field::_sensor_subsystem, -3),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_ref(o, Field::_sensor_subsystem, 12345),
                 std::invalid_argument);
}

TEST(Mirror, WrongKindRejected) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t p = f.m.register_row(Kind::Property);
    EXPECT_THROW(f.m.set_f(o, Field::MaxCondition, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.set_f(p, Field::o_radius, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.set_spheres(p, {}), std::invalid_argument);
    EXPECT_THROW(f.m.set_ref(o, Field::_sensor_subsystem, p),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_f(-1, Field::MaxCondition, 1.0),
                 std::invalid_argument);
}

TEST(Mirror, ClearInvalidatesAll) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, -1, -1, 5);
    int64_t pr = f.m.register_row(Kind::Profile);
    f.m.clear();
    EXPECT_THROW(f.m.set_i(o, Field::_dead, 1), std::invalid_argument);
    EXPECT_THROW(f.m.set_profile_rows(pr, {}, 0.0), std::invalid_argument);
    EXPECT_EQ(f.m.find_by_obj_id(5), -1);
    EXPECT_FALSE(f.m.valid(o));
}

TEST(Mirror, EpochRisesOnEverySetterAndClear) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    int64_t st = f.m.register_row(Kind::Set);
    int64_t pr = f.m.register_row(Kind::Profile);
    uint64_t e = f.m.epoch();
    auto rises = [&] {
        EXPECT_GT(f.m.epoch(), e);
        e = f.m.epoch();
    };
    f.m.set_f(s, Field::_condition, 1.0); rises();
    f.m.set_i(s, Field::_destroyed, 1); rises();
    f.m.set_ref(s, Field::_parent_ship, o); rises();
    f.m.set_ids(s, Field::_probe_ids, {1, 2}); rises();
    f.m.set_fv(st, Field::anchor, {1, 2, 3}); rises();
    f.m.set_spheres(o, {{0, 0, 0, 1}}); rises();
    f.m.set_profile_rows(pr, {{1.0, 0.5}}, 0.25); rises();
    f.m.clear(); rises();
}

TEST(Mirror, SetListsDropFreedShips) {
    Fixture f;
    int64_t st = f.m.register_row(Kind::Set);
    int64_t a = f.m.register_row(Kind::Object, -1, -1, 1);
    int64_t b = f.m.register_row(Kind::Object, -1, -1, 2);
    f.m.set_ids(st, Field::ships, {a, b});
    f.m.unregister_row(a);
    EXPECT_EQ(f.m.get_ids(st, Field::ships), (std::vector<int64_t>{b}));
    EXPECT_THROW(f.m.set_ids(st, Field::ships, {st}), std::invalid_argument);
}
