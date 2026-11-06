#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/k2_scan.h"

namespace dauntless::combat {

namespace {

// weapon_kind (mirror.h): the phaser system's and the bank's.
constexpr int64_t kPhaserSystem = 1, kPhaserBank = 5;

// A stock row of weapon kind `kind` (nullptr: gone).
bool stock(const SubsystemRow* r, int64_t kind) {
    return r != nullptr && r->k2_stock == 1 && r->weapon_kind == kind;
}

bool clean(const Mirror& m, int64_t ship) {
    const ObjectRow* o = m.object(ship);
    if (o == nullptr) return false;
    const int64_t sys = o->_phaser_system;
    if (sys == -1) return true;
    if (sys == kRefUnrepresentable) return false;
    const SubsystemRow* s = m.subsystem(sys);
    if (!stock(s, kPhaserSystem)) return false;
    for (const int64_t b : s->_children) {
        if (b == kRefUnrepresentable) return false;
        const SubsystemRow* bank = m.subsystem(b);
        if (!stock(bank, kPhaserBank)) return false;
        if (bank->_target == kRefUnrepresentable) return false;
    }
    return true;
}

}  // namespace

std::vector<size_t> k2_unclean_ships(const Mirror& m,
                                     const std::vector<int64_t>& handles) {
    std::vector<size_t> out;
    for (size_t i = 0; i < handles.size(); ++i) {
        const int64_t h = handles[i];
        if (h == -1) continue;
        if (!clean(m, h)) out.push_back(i);
    }
    return out;
}

}  // namespace dauntless::combat
