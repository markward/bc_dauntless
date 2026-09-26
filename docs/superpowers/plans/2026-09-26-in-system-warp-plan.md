# In-System Warp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross a star system without the tunnel: a ~10 s Set Course dash to any region of the same system, a Helm "Warp on Heading" dash along the nose, and a silent hand-off into whichever region you enter — all on one `InSystemWarp` that every ship uses.

**Architecture:** A pure planner (`engine/systems/warp_path.py`) turns start/end/obstacles into a straight or curved path in **system coordinates**, plus the speed policy and the body drop-out rule. `ShipClass.InSystemWarp`'s motion step becomes a *warp flight* that follows such a path for any ship (AI Intercept keeps its 100× speed; it gains routing and drop-out). A player dash controller (`engine/appc/dash.py`) drives the player's flight from Set Course (the warp button's engine step forks dash vs tunnel) or from the new Helm entry, locks controls, handles 0 / All Stop, and plays the queued actions. A per-frame hand-off detector (`engine/systems/handoff.py`) moves the player between region sets with `system_position` preserved, deferred to drop-out during a dash. The dust pass stretches into streaks from a pushed dash intensity.

**Tech Stack:** Python engine shim over BC's SDK scripts; one small C++ binding (dust smear cap); pytest + ctest.

**Spec:** `docs/superpowers/specs/2026-09-25-in-system-warp-design.md` (read in full). It depends on `docs/superpowers/specs/2026-09-25-warp-button-chain-and-mission-warps-design.md`, which is built (Warp sends `ET_WARP_BUTTON_PRESSED` through `engine/appc/warp_button.py`; the tunnel uses BC's persistent `"warp"` set; player-scene effects are gated on `warp._is_current_player`).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/system-frames`, branch `feat/system-frames`. Never merge it (Mark: not before the in-system warp stage is flown).
- Every shell: `export DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" DAUNTLESS_SDK_DIR="/Users/mward/Documents/Star Trek Bridge Commander/sdk"`.
- BANNED git: `checkout -- <path>`, `checkout .`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`. Explicit pathspecs only; temporary mutations by `cp` backup/restore + silent `diff`.
- Never launch the game. Never spell `game`/`sdk` as a path segment in code; never capture a path at import. Never edit the SDK directory.
- Single build tree `build/`; never run cmake inside `native/`. `scripts/check_tests.sh` decides what is pre-existing.
- Units are GU (1 GU = 175 m); never `*_m`/`*_mps` names. Rotation: column-vector, right-handed; forward = `GetWorldRotation().GetCol(1)`, up = `GetCol(2)`.
- **Spec tunables, verbatim, each named in one place (`engine/systems/warp_path.py`):** `DASH_TRIP_S = 10.0`; `DASH_MIN_GUPS = 2000.0`; `DASH_MAX_GUPS = 100000.0`; `HEADING_DASH_GUPS = 10000.0`; `DROP_LOOKAHEAD_S = 2.0`; clearance margin = `max(0.25 * body_radius, 2000.0)` GU from the surface; `HANDOFF_MARGIN_GU = 1500.0` (in `engine/systems/handoff.py`). The dust dash smear cap is a native constant tuned live.
- **Spec rules:** A (hand-off keeps pose/velocity; `system_position` identical), A′ (`ET_EXITED_SET`, `ET_ENTERED_SET`, then `ET_EXITED_WARP` with the player as **source**), H (hysteresis), C (system-to-system Set Course, and any warp naming a mission/episode change, keeps the tunnel), D (both dashes run the warp button chain and `warp_gate`), N (NPCs are never handed off).
- Player-scene effects are gated on the ship being the current player (`warp._is_current_player`), as the tunnel's are.

## Review Focus

1. **A dash across Ona 1 → Ona 3 must not fly through the sun** (the straight line passes ~4,350 GU from its centre, inside its radius). Test in Task 1 on the real Ona map and again end-to-end in Task 7.
2. **A heading dash aimed at nothing** (open space, away from every body) runs until 0 / All Stop and never raises; the player stays in its start set the whole way. Test in Task 5.
3. **Pressing Warp on Heading or Set Course during a dash** does nothing (no second dash, no tunnel). Test in Task 4 (Set Course) and Task 5 (heading).
4. **An unmapped set** (QuickBattle, a dev set): Warp on Heading is greyed, Set Course takes the tunnel, the hand-off never runs. Test in Tasks 3 and 5.
5. **An AI Intercept warp inside an unmapped set, or with ships in no set** (the existing unit tests) behaves exactly as today apart from routing/drop-out around real obstacles. Test in Task 2.

---

### Task 1: The path planner, speed policy and drop-out rule (pure)

**Files:**
- Create: `engine/systems/warp_path.py`
- Test: `tests/unit/test_warp_path.py`

**Interfaces:**
- Produces:
  - Constants listed under Global Constraints.
  - `clearance_gu(radius_gu: float) -> float` = `max(0.25 * radius_gu, 2000.0)`.
  - `class Obstacle(NamedTuple): name: str; center: tuple; radius_gu: float`.
  - `class WarpPath`: `length_gu: float`; `point_at(s: float) -> tuple` (s clamped to [0, length]); `tangent_at(s) -> tuple` (unit); `end -> tuple`.
  - `plan_path(start, end, obstacles, end_dir=None) -> WarpPath`. Straight when the segment clears every obstacle's `radius + clearance`; otherwise a smooth curve that clears every obstacle by that amount. When `end_dir` is given, the path's final tangent equals `end_dir` (within 1e-6) — the path approaches the placement along its forward. Deterministic.
  - `set_course_speed(length_gu) -> float` = `clamp(length_gu / DASH_TRIP_S, DASH_MIN_GUPS, DASH_MAX_GUPS)`.
  - `drop_out(pos, direction, speed_gups, obstacles, standoff_of) -> tuple | None`: if an obstacle lies on the ray within `speed_gups * DROP_LOOKAHEAD_S` of its surface, return the drop point on the ray at distance `standoff_of(obstacle)` from its centre (never behind `pos`); else None. `standoff_of` is supplied by the caller (Task 5 gives region-owning bodies their arrival range, others `2 * radius`).

**Design notes for the curve** (implementer chooses the construction; these are the acceptance properties): build the path as a polyline of tangent-continuous pieces — e.g. straight legs joined by circular arcs around each blocking obstacle at radius `r + clearance`, with the end approached along `end_dir` via a final straight of length ≥ `clearance_gu(largest obstacle radius)` (or the remaining distance if shorter). Tangent continuity: adjacent pieces' tangents differ by < 1e-6 at joins. Points are `(x, y, z)` floats in system coordinates; the maps are flat but paths must work in 3D.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_warp_path.py
"""The in-system warp planner (spec §1: Path, Speed policy, Body drop-out)."""
import math
import pytest
from engine.systems import warp_path as wp


def _dist(a, b):
    return math.dist(a, b)


def _min_clearance(path, obstacles, n=4000):
    worst = math.inf
    for i in range(n + 1):
        p = path.point_at(path.length_gu * i / n)
        for o in obstacles:
            worst = min(worst, _dist(p, o.center) - o.radius_gu - wp.clearance_gu(o.radius_gu))
    return worst


def test_clear_line_is_straight():
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [])
    assert p.length_gu == pytest.approx(100000.0)
    assert p.point_at(50000.0) == pytest.approx((50000.0, 0.0, 0.0))


def test_a_body_in_the_way_is_routed_around_with_clearance():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun])
    assert _min_clearance(p, [sun]) >= -1e-6
    assert p.point_at(0.0) == pytest.approx((0.0, 0.0, 0.0))
    assert p.point_at(p.length_gu) == pytest.approx((100000.0, 0.0, 0.0))
    assert p.length_gu > 100000.0


def test_the_path_is_tangent_continuous():
    sun = wp.Obstacle("Sun", (50000.0, 1000.0, 0.0), 10000.0)
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [sun], end_dir=(0.0, 1.0, 0.0))
    prev = p.tangent_at(0.0)
    steps = 20000
    for i in range(1, steps + 1):
        t = p.tangent_at(p.length_gu * i / steps)
        cos = sum(a * b for a, b in zip(prev, t))
        assert cos > math.cos(math.radians(2.0)), f"kink at step {i}"
        prev = t


def test_the_path_arrives_along_the_placement_forward():
    p = wp.plan_path((0, 0, 0), (100000, 0, 0), [], end_dir=(0.0, 1.0, 0.0))
    assert p.tangent_at(p.length_gu) == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
    assert p.point_at(p.length_gu) == pytest.approx((100000.0, 0.0, 0.0))


def test_ona1_to_ona3_routes_around_the_sun():
    """Review Focus 1, on the real regenerated map."""
    from engine.systems import resolve
    m = resolve.map_of("Ona")
    a1 = resolve.anchor_of("Ona1"); a3 = resolve.anchor_of("Ona3")
    obstacles = [wp.Obstacle(b.name, tuple(b.position_gu), b.radius_gu) for b in m.bodies]
    p = wp.plan_path(a1, a3, [o for o in obstacles if o.name == "Ona"])
    assert _min_clearance(p, [o for o in obstacles if o.name == "Ona"]) >= -1e-6


@pytest.mark.parametrize("length,expected", [
    (100000.0, 10000.0), (5000.0, 2000.0), (2_000_000.0, 100000.0)])
def test_set_course_speed(length, expected):
    assert wp.set_course_speed(length) == pytest.approx(expected)


def test_drop_out_stops_at_the_standoff_on_the_line():
    planet = wp.Obstacle("P", (30000.0, 0.0, 0.0), 1800.0)
    d = wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [planet], lambda o: 4000.0)
    assert d == pytest.approx((26000.0, 0.0, 0.0))


def test_drop_out_ignores_bodies_beyond_the_lookahead_and_off_the_line():
    far = wp.Obstacle("Far", (50000.0, 0.0, 0.0), 1800.0)     # surface 48,200 > 20,000
    side = wp.Obstacle("Side", (10000.0, 9000.0, 0.0), 1800.0)
    assert wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [far, side], lambda o: 4000.0) is None


def test_drop_out_never_goes_backwards():
    planet = wp.Obstacle("P", (3000.0, 0.0, 0.0), 1800.0)     # already inside the standoff
    d = wp.drop_out((0, 0, 0), (1, 0, 0), 10000.0, [planet], lambda o: 4000.0)
    assert d == pytest.approx((0.0, 0.0, 0.0))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_warp_path.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `engine/systems/warp_path.py`** — module docstring citing spec §1 and the tunables; pure functions, no engine imports (the Ona test imports `resolve` itself). Keep every tunable a module constant.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_warp_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/warp_path.py tests/unit/test_warp_path.py
git commit -m "feat(systems): in-system warp path planner, speed policy and drop-out rule"
```

---

### Task 2: One warp flight for every ship

**Files:**
- Modify: `engine/appc/ships.py` (`InSystemWarp` ~725, `_end_in_system_warp`, `StopInSystemWarp`, the comment at ~710-715 tying the factor to the Ctrl boost)
- Modify: `engine/appc/ship_motion.py` (`_step_in_system_warp` ~274-338 → the warp flight)
- Create: `engine/appc/warp_flight.py` (the flight object; `ship_motion` delegates to it)
- Test: `tests/unit/test_warp_flight.py` (create); update `tests/unit/test_in_system_warp.py::test_in_system_warp_transit_arrives_at_radius_edge` and `::test_in_system_warp_transit_takes_multiple_ticks` only if routing changes them (they have no obstacles, so they should not); keep `tests/unit/test_in_system_warp_preserves_speed.py`, `tests/unit/test_tier_a_event_emitters.py` (ET_IN_SYSTEM_WARP), `tests/unit/test_player_ai_motion_handoff.py::test_manual_takeover_aborts_in_system_warp_transit`, `tests/integration/test_ai_intercept_smoke.py` green

**Interfaces:**
- Consumes: Task 1's `plan_path`, `drop_out`, `Obstacle`, `clearance_gu`.
- Produces:
  - `engine.appc.warp_flight.WarpFlight` with fields `target` (a ship, a `(point, end_dir)` destination, or None for a heading), `heading` (unit tuple or None), `speed_policy` (`"ai"`, `"set_course"`, `"heading"`), `exit_policy` (`"keep_pre_warp"`, `"rest"`, `"engaged_impulse"`), `engaged_speed` (float), `ended_reason` (None | `"arrived"`, `"body"`, `"stopped"`, `"aborted"`), `drop_point`.
  - `warp_flight.obstacles_for(ship) -> list[Obstacle]` — the system map's bodies (system coordinates) when the ship's set is mapped; its set's own `Planet`/`Sun` objects (set-local == system coordinates for a one-set frame) otherwise; `[]` when the ship is in no set.
  - `warp_flight.to_system(ship, local_xyz) -> tuple` and `to_local(ship, system_xyz) -> tuple` — via the ship's containing-set anchor (`frames`); identity for an unmapped set or no set.
  - `ShipClass.begin_warp_flight(flight) -> None` (engine-only): records `self._insystem_warp_transit = flight`, posts `ET_IN_SYSTEM_WARP` True. `InSystemWarp(target, distance)` builds a `WarpFlight(target=target, speed_policy="ai", exit_policy="keep_pre_warp")` with the drop distance and calls it. `IsDoingInSystemWarp`/`StopInSystemWarp`/`_end_in_system_warp` keep their contract.
  - Each tick (`ship_motion` → `warp_flight.step(ship, dt)`): re-plan toward a moving ship target (AI); advance along the path at the policy speed; face the path tangent (`AlignToVectors(tangent, up)` keeping the ship's up as close as possible); body drop-out for **heading** flights only (a routed path already clears every body; an AI ship target path is routed); on end apply the exit policy and set `ended_reason`.

**AI behaviour change (spec, Mark approved):** an Intercept warp is now routed around bodies and stops short of a body in its line if its target lies beyond it. Speed and exit (pre-warp speed along the final direction) are unchanged.

- [ ] **Step 1: Write the failing tests** — in `tests/unit/test_warp_flight.py`:
  1. A ship in **no set** warping to a target with a clear line: same arrival point and final velocity as today (`(0, 705, 0)`, `v.y == _current_speed`), same per-tick speed `100 × base` — i.e. the existing contract, pinned again through the new code.
  2. A ship in a mapped Ona region (use `tests/helpers/mapped_regions.load_region("Ona","Ona1")` and `load_region("Ona","Ona2")`) intercepting a target placed on the far side of the Ona 1 planet: the flight's positions (converted to system coordinates) keep `>= radius + clearance` from Ona 1's centre every tick, and it arrives within the drop distance of the target.
  3. A ship in an unmapped set with a `Planet` between it and its target: routed around that planet (set-local coordinates).
  4. The ship's forward equals the path tangent (cos > 0.999) at every tick of a curved flight.
  5. `ET_IN_SYSTEM_WARP` posts True once at start and False once at the end (mirror `test_tier_a_event_emitters.py`'s helper).
  6. Review Focus 5: an AI warp between two ships in the same unmapped set with nothing between them is byte-for-byte the old trajectory (compare against a recorded straight-line expectation computed in the test).
- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/unit/test_warp_flight.py -q` → FAIL.
- [ ] **Step 3: Implement** `engine/appc/warp_flight.py`, the `ShipClass` changes, and `ship_motion` delegating to `warp_flight.step`. Remove the Ctrl-boost comment in `ships.py` (the boost itself is removed in Task 5). Frame conversions go through `engine.systems.frames` (`offset_between`, `system_position`, `local_in`) — never raw positions across sets.
- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_warp_flight.py tests/unit/test_in_system_warp.py tests/unit/test_in_system_warp_preserves_speed.py tests/unit/test_tier_a_event_emitters.py tests/unit/test_player_ai_motion_handoff.py tests/integration/test_ai_intercept_smoke.py tests/integration/test_intercept_polish_smoke.py -q` → PASS. If an existing test's straight-line expectation changes, stop and report which and why (it should not: none has an obstacle).
- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp_flight.py engine/appc/ship_motion.py engine/appc/ships.py tests/unit/test_warp_flight.py
git commit -m "feat(warp): one in-system warp flight for every ship — frame-aware, routed"
```

---

### Task 3: The player hand-off between regions

**Files:**
- Create: `engine/systems/handoff.py`
- Modify: `engine/host_loop.py` (call `handoff.tick(player)` after `collisions.tick_collisions(...)` and before `_reconcile_scene(...)` in the unfrozen branch)
- Modify: `tests/host/test_scene_reconcile_ordering.py` (add `"_handoff.tick("` — or the exact call spelling you use — to `_SIM_CALLS`)
- Test: `tests/unit/test_handoff.py` (create)

**Interfaces:**
- Consumes: `engine.systems.frames` (`offset_between`, `system_position`), `engine.systems.resolve` (`for_set`, `regions_of`, `system_of`), `engine.systems.region_hooks.is_mapped`, `warp._clear_all_targets`.
- Produces:
  - `HANDOFF_MARGIN_GU = 1500.0`.
  - `handoff.region_at(player) -> SetClass | None` — the loaded, mapped region set of the player's system whose sphere (`anchor`, `radius_gu`) contains the player's system position (nearest anchor wins if two contain it).
  - `handoff.tick(player) -> SetClass | None` — hands off and returns the new set, else None. No-op when: player None; player's set unmapped; player is dashing (`player.IsDoingInSystemWarp()` and the flight is a player dash — defer); player is inside its current set's radius + margin; no other region contains it.
  - `handoff.hand_off(player, dest) -> None` — the move itself (used by Task 4 at drop-out): rebase `local_dest = local_src + offset_between(dest, src)`; `src.RemoveObjectFromSet(name)`; `dest.AddObjectToSet(player, name)`; `SetTranslateXYZ(*local_dest)`; rotation and velocity untouched; `warp._clear_all_targets(player)`; then post `ET_EXITED_WARP` (TGEvent, source = player, destination = player).
  - `handoff.post_exited_warp(player) -> None` (Task 4 reuses it for a drop-out without a set change).

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_handoff.py` using `load_region("Ona","Ona1")`, `("Ona","Ona2")`:
  1. `hand_off` keeps `system_position` identical (to 1e-6), rotation and velocity identical, and the player is in the destination set only.
  2. Event order recorded by broadcast handlers: `ET_EXITED_SET`, `ET_ENTERED_SET`, `ET_EXITED_WARP`; `ET_EXITED_WARP`'s `GetSource()` is the player.
  3. `tick` hands off when the player's system position is placed inside Ona 2's sphere (and outside Ona 1's radius + margin); returns the Ona 2 set.
  4. Rule H: a player just outside Ona 1's radius but within radius + margin, and inside nothing else → no hand-off; circling Ona 2's sphere edge (positions alternating ±10 GU across its radius) after a hand-off into Ona 2 never hands back.
  5. Deferred during a dash: with a player flight active (`begin_warp_flight` with `speed_policy="heading"`), `tick` does nothing inside Ona 2's sphere.
  6. Rule N: an NPC inside Ona 2's sphere is never moved (`tick` only takes the player; call it with an NPC and assert None / no move).
  7. Review Focus 4: a player in an unmapped set → `tick` returns None and posts nothing.
  8. The target is cleared on hand-off.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `handoff.py` and the host call; add the call name to `_SIM_CALLS` in the ordering test.
- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_handoff.py tests/host/test_scene_reconcile_ordering.py tests/integration/test_sky_round_trip.py -q` → PASS.
- [ ] **Step 5: Commit**

```bash
git add engine/systems/handoff.py engine/host_loop.py tests/unit/test_handoff.py tests/host/test_scene_reconcile_ordering.py
git commit -m "feat(systems): the player hands off between regions with system_position kept"
```

---

### Task 4: The Set Course dash

**Files:**
- Create: `engine/appc/dash.py` (the player dash controller)
- Modify: `engine/appc/warp.py` (`execute_warp`: fork dash vs tunnel)
- Modify: `engine/host_loop.py` (`_PlayerControl.apply`: early return while the player dashes, except the `full_stop` key → `dash.drop_out(player, "stopped")`; call `dash.tick(player, dt)` once per frame in the unfrozen branch before `_handoff.tick`)
- Create: `engine/appc/dash_helm.py` (per-entry Helm disable/enable during a dash; the `ET_ALL_STOP` instance handler)
- Test: `tests/unit/test_dash_set_course.py` (create)

**Interfaces:**
- Consumes: Tasks 1-3; `warp_button.is_warp_active`; `warp._set_name_from_module`; `resolve`; `frames`.
- Produces:
  - `dash.is_same_system_dash(player, dest_module, mission, episode) -> bool` — True iff the player's set is a mapped region, the destination set name's system (`resolve.system_of`) equals the player's system, the destination set exists, and `mission`/`episode` are empty.
  - `dash.start_set_course(player, dest_set, placement_name, queues) -> None` — reads the destination `Waypoint` (`dest_set.GetObject(placement_name)`, falling back to `"Player Start"`), converts its position and forward (`GetWorldRotation().GetCol(1)`) to system coordinates, plans with `obstacles_for(player)` and `end_dir = forward`, then: **align** (turn the ship onto the path's first tangent over `warp._align_duration(player, first_tangent)` seconds — reuse it), **engage** (flash + "Enter Warp" + weapon loops silenced + `WES_WARPING` via `warp_state.set_state` + `begin_warp_flight(WarpFlight(target=(end, forward), speed_policy="set_course", exit_policy="rest"))`), fly, **drop out**.
  - `dash.drop_out(player, reason) -> None` — ends the flight; applies the exit; if the player's system position is inside a region other than its set → `handoff.hand_off(player, region)` (which posts `ET_EXITED_WARP`), else `handoff.post_exited_warp(player)`; for an arrival: snap to the waypoint's exact local position and rotation in the destination set, velocity zero; flash + "Exit Warp"; `WES_NOT_WARPING`; re-enable the Helm entries; play the "after" queue.
  - `dash.is_dashing(player) -> bool`.
  - `dash.tick(player, dt) -> None` — runs the align phase and detects a flight that ended (the flight's `ended_reason`) to run `drop_out` once.
  - `dash_helm.sync(player) -> None` (called every tick like `weapon_tactical_commands.sync`): registers once per Helm menu an `ET_ALL_STOP` instance handler (`engine.appc.dash_helm._on_all_stop`, runs first by LIFO, calls `dash.drop_out(player, "stopped")` if dashing, then `CallNextHandler`); while dashing, `SetDisabled()` on Warp, Set Course, Orbit Planet, Intercept, Dock and (Task 5) Warp on Heading — **never the Helm menu itself** — and restores exactly the entries it disabled on drop-out.

**Queued actions:** the dash plays the button's queues at its matching points (spec §2): "before" at engage, "before_during" then "during" then "after_during" sequentially starting at engage (no hold), "after" at drop-out.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_dash_set_course.py` (Ona1/Ona2 via `load_region`; player registered as current player; `engine.appc.warp_button.press` with the course set through `set_player_destination` + `warp.set_course_placement`; tick with `engine.core.loop.GameLoop` or the helper `tests/helpers/headless_mission.py` uses, plus `dash.tick`):
  1. Ona 1 → Ona 2 by Set Course: no `"warp"`-set entry happens (the tunnel is not used); flash-to-flash time is 10 s ± one tick; at the end the player is in Ona 2 at its "Player Start" local position and rotation (1e-6), velocity zero; events `ET_EXITED_SET`(Ona1), `ET_ENTERED_SET`(Ona2), `ET_EXITED_WARP`.
  2. During the flight: `IsDoingInSystemWarp()` is 1, warp state is `WES_WARPING`, the Helm entries listed are disabled and the Helm menu itself is enabled; after: all restored.
  3. Rule C: a course to another system, or one whose button names a mission, takes the tunnel (the player passes through `"warp"`).
  4. `full_stop` key during the flight (drive `_PlayerControl.apply` with a fake input whose `key_pressed(full_stop)` is True) → drop-out at rest where it is, `ET_EXITED_WARP` posted, no hand-off if outside every other sphere.
  5. All Stop: dispatch `ET_ALL_STOP` to the Helm menu during the flight → same drop-out, and the SDK `AllStop` still runs (the handler passes the event on).
  6. Review Focus 3: pressing Warp again during the flight starts nothing.
  7. Steering keys and impulse 1-9 during the flight change nothing (`_PlayerControl.apply` with those keys; position/rotation follow the flight only).
  8. Queues: actions queued on the button play at engage (before), during flight (during), and after drop-out (after).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Keep the fork in `execute_warp` small: `if dash.is_same_system_dash(...): dash.start_set_course(...); return`. `_PlayerControl.apply`'s early return must happen before any key read except `full_stop`.
- [ ] **Step 4: Run** — the new file, `tests/unit/test_warp_button_chain.py`, `tests/unit/test_warp_menu_side_effects.py`, `tests/host/test_player_control.py`, `tests/integration/test_campaign_warp_transitions.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add engine/appc/dash.py engine/appc/dash_helm.py engine/appc/warp.py engine/host_loop.py tests/unit/test_dash_set_course.py
git commit -m "feat(warp): the Set Course dash within a system"
```

---

### Task 5: Warp on Heading; body drop-out for the player; Ctrl+W removed

**Files:**
- Modify: `engine/appc/dash.py` (`start_heading`)
- Modify: `engine/appc/dash_helm.py` (the "Warp on Heading" Helm entry)
- Modify: `engine/appc/warp_button.py` (`press_heading(button)`; the engine step dispatches a heading press to `dash.start_heading`)
- Modify: `engine/appc/characters.py` (`STMenu.InsertChildAfter(child, after)` — engine-only helper; SDK has no insert)
- Modify: `engine/host_loop.py` (remove `WARP_BOOST_FACTOR`, `_warp_boost`, the `GetTargetSpeed` boost term and the Ctrl+W toggle; fix the "Ctrl+I" prose)
- Modify: `tests/host/test_player_control.py` (replace `test_ctrl_w_toggles_warp_boost` / `test_ctrl_i_no_longer_toggles_warp_boost` with one test: Ctrl+W changes nothing)
- Test: `tests/unit/test_dash_heading.py` (create)

**Interfaces:**
- Produces:
  - `WARP_ON_HEADING_LABEL = "Warp on Heading"` (project-authored; BC has no string) in `dash_helm`.
  - `dash_helm.sync` adds the entry once per Helm menu, immediately after the `STWarpButton` (via `InsertChildAfter`), as an `STButton` whose event (type from `App.Game_GetNextEventType()`, like `engine/appc/weapon_tactical_commands.py`) reaches `dash_helm._on_heading(menu, event)` → `warp_button.press_heading(App.SortedRegionMenu_GetWarpButton())`. The entry is disabled (greyed) when the player's set is unmapped (Review Focus 4) and while dashing.
  - `warp_button.press_heading(button)`: saves the button's destination, mission, episode (and does **not** touch its queues), clears them, sets a module flag `_heading_press = True`, `press(button)`, then restores the saved values and clears the flag in `finally`. The engine step: when `_heading_press` is set → gate (`warp_gate`) then `dash.start_heading(player, button.take_queues())` instead of the destination guard / `execute_warp`.
  - `dash.start_heading(player, queues)`: engage immediately (no align) along the nose at `HEADING_DASH_GUPS`, `WarpFlight(heading=forward, speed_policy="heading", exit_policy="engaged_impulse", engaged_speed=player's current impulse speed)`; the flight's body drop-out uses `standoff_of(obstacle)` = the distance from that body's centre to its owning region's "Player Start" (system coordinates) when it owns a region, else `2 * radius` (one radius above the surface).
  - Exit: body drop-out → the engaged impulse speed along the heading; 0 / All Stop → rest.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_dash_heading.py`:
  1. The Helm menu gains "Warp on Heading" right after Warp; it is greyed in an unmapped set.
  2. A heading dash from Ona 1 aimed at Ona 2's centre drops out on the line at Ona 2's arrival range from its centre, inside Ona 2's sphere, is handed off to Ona 2 (`ET_EXITED_SET`, `ET_ENTERED_SET`, `ET_EXITED_WARP`), and moves on at the engaged impulse speed along the heading.
  3. A heading dash at the sun (no region) stops one radius above its surface.
  4. Review Focus 2: a heading dash into open space runs (tick 30 s) without raising, stays in Ona 1's set, and ends at rest on 0.
  5. The mission chain runs with no destination: a test handler registered on the button records `button.GetDestination()` during the heading press → `None`/falsy; after the press the button's plotted course, mission and episode are restored exactly.
  6. A swallowing handler stops a heading dash; a gate refusal stops it (engines off) with the deny line.
  7. Review Focus 3: Warp on Heading during a dash does nothing.
  8. Ctrl+W no longer changes speed (in `tests/host/test_player_control.py`).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — the new file, `tests/unit/test_dash_set_course.py`, `tests/unit/test_warp_button_chain.py`, `tests/host/test_player_control.py`, `tests/unit/test_crew_menu_panel.py` → PASS.
- [ ] **Step 5: Commit**

```bash
git add engine/appc/dash.py engine/appc/dash_helm.py engine/appc/warp_button.py engine/appc/characters.py engine/host_loop.py tests/unit/test_dash_heading.py tests/host/test_player_control.py
git commit -m "feat(warp): Warp on Heading from the Helm, with body drop-out; Ctrl+W boost removed"
```

---

### Task 6: What you see and hear

**Files:**
- Modify: `native/src/renderer/include/renderer/dust_pass.h` (`kDashSmearScale` constant), `native/src/renderer/dust_pass.cc` (cap = `kMaxSmearLength * (1 + dash * (kDashSmearScale - 1))`), `native/src/renderer/frame.cc` (a `dauntless_dash_vfx` float next to `dauntless_warp_vfx`), `native/src/host/host_bindings.cc` (`set_dash_intensity(float)`, following `set_warp_streak_intensity` at ~3991)
- Modify: `engine/renderer.py` (`set_dash_intensity` wrapper + `_REQUIRED_BINDINGS` entry — see `tests/unit/test_renderer_binding_manifest.py`)
- Create: `engine/dash_vfx.py` (the dash clock: engage flash, hold, drop-out flash; nacelle glow drive)
- Modify: `engine/host_loop.py` (push `set_dash_intensity`; combine flash as `max(warp flash, dash flash)` so neither zeroes the other; `_warp_glow_envelope(ship)` returns the dash glow while the player dashes)
- Modify: `engine/appc/dash.py` (drive `dash_vfx` at engage/drop-out; "Enter Warp"/"Exit Warp" through `App.g_kSoundManager.PlaySound`; `warp._silence_ship_weapons(player)` at engage)
- Test: `tests/unit/test_dash_vfx.py` (create); a ctest in the existing dust-pass test file asserting the cap scales with the dash intensity (read `native/tests/` for the dust pass's test and follow it)

**Interfaces:**
- Produces: `dash_vfx.get()` singleton with `engage(now)`, `drop_out(now)`, `tick(now)`, `flash_intensity() -> float` (1 → 0 over 0.4 s after engage and after drop-out), `dash_intensity() -> float` (0 → 1 over 0.5 s after engage, 1 while dashing, 1 → 0 over 0.5 s after drop-out), `engine_glow() -> (drive, burst)` (drive 1 while dashing, burst 0).
- Rebuild: `cmake --build build -j` (never inside `native/`).

- [ ] **Step 1: Write the failing tests** — the `dash_vfx` envelopes above (exact values at 0, 0.2, 0.4, 0.5 s); the host combines flashes with `max` (a unit test on the small function you extract for it); the renderer manifest lists `set_dash_intensity`; the ctest for the smear cap.
- [ ] **Step 2: Run to verify they fail** (pytest + `ctest --test-dir build -R <dust test>`).
- [ ] **Step 3: Implement**, rebuild, and set `kDashSmearScale` to a starting value of 400 (the smear at 10,000 GU/s would otherwise be capped at 1.5 GU; 400 × 1.5 = 600 GU streaks) with a comment that it is tuned live.
- [ ] **Step 4: Run** — the new tests, `tests/unit/test_renderer_binding_manifest.py`, the dust ctest, and `uv run pytest tests -q -k "warp or dust or glow"` → PASS.
- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/dust_pass.h native/src/renderer/dust_pass.cc native/src/renderer/frame.cc native/src/host/host_bindings.cc engine/renderer.py engine/dash_vfx.py engine/host_loop.py engine/appc/dash.py tests/unit/test_dash_vfx.py <the ctest file>
git commit -m "feat(render): dash flash, nacelle glow and dust streaks"
```

---

### Task 7: End to end, docs, live guide

**Files:**
- Test: `tests/integration/test_in_system_warp_e2e.py` (create)
- Modify: `CLAUDE.md` (one reference-table row: in-system warp — `engine/systems/warp_path.py`, `engine/appc/warp_flight.py`, `engine/appc/dash.py`, `engine/systems/handoff.py`, the spec; "⚠️ not live-verified")
- Modify: `docs/superpowers/specs/2026-09-24-system-frames-design.md` (§7 status line: built)

- [ ] **Step 1: Write the end-to-end tests** — headless, through `tests/helpers/headless_mission.py`'s loader with `engine.dev_missions.system_preview` (Ona 1, player at "Player Start"); press Warp via `warp_button.press` exactly as the Helm does:
  1. Ona 1 → Set Course Ona 2 → Warp → arrive in Ona 2 at its "Player Start", at rest, same ship, draw list (`host_loop` celestial draw list for the viewed set — read `tests/integration/test_sky_round_trip.py`) is the Ona system's bodies.
  2. Ona 2 → Set Course Ona 1 → back.
  3. Ona 1 → Ona 3: the sampled path (every tick's system position) keeps ≥ `radius + clearance_gu(radius)` from the sun's centre (Review Focus 1); arrival at Ona 3.
  4. Warp on Heading at Ona 2 from Ona 1 → handed off into Ona 2 at its arrival range, moving at the engaged impulse speed.
  5. The system-to-system path still tunnels: from Ona 1, Set Course to another system (pick any mapped system reachable in the preview's Set Course menu, or build the course directly) passes through `"warp"`.
  6. `no_logged_failures` (from `tests/helpers/headless_mission.py`) on every case.
- [ ] **Step 2: Run** — `uv run pytest tests/integration/test_in_system_warp_e2e.py -q` → PASS. Then `scripts/check_tests.sh` → `OK — no new failures.`
- [ ] **Step 3: Docs** — the CLAUDE.md row and the spec status line.
- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_in_system_warp_e2e.py CLAUDE.md docs/superpowers/specs/2026-09-24-system-frames-design.md
git commit -m "test(warp): in-system warp end to end; docs"
```

## Live pass (Mark) — together with the warp-button-chain pass

`--developer` → Load Mission → Developer → **System Preview** (Ona 1):
1. Helm → Set Course → Ona 2 → Warp. Expect: turn onto course, flash, ~10 s through real space with dust streaks and Ona 2 growing, flash, parked at Ona 2's usual framing. "Entering Ona 2" banner.
2. Set Course → Ona 3 → Warp. Expect the path to bend around the sun and pass it close.
3. Point at Ona 1 (or any planet), Helm → **Warp on Heading**. Expect a drop-out near it at its usual framing range, still moving at your impulse speed.
4. Warp on Heading into empty space, then press **0**; then again and use **All Stop**. Both stop you dead with a flash.
5. Try Warp on Heading in QuickBattle: greyed.
6. Tune by eye: dust streak length (`kDashSmearScale`), flash strength.
