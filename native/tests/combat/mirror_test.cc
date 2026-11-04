#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <cstring>
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

// ids.unregister(obj_id) / ids.register(obj) (final review M5): an Object
// row whose Python id stops resolving is not found by its obj_id either,
// while the row itself (pending a deferred free) stays valid.
TEST(Mirror, AnObjectRowCanStopAndResumeBeingFoundByItsObjId) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, -1, -1, 42);
    const uint64_t e0 = f.m.epoch();
    f.m.set_obj_id_findable(o, false);
    EXPECT_EQ(f.m.find_by_obj_id(42), -1);
    EXPECT_TRUE(f.m.valid(o));
    EXPECT_GT(f.m.epoch(), e0);
    f.m.set_obj_id_findable(o, false);              // idempotent
    EXPECT_EQ(f.m.find_by_obj_id(42), -1);
    f.m.set_obj_id_findable(o, true);
    EXPECT_EQ(f.m.find_by_obj_id(42), o);
    // Unfindable, then freed: nothing to erase, nothing found.
    f.m.set_obj_id_findable(o, false);
    f.m.unregister_row(o);
    EXPECT_EQ(f.m.find_by_obj_id(42), -1);
    EXPECT_THROW(f.m.set_obj_id_findable(o, true), std::invalid_argument);
    // Only Object rows have an obj_id.
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_THROW(f.m.set_obj_id_findable(s, false), std::invalid_argument);
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

// ── K2 (phase 2): what the beam kernel reads ──────────────────────────────

TEST(MirrorK2, ShipRefsAndOffsets) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t other = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_ref(o, Field::_target_subsystem, s);
    f.m.set_ref(o, Field::_shield_subsystem, kRefUnrepresentable);
    EXPECT_EQ(f.m.get_ref(o, Field::_target_subsystem), s);
    EXPECT_EQ(f.m.get_ref(o, Field::_shield_subsystem), kRefUnrepresentable);
    EXPECT_THROW(f.m.set_ref(o, Field::_target_subsystem, other),
                 std::invalid_argument);             // an Object, not a Subsystem
    EXPECT_TRUE(f.m.get_fv(o, Field::_manual_target_offset).empty());
    f.m.set_fv(o, Field::_manual_target_offset, {1.5, -2.0, 0.25});
    EXPECT_EQ(f.m.get_fv(o, Field::_manual_target_offset),
              (std::vector<double>{1.5, -2.0, 0.25}));
    f.m.set_fv(o, Field::_manual_target_offset, {});
    EXPECT_TRUE(f.m.get_fv(o, Field::_manual_target_offset).empty());
    f.m.set_i(o, Field::_use_target_offset, 1);
    f.m.set_i(o, Field::is_ship_class, 1);
    f.m.set_i(o, Field::has_real_get_shields, 1);
    EXPECT_EQ(f.m.object(o)->_use_target_offset, 1);
    EXPECT_EQ(f.m.object(o)->is_ship_class, 1);
}

TEST(MirrorK2, HullBoxIsTwoVectorsAndAFlag) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    EXPECT_EQ(f.m.get_i(o, Field::hull_box_set), 0);
    EXPECT_THROW(f.m.set_fv(o, Field::_shield_hull_box_half, {}),
                 std::invalid_argument);             // never "unset" itself
    f.m.set_fv(o, Field::_shield_hull_box_center, {1, 2, 3});
    f.m.set_fv(o, Field::_shield_hull_box_half, {4, 5, 6});
    f.m.set_i(o, Field::hull_box_set, 1);
    const ObjectRow* r = f.m.object(o);
    EXPECT_EQ(r->_shield_hull_box_center, (Vec3{1, 2, 3}));
    EXPECT_EQ(r->_shield_hull_box_half, (Vec3{4, 5, 6}));
    EXPECT_EQ(r->hull_box_set, 1);
}

