#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "dauntless/combat/k2_scan.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

// K2's ship scan answered from the mirror (k2_scan.h): which ships the
// driver must hand to native_combat._k2_python_ship.

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr int64_t kPhaserSystemKind = 1, kPhaserBankKind = 5;

struct Fixture {
    TransformStore store;
    Mirror m{store};

    // A stock subsystem row of `weapon_kind`.
    int64_t sub(int64_t weapon_kind, int64_t stock = 1) {
        const int64_t h = m.register_row(Kind::Subsystem);
        m.set_i(h, Field::weapon_kind, weapon_kind);
        m.set_i(h, Field::k2_stock, stock);
        return h;
    }

    // A ship with a stock phaser system of `banks` stock banks, each aiming
    // at `target` (-1: none). Returns the ship; `sys` and `kids` its rows.
    int64_t ship(int banks, int64_t target, int64_t* sys = nullptr,
                 std::vector<int64_t>* kids = nullptr) {
        const int64_t o = m.register_row(Kind::Object, -1, -1, ++next_id);
        const int64_t s = sub(kPhaserSystemKind);
        std::vector<int64_t> b;
        for (int i = 0; i < banks; ++i) {
            const int64_t bank = sub(kPhaserBankKind);
            m.set_ref(bank, Field::_target, target);
            b.push_back(bank);
        }
        m.set_ids(s, Field::_children, b);
        m.set_ref(o, Field::_phaser_system, s);
        if (sys) *sys = s;
        if (kids) *kids = b;
        return o;
    }

    int64_t next_id = 0;
};

using Idx = std::vector<size_t>;

}  // namespace

TEST(K2Scan, StockShipIsClean) {
    Fixture f;
    const int64_t a = f.ship(3, -1);
    const int64_t b = f.ship(2, a);
    EXPECT_EQ(k2_unclean_ships(f.m, {a, b}), Idx{});
}

TEST(K2Scan, NoSystemIsClean) {
    // A ship with no phaser system (-1) is clean, as is a handle of -1
    // (no row: never checked).
    Fixture f;
    const int64_t o = f.m.register_row(Kind::Object, -1, -1, 1);
    EXPECT_EQ(k2_unclean_ships(f.m, {o, -1}), Idx{});
}

TEST(K2Scan, UnrepresentableSystemIsUnclean) {
    Fixture f;
    const int64_t o = f.ship(2, -1);
    f.m.set_ref(o, Field::_phaser_system, kRefUnrepresentable);
    EXPECT_EQ(k2_unclean_ships(f.m, {o}), Idx{0});
}

TEST(K2Scan, SubclassedSystemIsUnclean) {
    Fixture f;
    int64_t sys = -1;
    const int64_t o = f.ship(2, -1, &sys);
    f.m.set_i(sys, Field::k2_stock, 0);
    EXPECT_EQ(k2_unclean_ships(f.m, {o}), Idx{0});
}

TEST(K2Scan, SubclassedBankIsUnclean) {
    Fixture f;
    std::vector<int64_t> kids;
    const int64_t o = f.ship(3, -1, nullptr, &kids);
    f.m.set_i(kids[2], Field::k2_stock, 0);
    EXPECT_EQ(k2_unclean_ships(f.m, {o}), Idx{0});
}

TEST(K2Scan, WrongRoleIsUnclean) {
    // k2_stock says "a stock bank or phaser system class"; weapon_kind says
    // which. A stock BANK row as the ship's phaser system, or a stock
    // SYSTEM row among the banks, is not its role: unclean.
    Fixture f;
    int64_t sys = -1;
    const int64_t a = f.ship(2, -1, &sys);
    const int64_t bank = f.sub(kPhaserBankKind);
    f.m.set_ref(a, Field::_phaser_system, bank);
    std::vector<int64_t> kids;
    const int64_t b = f.ship(2, -1, nullptr, &kids);
    f.m.set_i(kids[1], Field::weapon_kind, kPhaserSystemKind);
    const int64_t c = f.ship(2, -1);
    EXPECT_EQ(k2_unclean_ships(f.m, {a, b, c}), (Idx{0, 1}));
    // Both rows keep k2_stock 1: the role alone decides.
    EXPECT_EQ(f.m.get_i(bank, Field::k2_stock), 1);
    EXPECT_EQ(f.m.get_i(kids[1], Field::k2_stock), 1);
}

TEST(K2Scan, NoRowChildIsUnclean) {
    Fixture f;
    int64_t sys = -1;
    std::vector<int64_t> kids;
    const int64_t o = f.ship(2, -1, &sys, &kids);
    f.m.set_ids(sys, Field::_children,
                {kids[0], kRefUnrepresentable, kids[1]});
    EXPECT_EQ(k2_unclean_ships(f.m, {o}), Idx{0});
}

TEST(K2Scan, NoRowTargetIsUnclean) {
    Fixture f;
    std::vector<int64_t> kids;
    const int64_t o = f.ship(2, -1, nullptr, &kids);
    f.m.set_ref(kids[1], Field::_target, kRefUnrepresentable);
    EXPECT_EQ(k2_unclean_ships(f.m, {o}), Idx{0});
}

TEST(K2Scan, GoneShipRowIsUnclean) {
    // A handle whose row is gone (freed), and a system or bank row freed
    // under a live ref, are unclean: the scan cannot read them.
    Fixture f;
    const int64_t gone = f.ship(1, -1);
    f.m.unregister_row(gone);
    int64_t sys = -1;
    const int64_t o = f.ship(1, -1, &sys);
    std::vector<int64_t> kids;
    const int64_t p = f.ship(1, -1, nullptr, &kids);
    f.m.unregister_row(sys);
    f.m.unregister_row(kids[0]);
    EXPECT_EQ(k2_unclean_ships(f.m, {gone, o, p}), (Idx{0, 1, 2}));
}

TEST(K2Scan, OrderIsKept) {
    Fixture f;
    const int64_t a = f.ship(1, -1);
    int64_t sys_b = -1;
    const int64_t b = f.ship(1, -1, &sys_b);
    const int64_t c = f.ship(1, -1);
    std::vector<int64_t> kids_d;
    const int64_t d = f.ship(2, -1, nullptr, &kids_d);
    f.m.set_i(sys_b, Field::k2_stock, 0);
    f.m.set_ref(kids_d[0], Field::_target, kRefUnrepresentable);
    EXPECT_EQ(k2_unclean_ships(f.m, {a, b, -1, c, d}), (Idx{1, 4}));
}
