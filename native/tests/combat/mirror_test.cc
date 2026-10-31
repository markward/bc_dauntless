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

TEST(Mirror, SetListsKeepUnrepresentableEntries) {
    // A ship Python cannot name (its row was dropped) keeps its place in the
    // ordered list as kRefUnrepresentable; the list never shortens.
    Fixture f;
    int64_t st = f.m.register_row(Kind::Set);
    int64_t b = f.m.register_row(Kind::Object, -1, -1, 2);
    f.m.set_ids(st, Field::ships, {kRefUnrepresentable, b});
    EXPECT_EQ(f.m.get_ids(st, Field::ships),
              (std::vector<int64_t>{kRefUnrepresentable, b}));
    f.m.set_ids(st, Field::nebulae, {kRefUnrepresentable});
    EXPECT_EQ(f.m.get_ids(st, Field::nebulae),
              (std::vector<int64_t>{kRefUnrepresentable}));
    EXPECT_THROW(f.m.set_ids(st, Field::ships, {-1}), std::invalid_argument);
    EXPECT_THROW(f.m.set_ids(st, Field::ships, {-3}), std::invalid_argument);
}

TEST(Mirror, SetFrameResolved) {
    Fixture f;
    int64_t st = f.m.register_row(Kind::Set);
    int64_t pr = f.m.register_row(Kind::Profile);
    uint64_t e = f.m.epoch();
    f.m.set_frame(st, pr, {1.0, 122000.0, 0.0}, {0.0, 0.0, 0.5});
    EXPECT_GT(f.m.epoch(), e);
    EXPECT_EQ(f.m.get_i(st, Field::mapped), 1);
    EXPECT_EQ(f.m.get_ref(st, Field::profile), pr);
    EXPECT_EQ(f.m.get_fv(st, Field::anchor),
              (std::vector<double>{1.0, 122000.0, 0.0}));
    EXPECT_EQ(f.m.get_fv(st, Field::star), (std::vector<double>{0.0, 0.0, 0.5}));

    f.m.set_frame(st, -1, {0, 0, 0}, {0, 0, 0});        // unmapped
    EXPECT_EQ(f.m.get_i(st, Field::mapped), 0);
    EXPECT_EQ(f.m.get_ref(st, Field::profile), -1);
    EXPECT_EQ(f.m.get_fv(st, Field::anchor), (std::vector<double>{0, 0, 0}));

    f.m.set_frame(st, kRefUnrepresentable, {0, 0, 0}, {0, 0, 0});
    EXPECT_EQ(f.m.get_i(st, Field::mapped), 0);
    EXPECT_EQ(f.m.get_ref(st, Field::profile), kRefUnrepresentable);

    EXPECT_THROW(f.m.set_frame(st, st, {0, 0, 0}, {0, 0, 0}),
                 std::invalid_argument);                  // not a Profile
    EXPECT_THROW(f.m.set_frame(pr, -1, {0, 0, 0}, {0, 0, 0}),
                 std::invalid_argument);                  // not a Set
    f.m.unregister_row(pr);
    EXPECT_THROW(f.m.set_frame(st, pr, {0, 0, 0}, {0, 0, 0}),
                 std::invalid_argument);                  // stale profile
}

