// native/tests/host/combat_effect_queue_test.cc
//
// The combat effect queue (spec 2026-11-02-combat-fire-events-design.md
// §4.1): one emission order for kernel (handle) and Python (object)
// entries, and the object references the queue owns released exactly once
// -- by clear, never by take (the taker owns them). Objects are opaque here: the test's releaser counts.
#include <gtest/gtest.h>

#include "combat_effect_queue.h"

#include <cstdint>
#include <cstring>
#include <map>
#include <span>
#include <string>
#include <vector>

namespace {

using dauntless::host::EffectEntry;
using dauntless::host::EffectKind;
using dauntless::host::EffectOperand;
using dauntless::host::EffectQueue;

std::vector<void*> g_released;

void count_release(void* p) { g_released.push_back(p); }

class EffectQueueTest : public ::testing::Test {
protected:
    void SetUp() override { g_released.clear(); }
    EffectQueue q{&count_release};
    int a = 0, b = 0, c = 0;   // stand-in Python objects (addresses only)
};

}  // namespace

TEST_F(EffectQueueTest, NativeEntriesComeOutInOrderWithTheirOperands) {
    q.append_native(EffectKind::FIRE_SOUND, std::int64_t{7});
    q.append_native(EffectKind::WEAPON_FIRED, std::int64_t{7},
                    std::int64_t{-1});
    q.append_native(EffectKind::WATCH, std::int64_t{9}, 0.25, 0.75);
    ASSERT_EQ(q.size(), 3u);
    std::vector<EffectEntry> out = q.take();
    EXPECT_TRUE(q.empty());
    ASSERT_EQ(out.size(), 3u);
    EXPECT_EQ(out[0].kind, EffectKind::FIRE_SOUND);
    EXPECT_TRUE(out[0].native);
    ASSERT_EQ(out[0].count, 1);
    EXPECT_EQ(out[0].ops[0].type, EffectOperand::Type::Handle);
    EXPECT_EQ(out[0].ops[0].handle, 7);
    EXPECT_EQ(out[1].kind, EffectKind::WEAPON_FIRED);
    ASSERT_EQ(out[1].count, 2);
    EXPECT_EQ(out[1].ops[1].handle, -1);
    EXPECT_EQ(out[2].kind, EffectKind::WATCH);
    ASSERT_EQ(out[2].count, 3);
    EXPECT_EQ(out[2].ops[0].handle, 9);
    EXPECT_EQ(out[2].ops[1].type, EffectOperand::Type::Number);
    EXPECT_EQ(out[2].ops[1].number, 0.25);
    EXPECT_EQ(out[2].ops[2].number, 0.75);
    EXPECT_TRUE(g_released.empty());
}

TEST_F(EffectQueueTest, NativeAndObjectAppendsShareOneOrder) {
    void* objs1[] = {&a};
    void* objs2[] = {&b, &c};
    q.append_objects(EffectKind::LOOP_STOP, objs1);
    q.append_native(EffectKind::TORPEDO_RELOAD, std::int64_t{3});
    q.append_objects(EffectKind::TORPEDO_FIRED, objs2);
    std::vector<EffectEntry> out = q.take();
    ASSERT_EQ(out.size(), 3u);
    EXPECT_EQ(out[0].kind, EffectKind::LOOP_STOP);
    EXPECT_FALSE(out[0].native);
    EXPECT_EQ(out[0].ops[0].type, EffectOperand::Type::Object);
    EXPECT_EQ(out[0].ops[0].object, &a);
    EXPECT_EQ(out[1].kind, EffectKind::TORPEDO_RELOAD);
    EXPECT_TRUE(out[1].native);
    EXPECT_EQ(out[2].kind, EffectKind::TORPEDO_FIRED);
    ASSERT_EQ(out[2].count, 2);
    EXPECT_EQ(out[2].ops[0].object, &b);
    EXPECT_EQ(out[2].ops[1].object, &c);
    // take hands the references over: nothing released.
    EXPECT_TRUE(g_released.empty());
}