TEST(MirrorK2, BankAndShieldFields) {
    Fixture f;
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_f(s, Field::_length, 3.5);
    f.m.set_f(s, Field::_beam_on_countdown, 0.66);
    f.m.set_f(s, Field::_dwell, 0.125);
    f.m.set_i(s, Field::has_shields, 1);
    const SubsystemRow* r = f.m.subsystem(s);
    EXPECT_EQ(r->_length, 3.5);
    EXPECT_EQ(r->_beam_on_countdown, 0.66);
    EXPECT_EQ(r->_dwell, 0.125);
    EXPECT_EQ(r->has_shields, 1);
    int64_t o = f.m.register_row(Kind::Object);
    EXPECT_THROW(f.m.set_f(o, Field::_dwell, 1.0), std::invalid_argument);
}

TEST(MirrorK2, Globals) {
    Fixture f;
    f.m.set_global_f(Global::BEAM_DWELL_FLUSH_S, 0.5);
    f.m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, 1.7320508075688772);
    EXPECT_EQ(f.m.globals().BEAM_DWELL_FLUSH_S, 0.5);
    EXPECT_EQ(f.m.globals().SHIELD_ELLIPSOID_AXIS_SCALE, 1.7320508075688772);
    EXPECT_EQ(global_by_name("BEAM_DWELL_FLUSH_S"), Global::BEAM_DWELL_FLUSH_S);
    EXPECT_FALSE(global_is_int(Global::SHIELD_ELLIPSOID_AXIS_SCALE));
}

// ── K3/K4: py_id and the torpedo table ──────────────────────────────────────

TEST(TorpedoTable, AddDropKeepsOrder) {
    TorpedoTable t;
    int64_t a = t.add(1, 0), b = t.add(2, 0), c = t.add(3, 0);
    EXPECT_EQ(t.handles(), (std::vector<int64_t>{a, b, c}));
    EXPECT_TRUE(t.drop(b));
    EXPECT_FALSE(t.drop(b));               // already gone
    EXPECT_EQ(t.handles(), (std::vector<int64_t>{a, c}));
    EXPECT_EQ(t.size(), 2u);
    int64_t d = t.add(4, 0);
    EXPECT_NE(d, b);                       // handles are never reused
    EXPECT_EQ(t.handles(), (std::vector<int64_t>{a, c, d}));
    EXPECT_EQ(t.find(b), nullptr);
    EXPECT_THROW(t.checked(b), std::invalid_argument);
    ASSERT_NE(t.find(c), nullptr);
    EXPECT_EQ(t.find(c)->xform_index, 3);
    // Rows in order, tombstones included and flagged.
    std::vector<int64_t> alive;
    for (const TorpedoRow& r : t.rows())
        if (r.alive) alive.push_back(r.handle);
    EXPECT_EQ(alive, t.handles());
    t.clear();
    EXPECT_EQ(t.size(), 0u);
    EXPECT_TRUE(t.handles().empty());
    EXPECT_EQ(t.find(a), nullptr);
}

TEST(TorpedoTable, TombstonesCompact) {
    TorpedoTable t;
    std::vector<int64_t> hs;
    for (int i = 0; i < 200; ++i) hs.push_back(t.add(i, 0));
    t.find(hs[199])->age = 7.5;
    // Drop all but every tenth: the tombstones outnumber the living, so the
    // table compacts, and order and contents survive it.
    std::vector<int64_t> kept;
    for (int i = 0; i < 200; ++i) {
        if (i % 10 == 0 || i == 199) kept.push_back(hs[i]);
        else EXPECT_TRUE(t.drop(hs[i]));
    }
    EXPECT_LT(t.rows().size(), 200u);      // compacted
    EXPECT_EQ(t.handles(), kept);
    EXPECT_EQ(t.find(hs[199])->age, 7.5);
    EXPECT_EQ(t.find(hs[190])->xform_index, 190);
    for (int64_t h : kept) EXPECT_TRUE(t.drop(h));
    EXPECT_EQ(t.size(), 0u);
}

