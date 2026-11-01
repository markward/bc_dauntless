#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/beam_trace.h"
#include "dauntless/combat/k2_beams.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/combat/projectile_geometry.h"
#include "dauntless/combat/step_scan.h"
#include "dauntless/transform_store.h"

// K3, the native torpedo kernel (native combat phase 3, Task 4).
//
// A resumable walk of engine/appc/projectiles.update_all's decision steps
// 0-3 (the ship cache, guide + advance of every torpedo, the broadphase and
// the narrow hit test) over the Mirror, its torpedo table and the step scan.
// docs/reference/engine/native-combat/k3-k4-map.md (K3M) section A1.1 is the
// walk and A6 its ordering contract; spec docs/superpowers/specs/2026-11-01-
// native-combat-k3-k4-design.md sections 4.3-4.5 bind. k3_projectiles.cc
// names every cursor state after the Python line it stands for. Every float
// is made by projectile_geometry / beam_geometry / beam_trace /
// sensor_detect, the Python-exact ports, or the store's sweep_candidates.
//
// A BATCH. Steps 1-3 of update_all post no event and call no SDK script
// (K3M A1 corrections), so the kernel decides every torpedo before Python
// applies anything: next() returns ASKs (a question only Python can answer,
// about one torpedo or one ship) and finally DONE. There is no RUN_PYTHON
// after begin: everything that sends the step to Python is decided by begin.
//
// WHOLE STEP TO PYTHON. begin() returns a reason (and opens no session) when
//   scan             the step scan is not representable (step_scan.h), or
//                    `scan_serial` is given and is not its serial (the
//                    driver's scan is not the current one);
//   table            the torpedo table's live row count is not `n_active`
//                    (len(_active)): a dirty table, a torpedo listed twice
//                    (the rebuild leaves the table empty), a non-Torpedo
//                    entry;
//   unrepresentable  a row has any `unrepresentable` bit;
//   stale_ref        a row's target, source, set or mount reads -2 (a
//                    dropped referent row);
//   torpedo_xform    a row's TransformStore slot is not live;
//   ship_cache       the ship cache cannot be built (an alive scan ship's
//                    transform or bound the mirror cannot answer).
// The driver adds its own Python-side reasons before calling begin (switch
// off, audit, `_active` not an _ActiveList, a patched function, the table
// still dirty after a rebuild).
//
// WRITES ARE MADE AT DONE. During the walk the kernel writes nothing to the
// torpedo table or the TransformStore: it decides. Only when it emits DONE
// does it apply every torpedo's row fields (age; and for a natively guided
// one last_seen / last_tvel / velocity, as written) and every torpedo's
// final position into the store (TTL expiries at cur_pos, the rest at
// cur_pos or ON the bubble), then return the write log for Python to copy
// into its own attributes WITHOUT pushing them back. Deferring is
// unobservable: no ASK's Python reads another torpedo's age, velocity or
// position (a torpedo target is never in the scan, so it is an ASK guide).
// So an abandon() before DONE leaves the table and the store exactly as at
// begin. The native can_detect latch and memo ARE written live, in torpedo
// list order, exactly as Python's own calls write them, and are not undone.
//
// RECORDS (K3Kind), as the binding builds them (handles: torpedo table
// handles for torpedoes, Object handles for ships, Set handles for sets; -1
// None; xyz a 3-tuple of floats):
//   0 DONE  (DONE, writes, expired, hits)
//     writes   [(torp, age, last_seen_xyz | None, last_tvel_xyz | None,
//                vel_xyz | None), ...] one per torpedo in `_active` order.
//              `age` is `t._age` after `+= dt`. The other three are the
//              native _guide's writes in Python's write order (last_seen,
//              last_tvel, velocity), None where _guide did not write that
//              field this tick (not guided, a ballistic/early return, the
//              invisible branch, the dist < 1e-6 return; or the torpedo was
//              an ASK guide, whose writes Python already made and pushed).
//              A `vel` write must also reach torpedo_scan.set_velocity,
//              exactly as the `_velocity` setter does today.
//     expired  [torp, ...]: TTL expiries in list order, then hits in list
//              order -- the order Python calls expire(t).
//     hits     [(torp, ship, hit_xyz, tier, normal_xyz | None,
//                bubble_xyz | None, hit_is_bubble), ...] in list order.
//              tier "mesh" | "sphere" | "fallback" | "origin" (beam_trace).
//              hit_is_bubble: the fallback tier on a bubble hit, where
//              Python's hit_point, seg_cur and torpedo._bubble_entry are ONE
//              TGPoint3 (build one object for all three); otherwise each is
//              its own fresh TGPoint3. `t._bubble_entry` is written (bubble
//              or None) for every hit torpedo, and only for those.
//   1 ASK   (ASK, query, *args) -> reply combat_k3_answer. Unlike K2 an ASK
//           carries no writes (they come at DONE). Queries:
//     frame        (set)                -> frames.frame_of(set) interned in
//                                          the step's key table:
//                                          (key_id, ax, ay, az), key_id -1
//                                          (or the bare None) for None.
//         A set with no frame-table entry. The kernel installs the answer in
//         the step scan's frame table and repeats the compare (a torpedo's
//         guide may ask twice: torpedo->target, then source->target).
//     steer_point  (torp, target, off_xyz) -> p = projectiles._steer_point(
//                                          t, target, off) -> (p.x, p.y, p.z)
//         The target has posed parts under an offset, or the shot's
//         `_mount_key` is not attributed to this target and offset. Python's
//         _steer_point writes `_mount_key` (pushed into the row). `off` is
//         frames.offset_between(torpedo set, target set) as a tuple.
//     guide        (torp)               -> projectiles._guide(t, dt); None
//         Anything on one torpedo's guide path the kernel cannot vouch for:
//         a target or source not in the step scan (its class or overrides
//         are unchecked), a target without a real IsDead, a can_detect that
//         threw. Its writes push into the row; the kernel then advances it
//         with the row's velocity.
//     shields_block (ship)              -> bool(combat.shields_block(ship))
//     bubble       (ship, origin_xyz, aim_xyz, max_dist)
//                                       -> combat.shield_bubble_entry(ship,
//                                          TGPoint3(*origin), TGPoint3(*aim),
//                                          max_dist): (x, y, z) or None
//     resolve_hit  (ship, origin_xyz, dir_xyz | None, max_dist,
//                   fallback_xyz)       -> as K2's resolve_hit: ((x, y, z),
//                                          normal or None, tier)
//         shields_block / bubble / resolve_hit: the K2 conditions
//         (k2_beams.h), on the narrow path.
//
// PINNING. The kernel holds handles only. Every ASK runs Python that frees
// no row (a pure query, or _guide / _steer_point writing the asked
// torpedo's own fields), and the step's ships_list and `_active` hold every
// object a record names. The driver must resolve DONE's torpedo handles to
// objects BEFORE it calls expire(): `_active.remove` drops the row.
//
// A THROW from next() (a protocol error: an ASK unanswered, a row gone that
// no ASK could have dropped) restores the session -- cursor, pending answer
// -- to its state before the call; nothing was written, so abandon() leaves
// the mirror equal to Python.

