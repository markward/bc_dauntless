# Native transform ownership, with threaded per-ship motion

**Date:** 2026-09-05
**Status:** design approved, not yet implemented
**Branch:** `feat/native-transform-ownership`

Move authoritative ownership of every object's position and rotation out of
Python and into a contiguous C++ array, then integrate ship motion across
multiple cores over that array.

## Why

The engine is effectively single-threaded. Nothing in `native/src` or `engine/`
creates a thread; the only concurrency in the process belongs to libraries we
embed (CEF's helper processes, OpenAL Soft's mixer thread). The whole game —
input, SDK logic, AI, motion, render-data build, every GL pass — runs
sequentially in one Python loop on the main thread under one GIL.

The motivation for this project is **correct ownership**, not a frame-time
target. That distinction matters, because the frame-time case on its own is
weak and the measured numbers say so.

### What the profiler actually says

From `docs/engine/frame-profiler.md`, 17-ship combat (`combat_stress`,
`DAUNTLESS_COMBAT_AVOID=0`):

```
ui_panels      ~17.0     sim            ~70        r.frame  ~15-24
render_prep    ~12.0       sim.combat   ~25-33
                           sim.gameloop ~35
                             gl.ai         ~10-11
                             gl.subsystems  ~7.6
                             gl.motion      ~5.6-6.1
                             gl.proximity   ~1.6
```

`gl.motion` — the phase threading would parallelise — is the **fourth**-largest
child of `sim`. Making it entirely free saves ~6 ms of a ~120 ms frame. That is
the Amdahl ceiling on the threading half, before any marshalling cost. Nobody
should expect this project to transform the frame rate.

### The finding that reframed it

`TGMatrix3` (`engine/appc/math.py:161`) is a list-of-lists with no `__slots__` —
roughly six allocations per instance (object + `__dict__` + outer list + three
rows). `ObjectClass.GetWorldRotation` (`engine/appc/objects.py:355`) constructs
one on **every call**:

```python
def GetWorldRotation(self) -> TGMatrix3:
    result = TGMatrix3()
    result._m = [row[:] for row in self._rotation._m]
    return result
```

There are **70 `GetWorldRotation()` and 96 `GetWorldLocation()` call sites**
across `engine/`, many of them per-ship, per-frame. That cost is smeared across
`gl.motion`, `gl.ai`, `render_prep` and `ui_panels` at once, which is exactly
why no single phase looks damning and why it never surfaced as a target.

The real prize is therefore **half 1**, not half 2: stop copying transforms in
Python and stop marshalling them across the language boundary for the renderer.
`render_prep` (12 ms combat, 15.8 ms bridge) is the largest single line item
this touches, and it is won without any threading at all.

## Goals

- One authoritative store for every object's position and rotation, owned by C++.
- Byte-identical behaviour from the SDK's point of view.
- Per-ship motion integration parallelised across cores.
- Cheaper transform reads throughout the engine as a consequence.

## Non-goals