TEST(TorpedoTable, FieldsAndUnrepresentable) {
    TorpedoTable t;
    int64_t h = t.add(5, 6);
    t.set_f(h, TorpField::_ttl, 12.5);
    t.set_v(h, TorpField::_last_seen_target_pos, true, {1, 2, 3});
    const TorpedoRow* r = t.find(h);
    EXPECT_EQ(r->ttl, 12.5);
    EXPECT_TRUE(r->last_seen_set);
    EXPECT_EQ(r->last_seen, (Vec3{1, 2, 3}));
    t.set_unrepresentable(h, TorpField::_ttl);
    EXPECT_NE(r->unrepresentable, 0u);
    t.set_f(h, TorpField::_ttl, 1.0);      // a good push clears the flag
    EXPECT_EQ(r->unrepresentable, 0u);
    t.set_v(h, TorpField::_last_seen_target_pos, false, {0, 0, 0});
    EXPECT_FALSE(r->last_seen_set);
    EXPECT_THROW(t.set_f(h, TorpField::_velocity, 1.0), std::invalid_argument);
    EXPECT_THROW(t.set_v(h, TorpField::_velocity, false, {0, 0, 0}),
                 std::invalid_argument);   // the velocity is never unset
    EXPECT_STREQ(torp_field_name(TorpField::_age), "_age");
}

TEST(MirrorK3, PyIdAndTorpedoRefs) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, 1, 2, 3, 0xFFFF000012345678ull);
    EXPECT_EQ(f.m.object(o)->py_id, 0xFFFF000012345678ull);
    int64_t s = f.m.register_row(Kind::Set);
    int64_t sub = f.m.register_row(Kind::Subsystem);
    TorpedoTable& tt = f.m.torpedoes();
    int64_t h = tt.add(9, 1);
    f.m.set_torpedo_ref(h, TorpField::_target_ship, o);
    f.m.set_torpedo_ref(h, TorpField::_containing_set, s);
    f.m.set_torpedo_mount(h, true, sub, {1, 2, 3});
    EXPECT_EQ(f.m.torpedo_ref(*tt.find(h), TorpField::_target_ship), o);
    EXPECT_EQ(f.m.torpedo_ref(*tt.find(h), TorpField::_mount_key), sub);
    // Kinds are checked: a Set is not a target, an Object is not a set.
    EXPECT_THROW(f.m.set_torpedo_ref(h, TorpField::_target_ship, s),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_torpedo_ref(h, TorpField::_containing_set, o),
                 std::invalid_argument);
    f.m.set_torpedo_ref(h, TorpField::_source_ship, kRefUnrepresentable);
    EXPECT_EQ(f.m.torpedo_ref(*tt.find(h), TorpField::_source_ship),
              kRefUnrepresentable);
    // A ref to a since-freed row reads UNREPRESENTABLE, never none: the
    // torpedo holds its referents strongly, so a dead handle means the row
    // was dropped (the object took the Python path), not that it is gone.
    f.m.unregister_row(o);
    EXPECT_EQ(f.m.torpedo_ref(*tt.find(h), TorpField::_target_ship),
              kRefUnrepresentable);
    f.m.set_torpedo_ref(h, TorpField::_target_ship, -1);
    EXPECT_EQ(f.m.torpedo_ref(*tt.find(h), TorpField::_target_ship), -1);
    // The globals carry the lead term; clear() empties the table.
    f.m.set_global_f(Global::LEAD_ACCEL_K, 0.5);
    EXPECT_EQ(f.m.globals().LEAD_ACCEL_K, 0.5);
    f.m.clear();
    EXPECT_EQ(tt.size(), 0u);
}

// Posed parts (native-combat posed parts, Task 1): the per-ship pose table
// and mount order, the per-subsystem part slot, and the global part-map
// generation. Storage only; no kernel reads them yet.
TEST(MirrorPosedParts, DefaultsReadUnresolved) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_TRUE(f.m.object(o)->part_poses.empty());
    EXPECT_TRUE(f.m.object(o)->mount_order.empty());
    EXPECT_EQ(f.m.subsystem(s)->part_slot, -1);
    EXPECT_EQ(f.m.subsystem(s)->part_gen, 0u);
    // The global starts at 1, so a never-resolved slot (gen 0) is stale.
    EXPECT_EQ(f.m.part_gen(), 1u);
}