namespace dauntless::combat {

enum class K3Kind : int32_t { DONE = 0, ASK, kCount };
const char* k3_kind_name(K3Kind k);

enum class K3Query : int32_t {
    frame = 0,
    steer_point,
    guide,
    shields_block,
    bubble,
    resolve_hit,
    kCount
};
const char* k3_query_name(K3Query q);

// Why begin() handed the whole step to Python (see above).
enum class K3Why : int32_t {
    scan = 0,
    table,
    unrepresentable,
    stale_ref,
    torpedo_xform,
    ship_cache,
    kCount
};
const char* k3_why_name(K3Why w);

// One torpedo's write log entry (DONE).
struct K3TorpWrite {
    int64_t torp = -1;
    double age = 0.0;
    std::optional<Vec3> last_seen, last_tvel, vel;
};

struct K3Hit {
    int64_t torp = -1, ship = -1;
    ResolvedHit hit;  // point, tier, normal
    std::optional<Vec3> bubble;
    bool hit_is_bubble = false;
};

using K3Arg = std::variant<std::monostate, int64_t, double, Vec3>;

struct K3Record {
    K3Kind kind = K3Kind::DONE;
    K3Query query = K3Query::kCount;  // ASK
    std::vector<K3Arg> args;          // ASK
    std::vector<K3TorpWrite> writes;  // DONE
    std::vector<int64_t> expired;     // DONE
    std::vector<K3Hit> hits;          // DONE
};

// The reply to an ASK. Which fields are read depends on the query:
//   frame: key (-1 None) and point (the anchor);
//   steer_point: point;
//   guide: nothing;
//   shields_block: flag;
//   bubble: none or point;
//   resolve_hit: point, normal, tier.
struct K3Answer {
    bool flag = false;
    bool none = false;
    int64_t key = -1;
    Vec3 point{0, 0, 0};
    std::optional<Vec3> normal;
    ResolvedHit::Tier tier = ResolvedHit::Tier::Fallback;
};

class K3Kernel {
public:
    // `store` must be the store `m` reads (the kernel writes torpedo
    // positions into it at DONE); `scan` is the step scan K4 used this step.
    K3Kernel(Mirror& m, TransformStore& store, StepScan& scan);