TEST_F(EffectQueueTest, ClearReleasesEveryObject) {
    void* objs[] = {&a, &b};
    q.append_objects(EffectKind::TORPEDO_FIRED, objs);
    q.append_native(EffectKind::FIRE_SOUND, std::int64_t{1});
    q.clear();
    EXPECT_TRUE(q.empty());
    EXPECT_EQ(g_released, (std::vector<void*>{&a, &b}));
}

TEST_F(EffectQueueTest, KindNamesCoverEveryKind) {
    for (int i = 0; i < static_cast<int>(EffectKind::kCount); ++i)
        EXPECT_NE(dauntless::host::effect_kind_name(
                      static_cast<EffectKind>(i)),
                  nullptr);
    EXPECT_STREQ(dauntless::host::effect_kind_name(EffectKind::WATCH),
                 "WATCH");
}

// The damage kinds (native damage §4.3) follow the weapon kinds -- SPAWN,
// then the two tractor events (fire control native only, R8) -- in
// effect_queue.py's order: the binding hands Python these numbers.
TEST_F(EffectQueueTest, DamageKindsFollowTheWeaponKindsInOrder) {
    const char* names[] = {"COND_WATCH", "SUBSYS_EVENT", "REPAIR_ADD",
                           "ZERO_CROSS", "SPLASH", "HIT_PRESENT",
                           "WEAPON_HIT"};
    EXPECT_EQ(static_cast<int>(EffectKind::TRACTOR_STARTED),
              static_cast<int>(EffectKind::SPAWN) + 1);
    EXPECT_STREQ(dauntless::host::effect_kind_name(EffectKind::TRACTOR_STOPPED),
                 "TRACTOR_STOPPED");
    const int first = static_cast<int>(EffectKind::TRACTOR_STOPPED) + 1;
    ASSERT_EQ(static_cast<int>(EffectKind::kCount), first + 7);
    for (int i = 0; i < 7; ++i)
        EXPECT_STREQ(dauntless::host::effect_kind_name(
                         static_cast<EffectKind>(first + i)),
                     names[i]);
    // HIT_PRESENT, spelled (points as xyz), is the longest entry.
    EXPECT_GE(EffectEntry::kMaxOperands, 35);
}

// The damage kinds' frozen operand layouts (native damage fix round, I4):
// one type letter per operand -- R a mirror handle (-1 None), H an object
// the entry holds, D a double, I an int code, B a bool -- the same layout
// effect_queue.OPERANDS gives Python. The weapon kinds have none.
TEST_F(EffectQueueTest, TheDamageKindsHaveFrozenOperandLayouts) {
    using dauntless::host::effect_kind_operands;
    EXPECT_STREQ(effect_kind_operands(EffectKind::COND_WATCH), "RIDD");
    EXPECT_STREQ(effect_kind_operands(EffectKind::SUBSYS_EVENT), "RI");
    EXPECT_STREQ(effect_kind_operands(EffectKind::REPAIR_ADD), "R");
    EXPECT_STREQ(effect_kind_operands(EffectKind::ZERO_CROSS), "RRBH");
    EXPECT_STREQ(effect_kind_operands(EffectKind::SPLASH), "R");
    EXPECT_STREQ(effect_kind_operands(EffectKind::HIT_PRESENT),
                 "RHBDDDBDDDDRDDDIIDBBBBDDDBDDDBDDBBD");
    EXPECT_STREQ(effect_kind_operands(EffectKind::WEAPON_HIT),
                 "RHDDDDBDDDDRIB");
    EXPECT_EQ(effect_kind_operands(EffectKind::SPAWN), nullptr);
    EXPECT_EQ(effect_kind_operands(EffectKind::WATCH), nullptr);
    EXPECT_EQ(static_cast<int>(std::strlen(
                  effect_kind_operands(EffectKind::HIT_PRESENT))),
              EffectEntry::kMaxOperands);
}