TEST(Mirror, GlobalsByName) {
    Fixture f;
    EXPECT_EQ(global_by_name("sensorless_range_gu"),
              Global::sensorless_range_gu);
    EXPECT_STREQ(global_name(Global::CLOAK_DETECTION_BASE_GU),
                 "CLOAK_DETECTION_BASE_GU");
    EXPECT_TRUE(global_is_int(Global::dev_mode));
    EXPECT_TRUE(global_is_int(Global::occ_enabled));
    EXPECT_TRUE(global_is_int(Global::enhanced_sensor_contest));
    EXPECT_FALSE(global_is_int(Global::conceal_cap));
    EXPECT_THROW(global_by_name("nope"), std::invalid_argument);
    for (int i = 0; i < static_cast<int>(Global::kCount); ++i) {
        auto g = static_cast<Global>(i);
        EXPECT_EQ(global_by_name(global_name(g)), g);
    }

    uint64_t e = f.m.epoch();
    f.m.set_global_f(Global::sensorless_range_gu, 2250.0);
    EXPECT_GT(f.m.epoch(), e);
    f.m.set_global_i(Global::dev_mode, 1);
    EXPECT_EQ(f.m.get_global_f(Global::sensorless_range_gu), 2250.0);
    EXPECT_EQ(f.m.globals().sensorless_range_gu, 2250.0);
    EXPECT_EQ(f.m.get_global_i(Global::dev_mode), 1);
    EXPECT_EQ(f.m.globals().dev_mode, 1);
    EXPECT_THROW(f.m.set_global_f(Global::dev_mode, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.set_global_i(Global::HYSTERESIS, 1), std::invalid_argument);

    f.m.clear();                                          // tests only
    EXPECT_EQ(f.m.globals().sensorless_range_gu, 0.0);
    EXPECT_EQ(f.m.globals().dev_mode, 0);
}

// ── Phase 1b: weapon systems, banks, tubes, ammo, chains ────────────────────

TEST(MirrorWeapons, AmmoRowRegistersAndFreesLikeAnyKind) {
    Fixture f;
    int64_t a = f.m.register_row(Kind::Ammo);
    EXPECT_EQ(Mirror::kind_of(a), Kind::Ammo);
    f.m.set_i(a, Field::_unlimited, 1);
    f.m.set_i(a, Field::_available, 7);
    EXPECT_EQ(f.m.get_i(a, Field::_unlimited), 1);
    EXPECT_EQ(f.m.get_i(a, Field::_available), 7);
    EXPECT_EQ(f.m.ammo(a)->_available, 7);
    // A field of another kind is rejected on an Ammo row, and the reverse.
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_THROW(f.m.set_i(a, Field::_fire_held, 1), std::invalid_argument);
    EXPECT_THROW(f.m.set_i(s, Field::_available, 1), std::invalid_argument);
    f.m.unregister_row(a);
    EXPECT_EQ(f.m.ammo(a), nullptr);
    EXPECT_THROW(f.m.set_i(a, Field::_available, 1), std::invalid_argument);
    int64_t b = f.m.register_row(Kind::Ammo);          // reuses the index
    EXPECT_NE(a, b);
    EXPECT_EQ(f.m.get_i(b, Field::_available), 0);     // a fresh row
}

TEST(MirrorWeapons, OrderedListsKeepOrderAndCheckKind) {
    Fixture f;
    int64_t sys = f.m.register_row(Kind::Subsystem);
    int64_t b0 = f.m.register_row(Kind::Subsystem);
    int64_t b1 = f.m.register_row(Kind::Subsystem);
    int64_t t0 = f.m.register_row(Kind::Object, -1, -1, 1);
    int64_t t1 = f.m.register_row(Kind::Object, -1, -1, 2);
    // Order is the list's own order (not sorted, duplicates untouched).
    f.m.set_ids(sys, Field::_children, {b1, b0});
    EXPECT_EQ(f.m.get_ids(sys, Field::_children),
              (std::vector<int64_t>{b1, b0}));
    f.m.set_ids(sys, Field::_target_list, {t1, kRefUnrepresentable, t0});
    EXPECT_EQ(f.m.get_ids(sys, Field::_target_list),
              (std::vector<int64_t>{t1, kRefUnrepresentable, t0}));
    EXPECT_THROW(f.m.set_ids(sys, Field::_children, {t0}),
                 std::invalid_argument);               // an Object, not a Subsystem
    EXPECT_THROW(f.m.set_ids(sys, Field::_target_list, {b0}),
                 std::invalid_argument);
    // A freed row's entry drops out; -2 keeps its place.
    f.m.unregister_row(t1);
    EXPECT_EQ(f.m.get_ids(sys, Field::_target_list),
              (std::vector<int64_t>{kRefUnrepresentable, t0}));
}

TEST(MirrorWeapons, AmmoBySlotIsSlotHandlePairs) {
    Fixture f;
    int64_t sys = f.m.register_row(Kind::Subsystem);
    int64_t a0 = f.m.register_row(Kind::Ammo);
    int64_t a1 = f.m.register_row(Kind::Ammo);
    f.m.set_ids(sys, Field::_ammo_by_slot, {0, a0, 3, a1, 5, kRefUnrepresentable});
    EXPECT_EQ(f.m.get_ids(sys, Field::_ammo_by_slot),
              (std::vector<int64_t>{0, a0, 3, a1, 5, kRefUnrepresentable}));
    EXPECT_THROW(f.m.set_ids(sys, Field::_ammo_by_slot, {0, a0, 1}),
                 std::invalid_argument);               // odd length
    EXPECT_THROW(f.m.set_ids(sys, Field::_ammo_by_slot, {0, sys}),
                 std::invalid_argument);               // not an Ammo handle
    EXPECT_NO_THROW(f.m.set_ids(sys, Field::_ammo_by_slot, {}));
    // A slot holding None is -1.
    f.m.set_ids(sys, Field::_ammo_by_slot, {0, -1, 2, a0});
    EXPECT_EQ(f.m.get_ids(sys, Field::_ammo_by_slot),
              (std::vector<int64_t>{0, -1, 2, a0}));
}

TEST(MirrorWeapons, OffsetsAreNullableButMountVectorsAreNot) {
    Fixture f;
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_TRUE(f.m.get_fv(s, Field::_held_offset).empty());
    EXPECT_TRUE(f.m.get_fv(s, Field::_target_offset).empty());
    f.m.set_fv(s, Field::_held_offset, {0.25, -0.5, 1.5});
    EXPECT_EQ(f.m.get_fv(s, Field::_held_offset),
              (std::vector<double>{0.25, -0.5, 1.5}));
    EXPECT_TRUE(f.m.get_fv(s, Field::_target_offset).empty());  // independent
    f.m.set_fv(s, Field::_held_offset, {});
    EXPECT_TRUE(f.m.get_fv(s, Field::_held_offset).empty());
    // A mount vector (and the ship velocity) is never "unset".
    EXPECT_THROW(f.m.set_fv(s, Field::_position, {}), std::invalid_argument);
    f.m.set_fv(s, Field::_position, {1, 2, 3});
    EXPECT_EQ(f.m.get_fv(s, Field::_position), (std::vector<double>{1, 2, 3}));
    int64_t o = f.m.register_row(Kind::Object);
    EXPECT_THROW(f.m.set_fv(o, Field::_velocity, {1, 2}), std::invalid_argument);
    f.m.set_fv(o, Field::_velocity, {1.5, -2.25, 0.125});
    EXPECT_EQ(f.m.get_fv(o, Field::_velocity),
              (std::vector<double>{1.5, -2.25, 0.125}));
}

TEST(MirrorWeapons, RefsCheckTheirTargetKind) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t other = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_ref(s, Field::_target, other);
    f.m.set_ref(s, Field::_held_target, kRefUnrepresentable);
    EXPECT_EQ(f.m.get_ref(s, Field::_target), other);
    EXPECT_EQ(f.m.get_ref(s, Field::_held_target), kRefUnrepresentable);
    EXPECT_THROW(f.m.set_ref(s, Field::_target, s), std::invalid_argument);
    f.m.set_ref(o, Field::_phaser_system, s);
    EXPECT_EQ(f.m.get_ref(o, Field::_phaser_system), s);
    EXPECT_THROW(f.m.set_ref(o, Field::_torpedo_system, other),
                 std::invalid_argument);               // an Object, not a Subsystem
}