    // The walk over this step's torpedo table. `ctx` is K2's per-step
    // context (npc_shields_off, player, view_offsets, iids, hooks;
    // python_ships is unused). `n_active` is len(projectiles._active).
    // `keep_iids`: ctx.iids is replaced by the previous context's table.
    // `scan_serial`: the StepScan::serial of the scan the driver took this
    // step; a different one is a stale scan (reason scan).
    // Returns nullopt with a session open, or the reason the whole step is
    // Python's (no session). Throws std::logic_error if a session is open.
    std::optional<K3Why> begin(double dt, const GuideClocks& clocks,
                               bool use_memo, K2Context ctx, int64_t n_active,
                               bool keep_iids = false,
                               std::optional<uint64_t> scan_serial = {});

    // The next record. Throws std::logic_error when no session is open, an
    // ASK has no answer, the session already returned DONE, or a row the
    // walk needs has gone (protocol invariant).
    K3Record next();
    K3Query awaiting() const;
    void answer(const K3Answer& a);

    void end();      // the session must have returned DONE
    void abandon();  // whatever its state (an exception unwound Python)
    bool open() const { return static_cast<bool>(session_); }
    void clear();
    const K2Context& context() const { return ctx_; }

    struct Counts {
        int64_t runs = 0, python_steps = 0, records = 0;
        std::array<int64_t, static_cast<size_t>(K3Why::kCount)> why{};
        std::array<int64_t, static_cast<size_t>(K3Query::kCount)> queries{};
        // guide ASKs by reason (GuideResult::why, or "target_not_in_scan" /
        // "source_not_in_scan").
        std::map<std::string, int64_t> guide_why;
    };
    const Counts& counts() const { return counts_; }
    void reset_counts() { counts_ = Counts{}; }

    struct Session;  // the cursor (k3_projectiles.cc)

private:
    Mirror& m_;
    TransformStore& store_;
    StepScan& scan_;
    K2Context ctx_;
    std::unique_ptr<Session> session_;
    Counts counts_;

public:
    ~K3Kernel();
    K3Kernel(const K3Kernel&) = delete;
    K3Kernel& operator=(const K3Kernel&) = delete;
};

// The process-wide kernel over mirror(), transform_store() and step_scan().
K3Kernel& k3_kernel();

}  // namespace dauntless::combat