// A kernel's int code and bool flag are their own operand types, apart
// from a handle (a bare int64) and a number.
TEST_F(EffectQueueTest, IntsAndBoolsAreTheirOwnOperandTypes) {
    using dauntless::host::EffectBool;
    using dauntless::host::EffectInt;
    q.append_native(EffectKind::ZERO_CROSS, std::int64_t{4}, std::int64_t{9},
                    EffectBool{true}, std::int64_t{-1});
    q.append_native(EffectKind::COND_WATCH, std::int64_t{9}, EffectInt{1},
                    1.0, 0.25);
    std::vector<EffectEntry> out = q.take();
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].ops[2].type, EffectOperand::Type::Bool);
    EXPECT_TRUE(out[0].ops[2].boolean);
    EXPECT_EQ(out[0].ops[3].type, EffectOperand::Type::Handle);
    EXPECT_EQ(out[0].ops[3].handle, -1);
    EXPECT_EQ(out[1].ops[1].type, EffectOperand::Type::Int);
    EXPECT_EQ(out[1].ops[1].integer, 1);
    EXPECT_EQ(out[1].ops[2].number, 1.0);
    EXPECT_TRUE(dauntless::host::effect_operands_match(
        EffectKind::COND_WATCH, std::span(out[1].ops.data(), out[1].count)));
    EXPECT_TRUE(dauntless::host::effect_operands_match(
        EffectKind::ZERO_CROSS, std::span(out[0].ops.data(), out[0].count)));
}

// The layout check a kernel's append is held to (assert): the type of
// every operand, and the count.
TEST_F(EffectQueueTest, AnOperandOfTheWrongTypeDoesNotMatchTheLayout) {
    using dauntless::host::effect_operands_match;
    EffectOperand ok[4], h, d, i, b, obj;
    h.type = EffectOperand::Type::Handle;
    h.handle = 3;
    d.type = EffectOperand::Type::Number;
    d.number = 0.5;
    i.type = EffectOperand::Type::Int;
    i.integer = 0;
    b.type = EffectOperand::Type::Bool;
    b.boolean = false;
    obj.type = EffectOperand::Type::Object;
    obj.object = &a;
    ok[0] = h; ok[1] = i; ok[2] = d; ok[3] = d;
    EXPECT_TRUE(effect_operands_match(EffectKind::COND_WATCH, ok));
    EffectOperand wrong[4] = {h, d, d, d};          // `which` as a number
    EXPECT_FALSE(effect_operands_match(EffectKind::COND_WATCH, wrong));
    EXPECT_FALSE(effect_operands_match(EffectKind::COND_WATCH,
                                       std::span(ok, 3)));
    // R: a handle, or an object a rebind left; H: an object, or -1.
    EffectOperand rebound[4] = {obj, i, d, d};
    EXPECT_TRUE(effect_operands_match(EffectKind::COND_WATCH, rebound));
    EffectOperand none = h;
    none.handle = -1;
    EffectOperand zc[4] = {h, h, b, none};
    EXPECT_TRUE(effect_operands_match(EffectKind::ZERO_CROSS, zc));
    zc[3] = obj;
    EXPECT_TRUE(effect_operands_match(EffectKind::ZERO_CROSS, zc));
    zc[3] = h;                                       // a live handle
    EXPECT_FALSE(effect_operands_match(EffectKind::ZERO_CROSS, zc));
    // A weapon kind has no layout: anything matches.
    EXPECT_TRUE(effect_operands_match(EffectKind::WATCH, wrong));
}

// The code operands' values (effect_queue.py's constants of the same
// names; combat_effect_codes() hands Python this table).
TEST_F(EffectQueueTest, TheCodeTableNamesEveryCode) {
    using namespace dauntless::host;
    std::map<std::string, int> codes;
    for (const EffectCode& c : effect_codes())
        EXPECT_TRUE(codes.emplace(c.name, c.value).second) << c.name;
    EXPECT_EQ(codes.size(), 17u);
    EXPECT_EQ(codes["WATCH_CONDITION"], static_cast<int>(CondWatch::CONDITION));
    EXPECT_EQ(codes["WATCH_COMBINED"], 1);
    EXPECT_EQ(codes["SUBSYS_DESTROYED"], 0);
    EXPECT_EQ(codes["SUBSYS_OPERATIONAL"],
              static_cast<int>(SubsysEvent::OPERATIONAL));
    EXPECT_EQ(codes["TRANSITION_DESTROYED"], 2);
    EXPECT_EQ(codes["HIT_WEAPON_COLLISION"],
              static_cast<int>(HitWeapon::COLLISION));
    EXPECT_EQ(codes["WEAPON_HIT_NON_WEAPON"], -1);
    EXPECT_EQ(codes["WEAPON_HIT_TRACTOR_BEAM"], 2);
}

