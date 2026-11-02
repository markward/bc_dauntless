#pragma once

#include <cstdint>
#include <string_view>
#include <variant>
#include <vector>

// The kernels' write-log representation, shared by the combat library (the
// K0 charging kernel logs it, k0_charging.h) and the host's C applier
// (native/src/host/combat_write_apply.h applies it: ApplyWrite is
// LoggedWrite). Plain C++: no Python here.
//
// A logged write is (handle, Python attribute name, value). The name is a
// std::string_view of storage that outlives every log: a string literal or
// field_name()'s static table in the kernels, the applier's never-freed name
// pool for a parsed Python log (combat_write_apply.cc). The applier caches
// each name's interned str by the view's address (checked by content), so a
// write costs no string copy or hash. The value is one
// of K1's encodings (None, bool, int, float, the walk-offset marker, a
// handle list) or one of K0's two in-place writes:
//   SlotWrite     obj.<field>[index] = value, on the object's EXISTING list
//                 (a tube's _reload_timers / _reload_advanced_at)
//   WatcherWrite  obj.<field>._value = value, `field` the attribute holding
//                 the FloatRangeWatcher ("_charge_watcher")
// K1 and K2 keep their own value type (K1Value, the first six
// alternatives) and the same name type; the applier's Python-log parser
// (combat_apply_log) uses LoggedValue. K0 logs its own plain K0Write
// (k0_charging.h): no string, no variant.

namespace dauntless::combat {

// The marker for "the walk's own offset object" (K1 ruling P5): the walk
// that logged it (the K1 session's walk number) and its system, so the
// driver can fetch that walk's object even when the write rides a later
// walk's record. k1_fire_control.h documents it.
struct K1WalkOffset {
    int64_t walk = -1;
    int64_t system = -1;
    bool operator==(const K1WalkOffset& o) const {
        return walk == o.walk && system == o.system;
    }
};

// A slot or watcher value: None, bool, int or float.
using WriteScalar = std::variant<std::monostate, bool, int64_t, double>;

struct SlotWrite {
    int64_t index = 0;
    WriteScalar value;
};

struct WatcherWrite {
    WriteScalar value;
};

// K1Value's alternatives in K1Value's order, then K0's two.
using LoggedValue =
    std::variant<std::monostate, bool, int64_t, double, K1WalkOffset,
                 std::vector<int64_t>, SlotWrite, WatcherWrite>;

struct LoggedWrite {
    int64_t handle = -1;
    std::string_view field;  // the Python attribute name (see above)
    LoggedValue value;
};

}  // namespace dauntless::combat
