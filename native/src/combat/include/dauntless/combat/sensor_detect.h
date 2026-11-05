#pragma once

#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

#include "dauntless/combat/mirror.h"

// The native sensor-detection kernel: engine/appc/sensor_detection.py
// (`can_detect` and its pieces) and engine/appc/sensor_occlusion.py
// (`blocked`), answered from the Mirror with no Python crossing.
//
// Each function is a line-for-line port of the Python function of the SAME
// NAME, in its gate order (docs/reference/engine/native-combat/
// can-detect-inputs.md §1, §4, §9.3), so the two read side by side. Floats
// are Python's: double, the same operand order, py_min/py_max in Python's
// argument order, and every comparison written so a NaN takes the branch
// Python takes.
//
// Arguments are Object row handles. `now` is a game time the Python reads
// itself: in concealment_at, the nebula drift clock
// (App.g_kTimerManager.GetGameTime() via sensor_detection._game_time); in
// occ_blocked, the occlusion cache's clock (App.g_kUtopiaModule.GetGameTime()
// via sensor_occlusion._now). These are NOT the same value today (CDM §3 #12
// assumed they were): the shim's TGTimerManager has no GetGameTime, so the
// drift clock reads 0.0. can_detect, which needs both, takes `occ_now`.
//
// FALLBACK. Every function throws std::invalid_argument (Python ValueError)
// when it cannot answer exactly as the Python would, so the caller asks the
// Python instead:
//   * a ref it reaches reads kRefUnrepresentable (-2): a non-None Python
//     referent the mirror cannot name. -1 is None and is answered here;
//   * a ref or set-list entry it reaches names a row that is gone (stale);
//   * a set list it walks holds a -2 entry;
//   * an Object's transform is invalid (Python's _get_xyz would log and read
//     the origin; unreachable for a registered object, CDM §9.5);
//   * the nebula noise meets a non-finite value (Python raises; R5);
//   * a case the mirror cannot prove matches the Python: a plain (non-Meta)
//     Nebula in `jammed` (Python calls a _Stub), a parent ship with no
//     ShipClass flag in `_out_of_action`, a MetaNebula with no _fbm.
// Only what the query actually reaches is checked, as in the Python.
//
// State written (sensor_state.h): the latch, the memo, the probe-walk guard
// and the occlusion caches, exactly where and when the Python writes its own.
// A throw can leave a write the Python would ALSO have made before raising at
// the same point (a latch flip, a rebuilt rock list); re-asking the same
// question gives the same answer, so a fallback re-run is unaffected.

namespace dauntless::combat {

// Pieces of the subsystem surface the weapon fire gates (fire_gates.h) share:
// subsystems._is_offline after its IsDisabled/IsDestroyed test (radiation
// outage on the subsystem or its parent, then the parent ship out of action),
// and ShipSubsystem.GetConditionPercentage (the property max when set).
bool is_offline_after_condition(const Mirror& m, const SubsystemRow& sub);
double condition_percentage(const Mirror& m, const SubsystemRow& sub);

// ShipSubsystem.IsDisabled / IsDestroyed (reading _max_condition, not the
// property max) and subsystems._is_offline on a leaf subsystem, as the
// detection kernel asks them. subsystem_is_offline throws
// std::invalid_argument where the mirror cannot answer (an unrepresentable
// parent, a parent ship that is not a ShipClass row): the caller hands that
// question to Python. Shared with the subsystem stage (subsystem_step.cc:
// the shield piece; the power plant's recharge gate).
bool subsystem_is_disabled(const SubsystemRow& s);
bool subsystem_is_destroyed(const SubsystemRow& s);
bool subsystem_is_offline(const Mirror& m, const SubsystemRow& s);
// ShipSubsystem.GetMaxCondition: the property template's MaxCondition when
// set and > 0, else _max_condition. Throws std::invalid_argument for a
// `_property` the mirror cannot name (the subsystem stage's repair piece).
double subsystem_max_condition(const Mirror& m, const SubsystemRow& s);

// sensor_detection.effective_sensor_range
double effective_sensor_range(const Mirror& m, int64_t ship);

// sensor_detection.concealment_at
double concealment_at(const Mirror& m, int64_t ship, double now);

// sensor_detection.is_hidden_by_cloak
bool is_hidden_by_cloak(const Mirror& m, int64_t target);

// sensor_detection.jammed
bool jammed(const Mirror& m, int64_t observer, int64_t target);

// sensor_detection.in_reach (writes the probe-walk guard only)
bool in_reach(Mirror& m, int64_t observer, int64_t target);

// sensor_occlusion.blocked (owns both occlusion caches)
bool occ_blocked(Mirror& m, int64_t observer, int64_t target, double now);

// sensor_detection.can_detect. `use_memo` is step_memo.active(): the memo is
// read and written only when it is true AND no optional argument is given
// (dist_sq and concealment absent, apply_concealment true), as the Python.
//
// Two clocks, as in the Python: `now` is the nebula drift clock
// (sensor_detection._game_time, App.g_kTimerManager.GetGameTime), and
// `occ_now` the occlusion cache's (sensor_occlusion._now,
// App.g_kUtopiaModule.GetGameTime). They are NOT the same value today: the
// shim's TGTimerManager has no GetGameTime, so _game_time() reads 0.0.
// `occ_now` absent means `now`.
bool can_detect(Mirror& m, int64_t observer, int64_t target, double now,
                bool use_memo, std::optional<double> dist_sq_gu = std::nullopt,
                bool apply_concealment = true,
                std::optional<double> concealment = std::nullopt,
                std::optional<double> occ_now = std::nullopt);

// sensor_occlusion.begin_tick / reset
void occ_begin_tick(Mirror& m, double now_gt);
void occ_reset(Mirror& m);

// sensor_detection.reset_concealment_state / _latched. `latched` throws on a
// handle that is not a live Object row, like set_latched.
void latch_reset(Mirror& m);
bool latched(const Mirror& m, int64_t observer, int64_t target);

// sensor_detection._set_latched for a registered pair (ruling R7: one latch
// owner). Throws std::invalid_argument, writing nothing, when either handle
// is not a live Object row.
void set_latched(Mirror& m, int64_t observer, int64_t target, bool broken);

// The audit (Task 6 fix 1): every observer latched against `target`, sorted.
// A native can_detect(a, b) -- its probe walk included -- writes only pairs
// whose target is b, so snapshot(b) / restore(b, snapshot) undoes all of it.
std::vector<int64_t> latch_snapshot(const Mirror& m, int64_t target);
// Replace target's pairs with `observers` (rows no longer live are skipped).
void latch_restore(Mirror& m, int64_t target,
                   const std::vector<int64_t>& observers);

// Every latched (observer, target) pair `h` is in, either side, sorted: what
// a row about to be dropped hands to the Python latch (Task 6 fix 2).
std::vector<std::pair<int64_t, int64_t>> latch_pairs_of(const Mirror& m,
                                                        int64_t h);

// step_memo.forget() for sensor_detection._answers AND subsystems._mounts
// (weapon_geometry.h's mount memo)
void memo_clear(Mirror& m);

}  // namespace dauntless::combat