TEST(MirrorPosedParts, StoresPoseTableSlotAndMountOrder) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s1 = f.m.register_row(Kind::Subsystem);
    int64_t s2 = f.m.register_row(Kind::Subsystem);
    PartPose a{{1, 0, 0, 0, 1, 0, 0, 0, 1}, {0, 0, 0}, true, false};
    PartPose b{{0, -1, 0, 1, 0, 0, 0, 0, 1}, {0.5, -0.0, 2.0}, false, true};
    uint64_t e0 = f.m.epoch();
    f.m.set_part_poses(o, {a, b});
    EXPECT_GT(f.m.epoch(), e0);
    const auto& t = f.m.object(o)->part_poses;
    ASSERT_EQ(t.size(), 2u);
    EXPECT_EQ(t[1].r[1], -1.0);
    EXPECT_EQ(t[1].t[0], 0.5);
    EXPECT_TRUE(std::signbit(t[1].t[1]));
    EXPECT_TRUE(t[0].identity);
    EXPECT_FALSE(t[0].detached);
    EXPECT_FALSE(t[1].identity);
    EXPECT_TRUE(t[1].detached);
    f.m.set_part_slot(s1, 1, 7);
    EXPECT_EQ(f.m.subsystem(s1)->part_slot, 1);
    EXPECT_EQ(f.m.subsystem(s1)->part_gen, 7u);
    f.m.set_mount_order(o, {s2, kRefUnrepresentable, s1});
    EXPECT_EQ(f.m.object(o)->mount_order,
              (std::vector<int64_t>{s2, kRefUnrepresentable, s1}));
    f.m.set_part_gen(9);
    EXPECT_EQ(f.m.part_gen(), 9u);
}

TEST(MirrorPosedParts, RejectsBadHandlesAndEntries) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    // Wrong row kinds.
    EXPECT_THROW(f.m.set_part_poses(s, {}), std::invalid_argument);
    EXPECT_THROW(f.m.set_part_slot(o, 0, 1), std::invalid_argument);
    EXPECT_THROW(f.m.set_mount_order(s, {}), std::invalid_argument);
    // A mount-order entry must be a Subsystem handle or -2.
    EXPECT_THROW(f.m.set_mount_order(o, {o}), std::invalid_argument);
    EXPECT_THROW(f.m.set_mount_order(o, {-1}), std::invalid_argument);
    // A slot below -1 is not an index.
    EXPECT_THROW(f.m.set_part_slot(s, -2, 1), std::invalid_argument);
    f.m.unregister_row(s);
    EXPECT_THROW(f.m.set_part_slot(s, 0, 1), std::invalid_argument);
}

TEST(MirrorPosedParts, ClearResetsRowsAndGeneration) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    f.m.set_part_poses(o, {PartPose{}});
    f.m.set_part_gen(42);
    f.m.clear();
    EXPECT_EQ(f.m.part_gen(), 1u);
    int64_t o2 = f.m.register_row(Kind::Object);
    EXPECT_TRUE(f.m.object(o2)->part_poses.empty());
}

// ── K0: the charging kernel's inputs (native weapon state, Task 3) ──────────

namespace {

bool same_bits(const std::vector<double>& a, const std::vector<double>& b) {
    if (a.size() != b.size()) return false;
    return a.empty() ||
           std::memcmp(a.data(), b.data(), a.size() * sizeof(double)) == 0;
}

}  // namespace

