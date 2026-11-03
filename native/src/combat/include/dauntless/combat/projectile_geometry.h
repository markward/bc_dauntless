#pragma once

#include <array>
#include <cstdint>
#include <optional>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/step_scan.h"
#include "dauntless/combat/torpedo_table.h"

// The native projectile geometry of the K3 kernel (phase 3, Task 3): the
// broadphase bound, the end-point sphere test, torpedo guidance, the advance
// and the unposed steer point. docs/reference/engine/native-combat/
// k3-k4-map.md sections A1.1-A1.3 and A3 (B1, G1-G12, A1-A8) are the
// specification; spec docs/superpowers/specs/2026-11-01-native-combat-k3-k4-
// design.md §4.4 and §6 bind as well.
//
// Each function is a line-for-line port of the Python function named in its
// comment in projectile_geometry.cc, reading the Mirror, its TransformStore
// and the step's frame table. Floats are Python's: double, the same operand
// order, py_min / py_max in Python's argument order, `** 0.5` as py_pow,
// Length as std::sqrt, math.sin as py_sin, math.acos as libm acos after the
// clamp, every NaN branch as Python's. Handles are Object rows for ships and
// targets, Set rows for sets; -1 is Python's None.
//
// FALLBACK. As in beam_geometry.h, bubble_bound_radius and
// steer_point_native throw std::invalid_argument (Python ValueError) when
// they cannot answer exactly as the Python would (a stale or unrepresentable
// ref, an invalid transform, a posed target whose mount slot is not
// current; steer_point_native answers posed mounts and picked spots
// itself). guide_torpedo
// never throws for that: it returns a status naming the question Python must
// answer instead (GuideResult).

