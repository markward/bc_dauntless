// native/tests/host/combat_effect_queue_test.cc
//
// The combat effect queue (spec 2026-11-02-combat-fire-events-design.md
// §4.1): one emission order for kernel (handle) and Python (object)
// entries, and the object references the queue owns released exactly once
// -- by clear, never by take (the taker owns them). Objects are opaque here: the test's releaser counts.
#include <gtest/gtest.h>

#include "combat_effect_queue.h"

#include <cstdint>
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