TEST(MirrorTest, FloatListRoundTrip) {
    Fixture f;
    int64_t s = f.m.register_row(Kind::Subsystem);
    EXPECT_EQ(field_type(Field::_reload_timers), FieldType::FloatList);
    EXPECT_EQ(field_type(Field::_reload_advanced_at), FieldType::FloatList);
    EXPECT_EQ(field_kind(Field::_reload_timers), Kind::Subsystem);
    EXPECT_STREQ(field_name(Field::_reload_timers), "_reload_timers");
    EXPECT_STREQ(field_name(Field::_reload_advanced_at), "_reload_advanced_at");
    EXPECT_TRUE(f.m.get_floats(s, Field::_reload_timers).empty());

    // Every bit survives: -0.0, a NaN payload, the loaded sentinel.
    const std::vector<double> timers{-1.0, 0.0, -0.0, std::nan("7"), 12.5};
    uint64_t e = f.m.epoch();
    f.m.set_floats(s, Field::_reload_timers, timers);
    EXPECT_GT(f.m.epoch(), e);
    EXPECT_TRUE(same_bits(f.m.get_floats(s, Field::_reload_timers), timers));
    EXPECT_TRUE(same_bits(f.m.subsystem(s)->_reload_timers, timers));

    // The two lists are independent fields.
    f.m.set_floats(s, Field::_reload_advanced_at, {3.0, -0.0});
    EXPECT_TRUE(same_bits(f.m.get_floats(s, Field::_reload_advanced_at),
                          {3.0, -0.0}));
    EXPECT_TRUE(same_bits(f.m.get_floats(s, Field::_reload_timers), timers));
    f.m.set_floats(s, Field::_reload_timers, {});
    EXPECT_TRUE(f.m.get_floats(s, Field::_reload_timers).empty());

    // Typed: a list setter on a scalar field, a scalar setter on a list
    // field, a list field on another kind's row and a stale handle all throw.
    EXPECT_THROW(f.m.set_floats(s, Field::_condition, {1.0}),
                 std::invalid_argument);
    EXPECT_THROW(f.m.get_floats(s, Field::_condition), std::invalid_argument);
    EXPECT_THROW(f.m.set_f(s, Field::_reload_timers, 1.0),
                 std::invalid_argument);
    int64_t o = f.m.register_row(Kind::Object);
    EXPECT_THROW(f.m.set_floats(o, Field::_reload_timers, {1.0}),
                 std::invalid_argument);
    int64_t gone = f.m.register_row(Kind::Subsystem);
    f.m.unregister_row(gone);
    EXPECT_THROW(f.m.set_floats(gone, Field::_reload_timers, {1.0}),
                 std::invalid_argument);
    EXPECT_THROW(f.m.get_floats(gone, Field::_reload_timers),
                 std::invalid_argument);

    // A cleared (or reused) row reads empty again.
    f.m.set_floats(s, Field::_reload_timers, timers);
    f.m.clear();
    int64_t s2 = f.m.register_row(Kind::Subsystem);
    EXPECT_TRUE(f.m.get_floats(s2, Field::_reload_timers).empty());
}

TEST(MirrorTest, ChargingScalarInputs) {
    Fixture f;
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_f(s, Field::_recharge_rate, 0.3);
    f.m.set_f(s, Field::_reload_delay, -0.0);
    f.m.set_i(s, Field::_watch_checks, 2);
    f.m.set_i(s, Field::_power_level, 1);
    const SubsystemRow* r = f.m.subsystem(s);
    EXPECT_EQ(r->_recharge_rate, 0.3);
    EXPECT_TRUE(std::signbit(r->_reload_delay));
    EXPECT_EQ(r->_watch_checks, 2);
    EXPECT_EQ(r->_power_level, 1);
    EXPECT_EQ(f.m.get_f(s, Field::_recharge_rate), 0.3);
    EXPECT_EQ(f.m.get_i(s, Field::_power_level), 1);
    EXPECT_THROW(f.m.set_i(s, Field::_recharge_rate, 1), std::invalid_argument);
    EXPECT_THROW(f.m.set_f(s, Field::_watch_checks, 1.0),
                 std::invalid_argument);
}