- Rewriting AI, combat, or subsystem simulation.
- A scene-graph / parent-child transform hierarchy (see below — there isn't one).
- Any change to `sdk/Build/scripts/`.

## Scope

**All of `ObjectClass`.** The slot is allocated in `ObjectClass.__init__`, so
ships, torpedoes, characters, planets, backdrops, lights, placement objects and
proximity checks all have one. Static objects simply never write after
placement.

The alternative — ships and torpedoes only — was rejected because `Torpedo`
derives directly from `ObjectClass` rather than `PhysicsObjectClass`, so there
is no inheritance cut that captures "the things that move". Any narrower scope
leaves `ObjectClass` with two storage paths and a branch in every accessor.

### Two facts that make this tractable

**There is no transform hierarchy to port.** `GetWorldLocation()` is identical
to `GetTranslate()` and `GetWorldRotation()` to `GetRotation()` — world equals
local, flat, no parent chain (`engine/appc/objects.py:301-305`). Subsystem world
positions are computed on demand from ship location + R·local, never stored.
The migration surface is exactly two fields.

**The SDK touches neither private field.** `._m`, `._position` and `._rotation`
have **zero** hits across all 1228 files in `sdk/Build/scripts/`. Every
private-field change stays inside our own code:

| symbol | sites | files |
|---|---|---|
| `._m` | 63 (40 in `engine/`) | 5 engine files, concentrated in `math.py` + `objects.py` |
| `._position` / `._rotation` outside `objects.py` | 29 | 6 |

## Approach

Three approaches were considered. An uncomfortable truth sits under all of
them: *per-call* read-through is not automatically faster, because a pybind11
crossing costs roughly what a Python attribute read plus a `TGPoint3`
construction costs today. The win comes from **bulk** transfer and from killing
the `TGMatrix3` allocation — not from the migration by itself.

**A. Native store, read-through accessors, bulk fast paths — CHOSEN.**
Single source of truth. Accessors preserve today's copy semantics exactly, so
the SDK needs no audit. Hot paths convert to bulk APIs that never build a Python
object. Requires flattening `TGMatrix3` or the read path gets *slower*.

**B. Native store with a Python mirror — rejected.** Faster reads (no crossings
on the SDK path), but two copies of the truth. Every missed write-through is a
silent desync that renders a ship where it isn't, and no existing test would
catch it. This is the debt the project exists to pay down.

**C. Python store with a native mirror for render and integrate — rejected.**
Smallest blast radius, still delivers threading and most of the `render_prep`
win, but it is not native ownership. It is today's architecture with a faster
path bolted on.

## Section 1 — Ownership and slot lifecycle

**Native store.** A `TransformStore` in `native/src/` holding a contiguous
vector of POD `Transform { double pos[3]; double rot[9]; }`, index-addressed.
**Double, not float** (amended 2026-09-05 during Task 3): Python's `float` IS a
double, so a 32-bit store truncates on every write, makes the two backends
numerically disagree, and would drift motion integration away from today's
behaviour once every object routes through it. The Goal of byte-identical
SDK-visible behaviour outranks the storage saving. The renderer converts to
32-bit at the GL boundary.
Slots come from a free list. Each slot carries a **generation counter**, so a
stale handle from a freed object fails loudly instead of silently reading
whatever object recycled its index. Growth is by doubling; indices stay valid
across a realloc, which is why Python receives an index and never a pointer.

**Python handle.** `ObjectClass.__init__` allocates a slot and stores
`self._xform = (index, generation)`. Nothing else about the object changes.

**Release via `weakref.finalize`, not `__del__`.** `ObjectClass` instances sit
in reference cycles — they are event handlers and the event manager holds refs
back — and `__del__` on cycle members is unreliable. A
`weakref.finalize(self, _free_slot, index, generation)` registered at
construction is cycle-safe.

**Correction (2026-09-05, found during Task 4): release is NOT deterministic in
production.** `engine/core/ids.py:6` holds `_registry` as a plain strong dict and
`TGObject.__init__` writes `_registry[self._obj_id] = self` (`:186`), so every
object is immortal unless something calls `ids.unregister()`. The finalizer
therefore fires only once that strong reference is gone, which for most objects
is never. This **pre-dates this project** — objects were already immortal and
already carried their transforms with them — so the store adds bytes to an
existing leak rather than creating a new one. The lifecycle tests unregister
explicitly and say so; they do not demonstrate production-time release. Fixing
the registry's ownership is a separate piece of work.

Slot lifetime therefore tracks the *Python object's* lifetime, not set
membership. That is correct: `RemoveObjectFromSet` / `DeleteObjectFromSet`
(`engine/appc/sets.py:242-258`) merely pop from a dict while the object may
still be referenced elsewhere.

**Two backends, one contract.** `engine/appc/transform_store.py` defines the
interface and selects a backend once at import: the native store when
`_dauntless_host` is present, a pure-Python store (flat list of 12 floats per
slot) when it is not. `engine/host_io.py:32-34` treats `_h is None` as a normal
headless state and the suite must keep passing there. The two backends are never
live simultaneously, so this is one contract with two implementations, not two
sources of truth — and a shared conformance suite is what stops them drifting.

**Why not reuse the renderer's instance ids:** those exist only for things that
draw. `ProximityCheck`, `PlacementObject` and friends have transforms and no
geometry, and the point of scoping to all of `ObjectClass` was to avoid an
"is this one native?" branch.

## Section 2 — The read/write path

**Prerequisite: `TGMatrix3` becomes flat.** Nine floats in `__slots__`, not a
list-of-lists with a `__dict__`. Drops an instance from ~6 allocations to 1 and
is a real chunk of the win on its own. Converts the 63 `._m` sites — mechanical,
mostly in two files.

No compatibility `_m` property is left behind. It would hand back a freshly
built list-of-lists and silently reintroduce the allocation we are removing, in
the places we could no longer see.

**Accessors read through; semantics unchanged.** `GetTranslate`,
`GetWorldLocation`, `GetRotation` and `GetWorldRotation` build a fresh
`TGPoint3` / `TGMatrix3` from the store's floats. Callers may still mutate what
they receive; the mutation still does not write back. Identical to today.

The `GetWorldForwardTG` / up / right helpers (`engine/appc/objects.py:497-520`)
currently read `self._rotation` directly and are hammered by AI and motion. They
become single-column store reads that never build a matrix at all.

**Writes go through immediately.** `SetTranslateXYZ`, `SetTranslate` and
`SetMatrixRotation` write the store on the spot. No deferred or batched writes —
that is what would open a desync window.

**⚠️ One real behaviour change.** Today `engine/appc/objects.py:348` is
`self._rotation = matrix` — it stores the caller's matrix **by reference**, so
anything mutating that matrix afterwards silently re-orients the object. Writing
into the store copies instead, breaking the aliasing. This is expected to be
unintentional everywhere, but that must be *verified*, not assumed: grep the
callers during Phase 2 and flag any that depend on it. It would surface live as
an object rotating wrongly, so it is on the Phase 2 checkpoint list.

**Bulk paths are where the win lives**, in descending value:

1. **`render_prep` stops marshalling.** ~20 sites in the host loop currently
   pull each object's transform into Python to hand back to the renderer
   (`engine/host_loop.py:4025-4043` and siblings). With the store native, the
   renderer reads it directly in C++ and transforms never enter Python. Biggest
   single prize, and a half-1 win.
2. **The integrator** works on store indices, setting up half 2.
3. **Per-ship sweeps** — collision broadphase, contact index, target list — take
   one bulk read instead of N accessor calls.

Everything else keeps the ordinary accessors. Convert what is measurably hot,
not all 166 sites.

## Section 3 — Threading

**The threading is the easy part; porting the motion math is the work.**
`_step_ship_motion` (`engine/appc/ship_motion.py:126`) is 324 lines of
SDK-faithful behaviour: impulse derating, inertial drift when the pods are out,
the rate-limited asymptote, non-braking speed caps, residual angular momentum,
in-system warp transit. Half 2 means reimplementing that in C++.

**Narrow what gets ported.** Only the integration math moves — ramps, caps,
`_asymptote_step`, `_integrate_rotation`. Everything requiring the
subsystem / damage / power graph stays in Python and arrives pre-computed in the
per-ship record: `impulse_online_fraction(ies)` and `_effective_motion(ship)`
are resolved to numbers before the window opens.

The C++ side therefore sees a flat POD — position, rotation, current speed,
setpoint (speed, direction, frame flag), effective max speed / accel / turn
rates, drift velocity and flag, immobile flag, warp target point and drop
distance, and the never-written-setpoint flag — and does pure arithmetic on it.
Small, numeric, differentially testable.

**No locks, because the GIL is the mutex.** Per tick: Python packs the records
(sequential, reads whatever it likes) → `py::gil_scoped_release` → worker
threads integrate disjoint slots → GIL reacquired → Python continues. No Python
code can run inside that window, so nothing can observe or race a half-updated
store. Same pattern as the existing `py::gil_scoped_acquire` sites at
`native/src/host/host_bindings.cc:3754`.

**Resolve the cross-ship read at pack time.** The single cross-entry read is
`_step_in_system_warp` reading its target's location
(`engine/appc/ship_motion.py:264`). Resolving it to a *point value* during pack
means no worker ever reads another worker's slot, which removes the need for
double-buffering and the subtle behaviour change that would come with it. The
value freezes to pack-time rather than mid-tick — identical to what
double-buffering would have given.

**Determinism is preserved.** Each ship's integration depends only on its own
record, so results do not vary with thread count or scheduling order. That
matters more here than in most engines, because BC-faithfulness claims are
checked by replaying scenarios.

**A threshold, because 17 ships may not be worth threading.** Below some N, pool
dispatch costs more than the work; the integrator runs inline. Land the pool
with a tunable threshold and *measure* the crossover on `combat_stress` rather
than guessing. Be clear-eyed: at BC's typical ship counts the parallel win may
round to nothing. The value of half 2 is headroom for larger battles plus the
pattern being established. The `render_prep` win from half 1 is the one to bank.

**One persistent pool**, created at boot, not per frame.

## Section 4 — Phasing and live checkpoints

Six phases, each independently committable. Every gate is `scripts/check_tests.sh`
(both suites, diffed against `tests/known_failures.txt`) plus — where marked —
live verification, because no green test can see an object drawn in the wrong
place.

| # | Phase | Gate |
|---|---|---|
| 0 | `TGMatrix3` goes flat. Pure Python, 63 mechanical sites. Lands the allocation win alone and de-risks everything downstream. | tests + profiler capture |
| 1 | `TransformStore`, both backends, conformance suite. No callers switched; behaviour unchanged by construction. | tests |
| 2 | `ObjectClass` switches to store-backed storage; accessors read/write through; 29 private-field sites convert. **Highest-risk phase.** Where the `SetMatrixRotation` aliasing question lands. | tests + **live** |
| 3 | Renderer reads the store directly; `render_prep` stops marshalling. Biggest measured prize, no threading involved. | tests + **live** + capture |
| 4 | Port integration math to C++, still single-threaded, behind a flag so the Python path stays runnable. Differentially tested against `_step_ship_motion`. | tests + **live flight test** |
| 5 | Thread it. Pool, threshold, crossover measurement. | tests + **live** + capture |

**Baseline before Phase 0.** A profiler capture to compare against:

```
DAUNTLESS_MISSION=engine.dev_missions.combat_stress \
DAUNTLESS_COMBAT_SHIPS=16 DAUNTLESS_COMBAT_AVOID=0
```

`AVOID=0` matches the documented figures, which were taken before that mission's
avoidance default flipped. CPU columns only — the GPU column is dead on this Mac.

**Build discipline.** Each worktree needs its own `build/`; a full configure
pulls CEF (~302 MB), OpenAL Soft and pybind11. A branch switch or merge desyncs
`build/`, so whichever tree is used for live testing must be rebuilt first — a
live check on a stale binary tells you nothing.

### Worktree prerequisites (found while setting this branch up)

Two things block a fresh worktree from running the suite at all. Both are
one-time per worktree, and the first is arguably a bug:

1. **`engine/dev_mode.py:10` imports `_dauntless_host` unguarded**, unlike
   `engine/host_io.py:32-34` which guards it and treats `_h is None` as a normal
   headless state. Because `tests/conftest.py` → `paths.resolve()` →
   `engine/settings_store.py` → `dev_mode`, the *entire* pytest suite requires a
   built native extension; without one, collection dies before a single test
   runs. This is what makes a native build mandatory rather than optional in a
   worktree. Guarding it the way `host_io` does would let Phase 0 (pure Python)
   be developed and tested with no C++ build at all. Not in scope here, but
   worth fixing separately.
2. **`settings.json` lives at `PROJECT_ROOT`** (`engine/settings_store.py:43`),
   so it is per-worktree. A new worktree has no configured BC roots and
   `paths.resolve()` fails loudly with instructions — correct behaviour by the
   path-resolution design, but it means each worktree needs its own
   `settings.json` `[paths]` block pointing at the shared install.

Baseline established for this branch at `597c3fb3`: `1 failed, 8100 passed,
6 skipped, 1 xfailed`, zero errors. The single failure is the only pytest entry
in `tests/known_failures.txt`. `ctest` was not run — no C++ build in this
worktree yet.

## Section 5 — Testing

**The conformance suite is the spine.** One parametrized test class runs the
identical contract against both backends. Two implementations that never run
simultaneously are only safe if something proves they agree.

**Differential testing carries Phase 4.** `_step_ship_motion` becomes the
reference oracle: randomized ship states — setpoints, damaged pods, drift,
mid-warp transit, immobile, the never-written-setpoint case — with the C++ port
asserted equal within float tolerance. This is why Phase 4 keeps the Python path
behind a flag rather than deleting it.

**Determinism as a race detector.** Integrate the same input with 1 thread and
with 8; assert bit-identical output. Races in the integrate window surface as
divergence, and it is machine-checkable in ctest — the alternative (noticing an
intermittent visual glitch in game) is not a test. The integrate window should
additionally be built under ThreadSanitizer in a ctest target; TSan finds the
races a determinism check misses.

**Slot lifecycle tests:** alloc / free / reuse; a stale handle failing loudly on
its generation counter; `weakref.finalize` firing under `gc.collect()`; no slot
leak across many create/destroy cycles (torpedoes churn hard).

**One pinning test for the aliasing change**, asserting that mutating a matrix
passed to `SetMatrixRotation` does *not* move the object — so it is a recorded
decision rather than an accident someone later "fixes" back.

**What none of this can see:** an object drawn in the wrong place, flight feel
after the Phase 4 port, and anything about how the game reads. Those are the
live checkpoints at Phases 2, 3, 4 and 5.

## Risks

| risk | mitigation |
|---|---|
| `SetMatrixRotation` aliasing is load-bearing somewhere | Grep every caller in Phase 2; pinning test; live checkpoint |
| Per-call read-through is slower than today's Python attribute access | `TGMatrix3` flattening in Phase 0 lands first and is measured on its own; hot paths convert to bulk rather than per-call |
| C++ motion port diverges from SDK-faithful behaviour | Differential test against the Python reference, which is retained behind a flag |
| Threading wins nothing at realistic ship counts | Expected and stated; threshold falls back to inline; the banked win is Phase 3, not Phase 5 |
| Slot leak or stale handle | Generation counters; `weakref.finalize`; explicit lifecycle tests |
| Native and Python backends drift | Shared conformance suite runs against both |

## Open questions

- The crossover point for the threading threshold is unknown and must be
  measured on `combat_stress`, not guessed.
- Whether `render_prep`'s remaining cost after Phase 3 is dominated by transform
  marshalling or by the rest of the render-data build. A cProfile of that phase
  before Phase 3 would size the prize more precisely.
