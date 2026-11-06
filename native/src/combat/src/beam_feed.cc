// build_beam_feed (beam_feed.h): engine/host_loop.py's beam render builders
// over the Mirror. Each block names the Python line it stands for; the
// CURRENT Python is the truth.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/beam_feed.h"

#include <array>
#include <optional>
#include <stdexcept>
#include <string>

#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/part_pose.h"
#include "dauntless/combat/py_math.h"
#include "frames_internal.h"
#include "geometry_internal.h"

namespace dauntless::combat {

using detail::obj;
using detail::shifted;
using detail::sub;

namespace {

// The feed's own refusals: the item is skipped, counted under `why`.
struct Skip : std::invalid_argument {
    BeamSkip why;
    Skip(BeamSkip w, const std::string& what)
        : std::invalid_argument("combat beam feed: " + what), why(w) {}
};

[[noreturn]] void skip(BeamSkip why, const std::string& what) {
    throw Skip(why, what);
}

// Run `f` (one item's build); on any exception count it under its reason
// and return false. Nothing is appended inside `f`: the caller appends a
// whole item only when this returns true.
template <class F>
bool guarded(BeamSkips& skips, F&& f) {
    BeamSkip why = BeamSkip::Error;
    try {
        f();
        return true;
    } catch (const Skip& e) {
        why = e.why;
    } catch (const PartStale&) {
        why = BeamSkip::PartStale;
    } catch (const MountUnknown&) {
        why = BeamSkip::MountUnknown;
    } catch (const detail::FramesUnanswerable&) {
        why = BeamSkip::Frames;
    } catch (const std::invalid_argument&) {
        why = BeamSkip::Geometry;
    } catch (const std::exception&) {
        why = BeamSkip::Error;
    }
    ++skips[static_cast<size_t>(why)];
    return false;
}

// ── engine/systems/frames.py ────────────────────────────────────────────────

// A `_containing_set` value: -1 (None) or a live Set row.
int64_t containing_set(const Mirror& m, int64_t object) {
    const int64_t s = obj(m, object)._containing_set;
    if (s != -1 && (s < 0 || !m.set(s)))
        skip(BeamSkip::ContainingSet, "_containing_set unnamed");
    return s;
}

// The frames.py helpers over this feed's table (frames_internal.h).
std::optional<Vec3> offset_between(const Mirror& m, const BeamFeedCtx& ctx,
                                   int64_t a, int64_t b) {
    return detail::offset_between(m, ctx.frames, a, b);
}

std::optional<Vec3> to_render(const Mirror& m, const BeamFeedCtx& ctx,
                              int64_t view, int64_t pset, const Vec3& p) {
    return detail::to_render(m, ctx.frames, ctx.origin, view, pset, p);
}

std::optional<Vec3> view_offset(const Mirror& m, const BeamFeedCtx& ctx,
                                int64_t pset) {
    return detail::view_offset(m, ctx.frames, ctx.view, pset);
}

// ── combat.shields_block, for any target ────────────────────────────────────
// A target whose GetShields is TGObject's stub (has_real_get_shields 0: a
// plain DamageableObject, any non-ship) is answered here, as Python answers
// it: `shields = ship.GetShields()` is a truthy _Stub; HasShields() and
// IsOn() are truthy _Stubs (no early return); IsDisabled() is a truthy _Stub
// -> return False. (An object that is no TGObject at all has no GetShields:
// None -> False too.) A ShipClass is beam_geometry's shields_block; a
// non-ShipClass with a REAL GetShields has no port and is skipped. The K2
// kernel keeps beam_geometry's refusal for both: it hands such a target to
// Python, which this feed cannot.
bool feed_shields_block(const Mirror& m, const BeamFeedCtx& ctx,
                        int64_t target) {
    const ObjectRow& t = obj(m, target);
    if (!t.has_real_get_shields) return false;
    if (!t.is_ship_class)
        skip(BeamSkip::Shields, "a non-ShipClass target with a real GetShields");
    return shields_block(m, target, ctx.npc_shields_off, ctx.player);
}

// ── host_loop._beam_endpoint ────────────────────────────────────────────────

Vec3 beam_endpoint(Mirror& m, const BeamFeedCtx& ctx, int64_t target,
                   const Vec3& emitter_pos, const Vec3& aim_unit,
                   double raw_length, const Vec3& fallback) {
    // if raw_length > 1e-6 and combat.shields_block(target):
    if (raw_length > 1e-6 && feed_shields_block(m, ctx, target)) {
        const std::optional<Vec3> entry = shield_bubble_entry(
            m, target, emitter_pos, aim_unit, raw_length * 1.5);
        if (entry) return *entry;
    }
    // if raw_length > 1e-6 and ship_instances is not None: (the table is
    // always given; an absent entry is _resolve_hit_point's iid None)
    if (raw_length > 1e-6) {
        static const TraceHooks kNoHost;
        std::optional<InstanceId> iid;
        std::optional<Vec3> off;
        const TraceHooks* hooks = &ctx.hooks;
        const auto it = ctx.iids.find(target);
        if (it != ctx.iids.end()) {
            // to_view = frames.view_offset(frames.containing_set(ship)):
            // only reached with an instance (combat.py:107-114).
            off = view_offset(m, ctx, containing_set(m, target));
            iid = it->second.id;
            // Not an InstanceId: host_io raises inside the try -> sphere.
            if (it->second.bad) hooks = &kNoHost;
        }
        const ResolvedHit hit =
            resolve_hit_point(m, *hooks, target, iid, emitter_pos, aim_unit,
                              raw_length * 1.5, fallback, off);
        return hit.point;  // `clipped` is never None
    }
    return fallback;
}

// ── host_loop._beam_descriptor_pair + _beam_pair_in_view ────────────────────
// The pair (outer, inner) in RENDER space, or nullopt where either returns
// []. `ship_set` is the memo's set_of(ship).

using Pair = std::array<BeamOut, 2>;

std::optional<Pair> beam_pair(Mirror& m, const BeamFeedCtx& ctx, int64_t ship,
                              int64_t ship_set, int64_t bank,
                              double brightness, double end_width_scale) {
    const SubsystemRow& b = sub(m, bank);
    // target = bank._target; if target is None: return []
    const int64_t target = b._target;
    if (target == -1) return std::nullopt;
    if (target < 0 || !m.object(target))
        skip(BeamSkip::TargetRow, "bank _target unnamed");
    // ship_set / target_set = _frames.containing_set(...)
    const int64_t s_set = containing_set(m, ship);
    const int64_t t_set = containing_set(m, target);
    // to_ship = (0,0,0) if ship_set is target_set else offset_between(...)
    std::optional<Vec3> to_ship;
    if (s_set == t_set)
        to_ship = Vec3{0.0, 0.0, 0.0};
    else
        to_ship = offset_between(m, ctx, s_set, t_set);
    if (!to_ship) return std::nullopt;
    // target_pos, target_sub = _phaser_aim_point(ship, target)
    const Vec3 target_pos =
        phaser_aim_point(m, ship, target, ctx.use_memo).point;
    // emitter_pos = bank._strip_emit_position(shifted(target_pos, to_ship))
    const Vec3 emitter_pos = strip_emit_position(
        m, bank, shifted(target_pos, *to_ship), ctx.use_memo);
    const Vec3 emitter_t = shifted(emitter_pos, *to_ship, -1.0);
    const double dx = target_pos[0] - emitter_t[0];
    const double dy = target_pos[1] - emitter_t[1];
    const double dz = target_pos[2] - emitter_t[2];
    const double raw_length = py_pow(dx * dx + dy * dy + dz * dz, 0.5);
    double beam_length = raw_length;
    Vec3 beam_end = target_pos;
    if (raw_length > 1e-6) {
        const Vec3 aim_unit{dx / raw_length, dy / raw_length, dz / raw_length};
        beam_end = beam_endpoint(m, ctx, target, emitter_t, aim_unit,
                                 raw_length, beam_end);
        const double cdx = beam_end[0] - emitter_t[0];
        const double cdy = beam_end[1] - emitter_t[1];
        const double cdz = beam_end[2] - emitter_t[2];
        beam_length = py_pow(cdx * cdx + cdy * cdy + cdz * cdz, 0.5);
    }
    // The row again: no row reference is held across the geometry calls.
    const SubsystemRow& v = sub(m, bank);
    const double tile_per_unit = v._length_texture_tile_per_unit;
    const double u_tiles =
        tile_per_unit > 0 ? py_max(1.0, beam_length * tile_per_unit) : 1.0;
    const double mut = ctx.width_mutator;
    const double core_scale = py_or(v._core_scale, 0.50);
    const double outer_half = py_or(v._phaser_width, 0.30) * mut;
    const double inner_half = py_or(v._main_radius, 0.15) * core_scale * mut;
    const double taper_radius = py_or(v._taper_radius, 0.01) * mut;
    // outer_color = bank.GetOuterShellColor(); ic = bank.GetInnerCoreColor()
    if (!v.outer_shell_color_set)
        skip(BeamSkip::ColourUnset, "outer shell colour unset");
    if (!v.inner_core_color_set)
        skip(BeamSkip::ColourUnset, "inner core colour unset");
    const Vec4& oc = v._outer_shell_color;
    const Vec4& ic = v._inner_core_color;

    BeamOut common{};
    common.u_tiles = u_tiles;
    common.num_sides = v._num_sides != 0 ? v._num_sides : 6;  // int(x or 6)
    common.taper_radius = taper_radius;
    common.taper_ratio = py_or(v._taper_ratio, 0.25);
    common.taper_min_length = py_or(v._taper_min_length, 5.0);
    common.taper_max_length = py_or(v._taper_max_length, 30.0);
    common.perimeter_tile = py_or(v._perimeter_tile, 1.0);
    common.texture_speed = py_or(v._texture_speed, 0.0);
    common.end_width_scale = end_width_scale;

    // _beam_pair_in_view: "emitter" from the ship's set, "target" from the
    // target's; either outside the viewed frame -> [] (both dicts share them).
    const std::optional<Vec3> e = to_render(m, ctx, ctx.view, ship_set, emitter_pos);
    const std::optional<Vec3> t = to_render(m, ctx, ctx.view, t_set, beam_end);
    if (!e || !t) return std::nullopt;
    common.emitter = *e;
    common.target = *t;

    // The builder's brightness: rgb scaled, alpha kept.
    BeamOut outer = common;
    outer.color = {oc[0] * brightness, oc[1] * brightness, oc[2] * brightness,
                   oc[3]};
    outer.width = outer_half;
    BeamOut inner = common;
    inner.color = {ic[0] * brightness, ic[1] * brightness, ic[2] * brightness,
                   0.35};
    inner.width = inner_half;
    return Pair{outer, inner};
}

// _ViewMemo.set_of(ship) (view is not None): the ship's set when it is in
// the viewed frame, else None (-1). Uncached: nothing between the two
// builders' calls changes a `_containing_set`.
int64_t set_of(const Mirror& m, const BeamFeedCtx& ctx, int64_t ship) {
    const int64_t pset = containing_set(m, ship);
    if (offset_between(m, ctx, ctx.view, pset)) return pset;
    return -1;
}

// _build_phaser_beam_render_data / _build_tractor_beam_render_data. A ship
// whose own state the mirror cannot answer is one skip; a bank's pair that
// cannot be answered is one skip; everything else is drawn.
void build_one(Mirror& m, const std::vector<int64_t>& ships,
               const BeamFeedCtx& ctx, bool tractor, double brightness,
               double end_width_scale, std::vector<BeamOut>& out,
               BeamSkips& skips) {
    // if memo.view is None: return out
    if (ctx.view == -1) return;
    for (const int64_t ship : ships) {
        std::vector<int64_t> banks;
        int64_t pset = -1;
        const bool ok = guarded(skips, [&] {
            if (ship < 0 || !m.object(ship))
                skip(BeamSkip::ShipRow, "a ship with no Object row");
            const ObjectRow& s = obj(m, ship);
            // hasattr(ship, "GetPhaserSystem"): every ShipClass; anything
            // else reaches a stub, which the mirror cannot answer.
            if (!s.is_ship_class)
                skip(BeamSkip::NotShipClass, "ship is not a ShipClass");
            // sys_ = ship.GetPhaserSystem() / GetTractorBeamSystem()
            const int64_t sys =
                tractor ? s._tractor_beam_system : s._phaser_system;
            if (sys == -1) return;
            // banks = _firing_banks(sys_): the stock path, `_children` in
            // order.
            const std::vector<int64_t> children = sub(m, sys)._children;
            for (const int64_t child : children)
                if (sub(m, child)._firing) banks.push_back(child);
            if (banks.empty()) return;
            // pSet = memo.set_of(ship)
            pset = set_of(m, ctx, ship);
        });
        if (!ok || banks.empty() || pset == -1) continue;
        for (const int64_t bank : banks) {
            std::optional<Pair> pair;
            if (!guarded(skips, [&] {
                    pair = beam_pair(m, ctx, ship, pset, bank, brightness,
                                     end_width_scale);
                }))
                continue;
            if (!pair) continue;
            out.reserve(out.size() + 2);  // the pair is appended whole
            out.push_back((*pair)[0]);
            out.push_back((*pair)[1]);
        }
    }
}

}  // namespace

const char* beam_skip_name(BeamSkip w) {
    switch (w) {
        case BeamSkip::ShipRow: return "ship_row";
        case BeamSkip::NotShipClass: return "not_ship_class";
        case BeamSkip::TargetRow: return "target_row";
        case BeamSkip::ContainingSet: return "containing_set";
        case BeamSkip::Frames: return "frames";
        case BeamSkip::PartStale: return "part_stale";
        case BeamSkip::MountUnknown: return "mount_unknown";
        case BeamSkip::ColourUnset: return "colour_unset";
        case BeamSkip::Shields: return "shields";
        case BeamSkip::Geometry: return "geometry";
        case BeamSkip::Error: return "error";
        case BeamSkip::kCount: break;
    }
    return "?";
}

void build_beam_feed(Mirror& m, const std::vector<int64_t>& ships,
                     const BeamFeedCtx& ctx, std::vector<BeamOut>& phasers,
                     std::vector<BeamOut>& tractors, BeamSkips& skips) {
    phasers.clear();
    tractors.clear();
    skips.fill(0);
    // beam_from_dict's default end_width_scale for a phaser dict: 1.0.
    build_one(m, ships, ctx, /*tractor=*/false, ctx.phaser_brightness, 1.0,
              phasers, skips);
    build_one(m, ships, ctx, /*tractor=*/true, ctx.tractor_brightness,
              ctx.tractor_end_width_scale, tractors, skips);
}

}  // namespace dauntless::combat