TEST(MirrorTest, PhaserDischargeTableGlobals) {
    Fixture f;
    f.m.set_global_f(Global::PHASER_DISCHARGE_0, 0.35);
    f.m.set_global_f(Global::PHASER_DISCHARGE_1, 1.0);
    f.m.set_global_f(Global::PHASER_DISCHARGE_2, 1.0);
    f.m.set_global_i(Global::PHASER_DISCHARGE_LEN, 3);
    EXPECT_EQ(f.m.globals().PHASER_DISCHARGE_0, 0.35);
    EXPECT_EQ(f.m.globals().PHASER_DISCHARGE_LEN, 3);
    EXPECT_EQ(global_by_name("PHASER_DISCHARGE_2"), Global::PHASER_DISCHARGE_2);
    EXPECT_TRUE(global_is_int(Global::PHASER_DISCHARGE_LEN));
    EXPECT_FALSE(global_is_int(Global::PHASER_DISCHARGE_1));
    EXPECT_THROW(f.m.set_global_f(Global::PHASER_DISCHARGE_LEN, 3.0),
                 std::invalid_argument);
}

TEST(MirrorTest, FloatListElementInPlace) {
    Fixture f;
    int64_t s = f.m.register_row(Kind::Subsystem);
    f.m.set_floats(s, Field::_reload_timers, {-1.0, 2.0, 3.0});
    const double* data = f.m.subsystem(s)->_reload_timers.data();
    uint64_t e = f.m.epoch();
    f.m.set_float_at(s, Field::_reload_timers, 1, -0.0);
    EXPECT_GT(f.m.epoch(), e);
    EXPECT_TRUE(same_bits(f.m.get_floats(s, Field::_reload_timers),
                          {-1.0, -0.0, 3.0}));
    // In place: the list is not reallocated.
    EXPECT_EQ(f.m.subsystem(s)->_reload_timers.data(), data);
    // Out of range, the wrong field type, the wrong row, a stale handle.
    EXPECT_THROW(f.m.set_float_at(s, Field::_reload_timers, 3, 1.0),
                 std::out_of_range);
    EXPECT_THROW(f.m.set_float_at(s, Field::_condition, 0, 1.0),
                 std::invalid_argument);
    int64_t o = f.m.register_row(Kind::Object);
    EXPECT_THROW(f.m.set_float_at(o, Field::_reload_timers, 0, 1.0),
                 std::invalid_argument);
    f.m.unregister_row(s);
    EXPECT_THROW(f.m.set_float_at(s, Field::_reload_timers, 0, 1.0),
                 std::invalid_argument);
}