// A row dropped while its kernel entries wait (native_combat._drop: a value
// the mirror cannot hold): every pending NATIVE operand naming that handle
// becomes the object, one reference taken per operand, so the entry is
// still delivered. Object entries and other handles are left alone.
TEST_F(EffectQueueTest, RebindTurnsAHandleIntoTheObject) {
    std::vector<void*> acquired;
    static std::vector<void*>* seen = nullptr;
    seen = &acquired;
    auto acquire = [](void* p) -> void* {
        seen->push_back(p);
        return p;
    };
    void* objs[] = {&b};
    q.append_native(EffectKind::TORPEDO_RELOAD, std::int64_t{5});
    q.append_native(EffectKind::WATCH, std::int64_t{5}, 0.5, 0.25);
    q.append_native(EffectKind::WEAPON_FIRED, std::int64_t{6},
                    std::int64_t{5});
    q.append_objects(EffectKind::LOOP_STOP, objs);
    q.append_native(EffectKind::FIRE_SOUND, std::int64_t{6});
    EXPECT_EQ(q.rebind(5, &a, acquire), 3u);
    EXPECT_EQ(acquired, (std::vector<void*>{&a, &a, &a}));
    std::vector<EffectEntry> out = q.take();
    ASSERT_EQ(out.size(), 5u);
    EXPECT_TRUE(out[0].native);
    EXPECT_EQ(out[0].ops[0].type, EffectOperand::Type::Object);
    EXPECT_EQ(out[0].ops[0].object, &a);
    EXPECT_EQ(out[1].ops[0].type, EffectOperand::Type::Object);
    EXPECT_EQ(out[1].ops[1].type, EffectOperand::Type::Number);
    EXPECT_EQ(out[1].ops[1].number, 0.5);
    EXPECT_EQ(out[2].ops[0].type, EffectOperand::Type::Handle);
    EXPECT_EQ(out[2].ops[0].handle, 6);
    EXPECT_EQ(out[2].ops[1].type, EffectOperand::Type::Object);
    EXPECT_EQ(out[3].ops[0].object, &b);
    EXPECT_EQ(out[4].ops[0].handle, 6);
    // A NONE operand (-1) is never a row: never rebound.
    q.append_native(EffectKind::WEAPON_FIRED, std::int64_t{6},
                    std::int64_t{-1});
    EXPECT_EQ(q.rebind(-1, &a, acquire), 0u);
    // A rebound operand is released by clear like any object.
    q.append_native(EffectKind::TORPEDO_RELOAD, std::int64_t{8});
    EXPECT_EQ(q.rebind(8, &c, acquire), 1u);
    q.clear();
    EXPECT_EQ(g_released, (std::vector<void*>{&c}));
}

