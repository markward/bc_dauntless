// The native impulse fractions -- see impulse.h. A port of
// subsystems.impulse_fractions, each step naming the Python it stands for.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/impulse.h"

#include <stdexcept>
#include <string>

#include "dauntless/combat/py_math.h"
#include "dauntless/combat/sensor_detect.h"

namespace dauntless::combat {

namespace {

[[noreturn]] void fall_back(const char* why) {
    throw std::invalid_argument(std::string("combat impulse: ") + why +
                                " -- answer in Python");
}

const SubsystemRow& sub_row(const Mirror& m, int64_t ref, const char* what) {
    if (ref == kRefUnrepresentable) fall_back(what);
    const SubsystemRow* r = m.subsystem(ref);
    if (!r) fall_back(what);
    return *r;
}

// ShipSubsystem.IsDisabled (subsystems.py): reads _max_condition.
bool is_disabled(const SubsystemRow& s) {
    if (s._max_condition <= 0.0) return false;
    const double threshold = s._disabled_percentage * s._max_condition;
    return s._condition <= threshold;
}

// ShipSubsystem.IsDestroyed.
bool is_destroyed(const SubsystemRow& s) {
    if (s._destroyed) return true;
    if (s._max_condition > 0.0 && s._condition <= 0.0) return true;
    return false;
}

// subsystems._is_offline.
bool is_offline(const Mirror& m, const SubsystemRow& s) {
    if (is_disabled(s) || is_destroyed(s)) return true;
    return is_offline_after_condition(m, s);
}

}  // namespace

ImpulseFractions impulse_fractions(const Mirror& m, int64_t ies_ref) {
    if (ies_ref == -1) return {1.0, 1.0};
    const SubsystemRow& ies = sub_row(m, ies_ref, "impulse engine ref");
    if (is_offline(m, ies)) return {0.0, 0.0};
    const size_t n = ies._children.size();
    double online, cur;
    if (n == 0) {
        online = 1.0;
        cur = 1.0;
    } else {
        // `implements(ies, "GetParentShip")`: _is_offline(ies) above then
        // established the ship in action, so the pods' ship clause is skipped.
        const bool ship_known_good = ies.has_parent_ship_getter != 0;
        int64_t online_n = 0;
        double contrib = 0.0;
        for (size_t i = 0; i < n; ++i) {
            const SubsystemRow& pod = sub_row(m, ies._children[i], "pod ref");
            const bool disabled = is_disabled(pod);
            bool offline;
            if (ship_known_good)
                offline = disabled || is_destroyed(pod);
            else
                offline = is_offline(m, pod);
            if (!offline) ++online_n;
            if (!disabled) contrib += condition_percentage(m, pod);
        }
        online = static_cast<double>(online_n) / static_cast<double>(n);
        cur = contrib / static_cast<double>(n);
    }
    if (!ies._is_on) return {online, 0.0};
    cur = py_max(0.0, py_min(1.0, cur));
    return {online, cur * ies._power_percentage_wanted};
}

}  // namespace dauntless::combat