// Kernel M's inputs (native motion phase 2, Task 2): every field round-trips
// through its typed setter into the row the kernel reads, with its default
// before any push.
TEST(Mirror, MotionFieldsRoundTrip) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    int64_t s = f.m.register_row(Kind::Subsystem);
    const ObjectRow* r = f.m.object(o);
    // Defaults: _angular_space is DIRECTION_WORLD_SPACE (getattr's default),
    // the vectors are unset, the setpoint empty, the ref none.
    EXPECT_EQ(r->_angular_space, 1);
    EXPECT_EQ(r->_current_angular_velocity_state, 0);
    EXPECT_TRUE(r->_speed_setpoint.empty());
    EXPECT_EQ(f.m.get_ref(o, Field::_impulse_engine_subsystem), -1);
    EXPECT_EQ(r->motion_stock, 0);

    f.m.set_f(o, Field::_current_speed, -0.0);
    f.m.set_fv(o, Field::_current_angular_velocity, {0.1, -0.2, 0.3});
    f.m.set_fv(o, Field::_target_angular_velocity_setpoint, {1.0, 2.0, 3.0});
    f.m.set_fv(o, Field::_drift_velocity, {4.0, 5.0, 6.0});
    f.m.set_fv(o, Field::_angular_velocity, {7.0, 8.0, 9.0});
    const std::vector<double> sp{3.5, 0.25, 1.0, -0.5, 1.0};
    f.m.set_floats(o, Field::_speed_setpoint, sp);
    f.m.set_i(o, Field::_angular_space, 0);
    f.m.set_i(o, Field::_static, 1);
    f.m.set_i(o, Field::_stationary, 1);
    f.m.set_i(o, Field::_insystem_warp_transit, 1);
    f.m.set_ref(o, Field::_impulse_engine_subsystem, s);
    f.m.set_i(o, Field::motion_stock, 1);
    EXPECT_TRUE(std::signbit(r->_current_speed));
    EXPECT_EQ(r->_current_angular_velocity, (Vec3{0.1, -0.2, 0.3}));
    EXPECT_EQ(r->_current_angular_velocity_state, 1);
    EXPECT_EQ(r->_target_angular_velocity_setpoint, (Vec3{1.0, 2.0, 3.0}));
    EXPECT_EQ(r->_target_angular_velocity_setpoint_state, 1);
    EXPECT_EQ(r->_drift_velocity, (Vec3{4.0, 5.0, 6.0}));
    EXPECT_EQ(r->_drift_velocity_state, 1);
    EXPECT_EQ(r->_angular_velocity, (Vec3{7.0, 8.0, 9.0}));
    EXPECT_EQ(r->_angular_velocity_state, 1);
    EXPECT_TRUE(same_bits(r->_speed_setpoint, sp));
    EXPECT_TRUE(same_bits(f.m.get_floats(o, Field::_speed_setpoint), sp));
    EXPECT_EQ(r->_angular_space, 0);
    EXPECT_EQ(r->_static, 1);
    EXPECT_EQ(r->_stationary, 1);
    EXPECT_EQ(r->_insystem_warp_transit, 1);
    EXPECT_EQ(r->_impulse_engine_subsystem, s);
    EXPECT_EQ(f.m.get_ref(o, Field::_impulse_engine_subsystem), s);
    EXPECT_EQ(r->motion_stock, 1);
    // The ref checks its target kind and reads a freed IES as none.
    EXPECT_THROW(f.m.set_ref(o, Field::_impulse_engine_subsystem, o),
                 std::invalid_argument);
    f.m.unregister_row(s);
    EXPECT_EQ(f.m.get_ref(o, Field::_impulse_engine_subsystem), -1);

    int64_t ies = f.m.register_row(Kind::Subsystem);
    f.m.set_f(ies, Field::_power_percentage_wanted, 1.25);
    f.m.set_f(ies, Field::_max_speed, 6.3);
    f.m.set_f(ies, Field::_max_accel, 1.7);
    f.m.set_f(ies, Field::_max_angular_velocity, 0.31);
    f.m.set_f(ies, Field::_max_angular_accel, 0.11);
    f.m.set_i(ies, Field::motion_ies_stock, 1);
    f.m.set_i(ies, Field::motion_pod_stock, 1);
    const SubsystemRow* q = f.m.subsystem(ies);
    EXPECT_EQ(q->_power_percentage_wanted, 1.25);
    EXPECT_EQ(q->_max_speed, 6.3);
    EXPECT_EQ(q->_max_accel, 1.7);
    EXPECT_EQ(q->_max_angular_velocity, 0.31);
    EXPECT_EQ(q->_max_angular_accel, 0.11);
    EXPECT_EQ(q->motion_ies_stock, 1);
    EXPECT_EQ(q->motion_pod_stock, 1);

    // Typed and kinded: an Object field on a Subsystem row, a scalar setter
    // on the setpoint list, and the other way round, all throw.
    EXPECT_THROW(f.m.set_f(ies, Field::_current_speed, 1.0),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_f(o, Field::_max_speed, 1.0), std::invalid_argument);
    EXPECT_THROW(f.m.set_f(o, Field::_speed_setpoint, 1.0),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_floats(o, Field::_current_speed, {1.0}),
                 std::invalid_argument);
    EXPECT_STREQ(field_name(Field::_impulse_engine_subsystem),
                 "_impulse_engine_subsystem");
    EXPECT_EQ(field_kind(Field::_max_speed), Kind::Subsystem);
    EXPECT_EQ(field_type(Field::_speed_setpoint), FieldType::FloatList);
    EXPECT_EQ(field_type(Field::_drift_velocity), FieldType::Vec3);

    // A cleared row reads its defaults again.
    f.m.clear();
    int64_t o2 = f.m.register_row(Kind::Object);
    EXPECT_EQ(f.m.object(o2)->_angular_space, 1);
    EXPECT_EQ(f.m.object(o2)->_static, 0);
    EXPECT_TRUE(f.m.object(o2)->_speed_setpoint.empty());
}