// A launch's SPAWN (spec 2026-11-02-combat-launch-deferral §4.1): a kernel
// entry carrying its whole fire-time record -- handles, numbers and the
// target as an object the queue owns (its fire-time value, delivered even
// if its row is freed) -- in one entry, in order.
TEST_F(EffectQueueTest, ASpawnCarriesItsWholeRecord) {
    using dauntless::host::NativeOperand;
    using dauntless::host::OwnedObject;
    std::vector<NativeOperand> ops;
    ops.push_back(std::int64_t{4});   // the launcher
    ops.push_back(0.0);               // the kind
    ops.push_back(OwnedObject{&a});   // the target
    for (int i = 0; i < EffectEntry::kMaxOperands - 3; ++i)
        ops.push_back(0.5 * i);
    q.append_native_span(EffectKind::SPAWN, ops);
    std::vector<EffectEntry> out = q.take();
    ASSERT_EQ(out.size(), 1u);
    EXPECT_EQ(out[0].kind, EffectKind::SPAWN);
    EXPECT_TRUE(out[0].native);
    ASSERT_EQ(out[0].count, EffectEntry::kMaxOperands);
    EXPECT_EQ(out[0].ops[0].handle, 4);
    EXPECT_EQ(out[0].ops[1].type, EffectOperand::Type::Number);
    EXPECT_EQ(out[0].ops[2].type, EffectOperand::Type::Object);
    EXPECT_EQ(out[0].ops[2].object, &a);
    EXPECT_EQ(out[0].ops[EffectEntry::kMaxOperands - 1].number,
              0.5 * (EffectEntry::kMaxOperands - 4));
    EXPECT_TRUE(g_released.empty());  // the taker owns it
    // Dropped undelivered, the owned object is released once.
    q.append_native_span(EffectKind::SPAWN, ops);
    q.clear();
    EXPECT_EQ(g_released, (std::vector<void*>{&a}));
    EXPECT_STREQ(dauntless::host::effect_kind_name(EffectKind::SPAWN),
                 "SPAWN");
    EXPECT_GE(EffectEntry::kMaxOperands, 23);
}

// The native damage entries' in-place append: the same entry the span
// append makes from NativeOperands (native set, operands as typed), in
// the one emission order, and an object operand released by clear as any.
TEST_F(EffectQueueTest, AnInPlaceNativeEntryIsTheSpansEntry) {
    using dauntless::host::EffectBool;
    using dauntless::host::EffectInt;
    using dauntless::host::NativeOperand;
    using dauntless::host::OwnedObject;
    const NativeOperand span_ops[] = {std::int64_t{4}, OwnedObject{&a},
                                      EffectBool{true}, std::int64_t{-1}};
    q.append_native_span(EffectKind::ZERO_CROSS, span_ops);
    EffectEntry e;
    e.kind = EffectKind::ZERO_CROSS;
    e.count = 4;
    e.ops[0].type = EffectOperand::Type::Handle;
    e.ops[0].handle = 4;
    e.ops[1].type = EffectOperand::Type::Object;
    e.ops[1].object = &b;
    e.ops[2].type = EffectOperand::Type::Bool;
    e.ops[2].boolean = true;
    e.ops[3].type = EffectOperand::Type::Handle;
    e.ops[3].handle = -1;
    q.append_native_entry(e);
    q.append_native(EffectKind::COND_WATCH, std::int64_t{9}, EffectInt{1},
                    1.0, 0.25);
    ASSERT_EQ(q.size(), 3u);
    std::vector<EffectEntry> out = q.take();
    ASSERT_EQ(out.size(), 3u);
    for (int k : {0, 1}) {
        EXPECT_EQ(out[k].kind, EffectKind::ZERO_CROSS);
        EXPECT_TRUE(out[k].native);
        ASSERT_EQ(out[k].count, 4);
        EXPECT_EQ(out[k].ops[0].type, EffectOperand::Type::Handle);
        EXPECT_EQ(out[k].ops[0].handle, 4);
        EXPECT_EQ(out[k].ops[1].type, EffectOperand::Type::Object);
        EXPECT_EQ(out[k].ops[2].type, EffectOperand::Type::Bool);
        EXPECT_TRUE(out[k].ops[2].boolean);
        EXPECT_EQ(out[k].ops[3].type, EffectOperand::Type::Handle);
        EXPECT_EQ(out[k].ops[3].handle, -1);
    }
    EXPECT_EQ(out[0].ops[1].object, &a);
    EXPECT_EQ(out[1].ops[1].object, &b);
    EXPECT_EQ(out[2].kind, EffectKind::COND_WATCH);
    // Owned by the queue until taken: nothing released by take.
    EXPECT_TRUE(g_released.empty());
    q.append_native_entry(e);
    q.clear();
    ASSERT_EQ(g_released.size(), 1u);
    EXPECT_EQ(g_released[0], &b);
}