TEST(MirrorWeapons, FiringChainsAreAnOrderedListOfGroupLists) {
    Fixture f;
    int64_t p = f.m.register_row(Kind::Property);
    EXPECT_TRUE(f.m.get_id_lists(p, Field::_firing_chains).empty());
    f.m.set_id_lists(p, Field::_firing_chains, {{0, 1}, {0, 1, 2, 3}, {}});
    EXPECT_EQ(f.m.get_id_lists(p, Field::_firing_chains),
              (std::vector<std::vector<int64_t>>{{0, 1}, {0, 1, 2, 3}, {}}));
    EXPECT_EQ(f.m.property(p)->_firing_chains.size(), 3u);
    f.m.set_i(p, Field::_groups, 5);
    EXPECT_EQ(f.m.get_i(p, Field::_groups), 5);
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_THROW(f.m.set_id_lists(s, Field::_firing_chains, {}),
                 std::invalid_argument);               // not a Property
    EXPECT_THROW(f.m.set_ids(p, Field::_children, {}), std::invalid_argument);
}

TEST(MirrorWeapons, ClearFreesAmmoToo) {
    Fixture f;
    int64_t a = f.m.register_row(Kind::Ammo);
    f.m.clear();
    EXPECT_EQ(f.m.ammo(a), nullptr);
    EXPECT_FALSE(f.m.valid(a));
}