namespace dauntless::combat {

// combat.bubble_bound_radius (B1), world_radius's and _hull_box_for's rules
// included. Throws for a ship with no live Object row (Python's unreadable
// radius drops the row: the step scan hands such a step to Python), and for
// a row that is not a ShipClass (world_radius's DebrisChunk rule and a stub
// GetScale are not mirrored; the step scan admits only ShipClass rows).
double bubble_bound_radius(const Mirror& m, int64_t ship);

// combat.sphere_hit (A8): squared distance <= r * r (NaN -> false).
bool sphere_hit(const Vec3& p, const Vec3& c, double r);

// update_all's advance (A1-A6) of one torpedo from `prev` (its GetTranslate)
// with its post-guide velocity. `expired` is `age >= ttl` (a NaN age or ttl
// never expires); seg / seg_len / aim_unit are filled only when not expired
// (Python computes them only then). aim_unit is nullopt for seg_len <= 1e-9
// (NaN included).
struct Advance {
    Vec3 cur{0.0, 0.0, 0.0};
    double age = 0.0;
    bool expired = false;
    Vec3 seg{0.0, 0.0, 0.0};
    double seg_len = 0.0;
    std::optional<Vec3> aim_unit;
};
Advance advance_torpedo(const Vec3& prev, const Vec3& vel, double dt,
                        double age, double ttl);

// projectiles._steer_point for a target the mirror can answer: `offset`
// nullopt is the no-offset hull centre (G12). Otherwise
// target_offset_world(target, offset, mount_sub) (G11): an unposed target
// whatever the mount, a POSED one through the mount's part slot only when
// the offset is the mount's own point (weapon_geometry.h); a picked spot
// (mount_sub -1), or an offset off its mount, is body_point_world(target,
// offset): pos + R·(scale·offset), NO part pose, for the whole flight (fire
// control native only, M5, M8.5). `off` is frames.offset_between(torpedo
// set, target set), never None here; the point is shifted only when `off`
// is not (0, 0, 0) by C `==` (Python's tuple ==). Throws for a mount_sub of
// -2, a stale target / invalid transform, and target_offset_world's posed
// fallback (PartStale for a slot that is not current).
Vec3 steer_point_native(const Mirror& m, int64_t target,
                        const std::optional<Vec3>& offset, int64_t mount_sub,
                        const Vec3& off);

// The two clocks can_detect reads (sensor_detect.h): `drift_now` the nebula
// drift clock (native_combat.now()), `occ_now` the occlusion clock
// (sensor_occlusion._now() / the weapons' Utopia game time).
struct GuideClocks {
    double drift_now = 0.0;
    double occ_now = 0.0;
};

// What _guide would write, in its write order: `_last_seen_target_pos`,
// `_last_target_vel`, `_velocity` (each a fresh TGPoint3). `_mount_key` is
// never here: only the steer-point ASK writes it, in Python.
enum class GuideField : int32_t { last_seen, last_tvel, velocity };

struct GuideWrite {
    GuideField field = GuideField::velocity;
    Vec3 value{0.0, 0.0, 0.0};
};

// Everything _guide had decided when it stopped for the steer point, so the
// kernel can carry on without re-running can_detect (whose latch and memo
// writes are order-dependent per pair and must happen once).
struct GuideResume {
    int64_t target = -1;
    double speed = 0.0;
    Vec3 torp_pos{0.0, 0.0, 0.0};
};

// Why a steer point is Python's (GuideResult::steer_why of
// need_steer_point). posed_target is retired (posed parts, Task 4): never
// counted, kept for dashboards one release.
//   unattributed          the shot's `_mount_key` is not this target/offset
//                         and the mirror cannot attribute it
//                         (authored_mount_subsystem's kMountUnknown; else
//                         the kernel attributes it: GuideResult::attributed)
//   mount_unrepresentable the attributed mount is a row the mirror can't name
//   posed_target          (retired)
//   mount_stale           a posed target, the mount's row is gone
//   part_stale            a posed target, the mount's part slot not current
//   geometry              the steer geometry fell back otherwise
enum class SteerWhy : int32_t {
    unattributed = 0,
    mount_unrepresentable,
    posed_target,
    mount_stale,
    part_stale,
    geometry,
    kCount
};
// The counter's Python-visible name ("unattributed", ...).
const char* steer_why_name(SteerWhy w);

struct GuideResult {
    enum class Status : int32_t {
        // _guide's answer: `writes[0..n_writes)` in Python's write order
        // (possibly none: an early return).
        done,
        // A set with no frame-table entry (`frame_set`): ASK frame(set),
        // install it, and call guide_torpedo AGAIN from the start. Nothing
        // has been decided or written (no can_detect has run).
        need_frame,
        // _steer_point is Python's (a mount the shot has not attributed and
        // the mirror cannot tell, or a posed target whose mount slot cannot
        // carry the offset;
        // steer_why says which): ASK steer_point(t), which also
        // writes `_mount_key`, then call guide_torpedo_resume with the point
        // and `resume`. can_detect HAS run: never start over.
        need_steer_point,
        // Something on the guide path the mirror cannot vouch for (a -2 or
        // stale ref, a target without a real IsDead, an unrepresentable row
        // field or visibility input, a can_detect that threw): ASK guide(t),
        // Python's _guide whole. No writes are reported.
        need_guide,
    };
    Status status = Status::done;
    std::array<GuideWrite, 3> writes{};
    int n_writes = 0;
    int64_t frame_set = -1;    // need_frame
    GuideResume resume{};      // need_steer_point
    // need_guide: a short reason, for counters.
    const char* why = nullptr;
    // need_steer_point: why the steer point is Python's.
    SteerWhy steer_why = SteerWhy::kCount;
    // done: the steer point was a POSED target's offset (a mount, or a
    // picked spot's plain body point), computed natively.
    bool posed_steer = false;
    // done: the shot's `_mount_key` was not this target/offset and the
    // mount was attributed natively (authored_mount_subsystem, round trips
    // Task 4): `mount` is the subsystem handle (-1 None) Python's
    // `_mount_key[4]` would hold. The caller logs the write.
    bool attributed = false;
    int64_t mount = -1;
};


// projectiles._guide(torpedo, dt) (G1-G12) for one torpedo row, with
// _target_visible's native can_detect from the FIRING ship: memo-eligible
// (`use_memo` = step_memo.active()) for the same-set / zero-offset and the
// other-frame (`off is None`) calls; the cross-region call passes
// dist_sq_gu and skips the memo. Writes nothing to the row; can_detect
// writes its latch and memo exactly as the Python's call would.
GuideResult guide_torpedo(Mirror& m, const TorpedoRow& row, double dt,
                          const StepScan& frames, bool use_memo,
                          const GuideClocks& clocks);

// The rest of _guide after a need_steer_point: `steer_point` is
// _steer_point's answer (torpedo-set coordinates). Throws
// std::invalid_argument if the target's row has gone since the ASK (it
// cannot start over: can_detect has run); the ASK writes only `_mount_key`,
// so in practice the row is still there.
GuideResult guide_torpedo_resume(const Mirror& m, const TorpedoRow& row,
                                 double dt, const GuideResume& resume,
                                 const Vec3& steer_point);

}  // namespace dauntless::combat