// A point-or-none vector: 0 doubles is None (state 0), 3 a TGPoint3 (1), 4
// a value the mirror cannot hold (2, the vector zero). get_fv reads back what
// was set; the state is read-only except through set_fv.
TEST(Mirror, PointOrNoneState) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object);
    const ObjectRow* r = f.m.object(o);
    for (Field v : {Field::_current_angular_velocity, Field::_drift_velocity,
                    Field::_target_angular_velocity_setpoint,
                    Field::_angular_velocity}) {
        EXPECT_TRUE(f.m.get_fv(o, v).empty());
        f.m.set_fv(o, v, {1.0, -0.0, 2.0});
        EXPECT_TRUE(same_bits(f.m.get_fv(o, v), {1.0, -0.0, 2.0}));
        f.m.set_fv(o, v, {0.0, 0.0, 0.0, 0.0});
        EXPECT_EQ(f.m.get_fv(o, v), (std::vector<double>{0, 0, 0, 0}));
        f.m.set_fv(o, v, {});
        EXPECT_TRUE(f.m.get_fv(o, v).empty());
        EXPECT_THROW(f.m.set_fv(o, v, {1.0, 2.0}), std::invalid_argument);
    }
    f.m.set_fv(o, Field::_drift_velocity, {3.0, 4.0, 5.0});
    EXPECT_EQ(r->_drift_velocity_state, 1);
    EXPECT_EQ(f.m.get_i(o, Field::_drift_velocity_state), 1);
    f.m.set_fv(o, Field::_drift_velocity, {9.0, 9.0, 9.0, 9.0});
    EXPECT_EQ(r->_drift_velocity_state, 2);
    EXPECT_EQ(r->_drift_velocity, (Vec3{0, 0, 0}));
    f.m.set_fv(o, Field::_drift_velocity, {});
    EXPECT_EQ(r->_drift_velocity_state, 0);
    EXPECT_EQ(r->_drift_velocity, (Vec3{0, 0, 0}));
    // The other vectors are untouched by it.
    EXPECT_EQ(r->_angular_velocity_state, 0);
    // The state is written only with its vector.
    EXPECT_THROW(f.m.set_i(o, Field::_drift_velocity_state, 1),
                 std::invalid_argument);
    // A non-nullable vector still takes exactly 3 doubles.
    EXPECT_THROW(f.m.set_fv(o, Field::_velocity, {1.0, 2.0, 3.0, 4.0}),
                 std::invalid_argument);
    EXPECT_THROW(f.m.set_fv(o, Field::_velocity, {}), std::invalid_argument);
}

// _velocity keeps its Vec3 for every kernel; _velocity_state beside it is 0
// until a push, 1 after any 3-double set_fv (a TGPoint3 is what every
// native writer stores), and Python sets 2 for a non-TGPoint3 value.
TEST(Mirror, VelocityState) {
    Fixture f;
    int64_t o = f.m.register_row(Kind::Object, 3, 4, 77);
    EXPECT_EQ(f.m.get_i(o, Field::_velocity_state), 0);
    f.m.set_fv(o, Field::_velocity, {1.0, 2.0, 3.0});
    EXPECT_EQ(f.m.get_i(o, Field::_velocity_state), 1);
    f.m.set_i(o, Field::_velocity_state, 2);
    EXPECT_EQ(f.m.get_i(o, Field::_velocity_state), 2);
    EXPECT_EQ(f.m.get_fv(o, Field::_velocity),
              (std::vector<double>{1.0, 2.0, 3.0}));
    f.m.set_fv(o, Field::_velocity, {4.0, 5.0, 6.0});
    EXPECT_EQ(f.m.get_i(o, Field::_velocity_state), 1);
}
