# Nebula Pockets — Faithful Rendering + Gameplay Effects

**Date:** 2026-06-22
**Status:** Design approved, pending spec review
**Scope:** Make BC `MetaNebula` "pockets" fully functional — faithful two-texture
rendering plus the gameplay effects (enter/exit events, environmental damage,
sensor-range scaling) — building on the geometry-only `MetaNebula` already in
`engine/appc/nebula.py`.

---

## 1. Background

### Two distinct "nebula" mechanisms in BC

The Vesuvi system (our reference) uses two unrelated things both called "nebula":

1. **Backdrop sphere** `"Backdrop treknebula3"` — a painted skybox texture
   (`data/Backgrounds/treknebula3.tga`) on a giant `BackdropSphere`. Pure
   scenery on the celestial sphere. **Already handled** by
   `engine/appc/backdrops.py` + `renderer.set_backdrops`. Out of scope.

2. **`MetaNebula` volume** (`Systems/Vesuvi/Vesuvi4_S.py:13-22`) — the
   interactive fog *pocket* the player flies into, with damage/sensor/warp
   effects. **This is the subject of this project.**

### The SDK construction recipe

```python
# Systems/Vesuvi/Vesuvi4_S.py — runs from Vesuvi4.Initialize() -> Vesuvi4_S.Initialize(pSet)
pNebula = App.MetaNebula_Create(
    155.0/255.0, 90.0/255.0, 185.0/255.0,   # r, g, b tint (purple)
    145.0,                                    # visibility distance INSIDE (GU)
    10.5,                                     # sensor density (scale sensor range; see clamp note)
    "data/Backgrounds/nebulaoverlay.tga",     # INTERNAL texture (has alpha) — fog when inside
    "data/Backgrounds/nebulaexternal.tga")    # EXTERNAL texture (no alpha) — cloud from outside
pNebula.SetupDamage(150.0, 20.0)              # hull dmg/sec, shield dmg/sec
pNebula.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)  # x, y, z, radius — a "pocket"
pSet.AddObjectToSet(pNebula, "my foggy new nebula")
```

A `MetaNebula` is a **union of fuzzy spheres**. Vesuvi4 uses one 1500 GU
sphere; `Systems/Multi5/Multi5_S.py` and `Multi6_S.py` cluster several
overlapping spheres to sculpt irregular cloud shapes ("pockets").

### Original rendering model (two textures)

- **External texture** (`nebulaexternal.tga`, opaque): drawn when the camera is
  **outside** — a soft cloud so the nebula is visible from a distance.
- **Internal texture** (`nebulaoverlay.tga`, alpha): a fog effect when the
  camera is **inside**, tinted by `(r,g,b)`, with `visibility` controlling the
  draw-distance falloff. Not particles — a tinted distance-fog + billboard shell
  keyed on point-in-sphere tests.

### Current engine state

- `engine/appc/nebula.py` — `MetaNebula` with `AddNebulaSphere`,
  `GetNebulaSpheres`, `IsObjectInNebula`, `SetupDamage` (stored, unused),
  `MetaNebula_Create`, `Nebula_Cast`. **Geometry only.**
- `engine/appc/sets.py:315` — `GetNebula()` / `GetClassObjectList(CT_NEBULA)`.
- `engine/appc/warp_gates.py:69` — `_in_nebula` warp-blocking already works.
- **Missing:** rendering, enter/exit events, environmental damage application,
  sensor scaling, `MetaNebula_Cast` export.

---

## 2. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Render fidelity | **Faithful first**, modern volumetric toggle **next project** | Cheap + correct now; volumetric is a separate round |
| Inside fog | **Depth-aware distance fog** (world-space, hull-occluded) | Sits correctly in our HDR/depth pipeline; ships fade into murk with range |
| Outside view | **Soft billboard shell now** (per sphere, `nebulaexternal.tga`) | Nebula visible from afar; faithful; cross-fades to inside fog at rim |
| Toggle | None this project; faithful path is always-on | Faithful *is* the stock look. Future volumetric sits behind Modern VFX (`off = faithful`) |
| Verification set | **Vesuvi4** (single 1500 GU sphere); Multi5/Multi6 for multi-pocket | Self-contained, loadable standalone |

### Forward-compat seam for next project (modern volumetric + lighting)

The render pass selects behind a `nebula_style` enum (`FAITHFUL` now,
`VOLUMETRIC` later) fed from the existing **Modern VFX** config group. The
binding payload (sphere union + tint + visibility + sun direction) is already
everything a raymarched volumetric + scattering pass needs, so the upgrade is a
new shader path behind the **same data contract** — no host-loop or model
changes. `off = faithful`, matching the "off/off = stock BC" philosophy.

---

## 3. Architecture

**Native render pass + thin Python data binding** — mirrors `dust_pass`,
`hologram_pass`, `subsystem_pin_pass`. The pass owns GL; the host loop scrapes
nebula data per frame and pushes it across a binding (like `set_backdrops`).
Gameplay logic stays in Python.

Rejected alternatives: pure-Python screen overlay (can't do depth-aware fog —
shader needs the depth buffer); folding into a generic "volume effects" pass
(premature generalization).

### Components

| Unit | Location | Responsibility |
|---|---|---|
| **MetaNebula model** (extend) | `engine/appc/nebula.py` | Add `MetaNebula_Cast` export + getters (tint, visibility, sensor_density, external/internal tex). No new state. |
| **Nebula membership tracker** | `engine/appc/nebula_runtime.py` (new), driven by host loop | Per sim-tick: diff per-ship sphere containment vs last tick → broadcast enter/exit events; apply environmental damage + sensor scaling while inside. Pure Python, no GL. |
| **Render data scraper** | `engine/host_loop.py` (alongside `_aggregate_backdrops`) | Once/frame: collect active-set nebulas → list of `{spheres, rgb, visibility, external_tex, internal_tex}` → `_h.set_nebulae(...)`. |
| **Binding** | `native/src/host/host_bindings.cc` | `set_nebulae(list)` → C++ structs. Mirrors `set_backdrops`. |
| **Nebula render pass** | `native/src/renderer/nebula_pass.{cc,h}` + shaders | Inside: depth-aware fog. Outside: soft additive billboard shell per sphere, rim cross-fade. `nebula_style` enum seam. |
| **Pipeline hook** | `native/src/renderer/pipeline.cc` | Invoke after scene/hull, before HUD (depth buffer bound). |

**Boundaries:** render pass = data in → pixels out (no gameplay knowledge);
membership tracker = no GL; model = plain geometry + params. Each testable alone.

---

## 4. Data flow

### Per-frame render path (every frame)

```
host_loop frame tick
  └─ _aggregate_nebulae(active_set)        # Python, alongside _aggregate_backdrops
       → [{spheres:[(x,y,z,r)…], rgb, visibility, ext_tex, int_tex}]
  └─ _h.set_nebulae([...])                 # binding, mirrors set_backdrops
        → nebula_pass caches structs
  └─ pipeline draws nebula_pass(camera, depth) after hulls, before HUD
```

Camera-in-sphere test happens in the pass/shader (cheap, per-sphere) to choose
inside-fog vs outside-shell and cross-fade at the rim. All sphere data is
world-space **GU** end-to-end — no display conversion (per game-unit convention).

Inside fog shader (faithful path):
```
fog   = 1 - exp(-sceneDepth / visibility)   # depth from depth buffer
color = mix(sceneColor, rgb_tint, fog)      # modulated by sampled nebulaoverlay noise
```

Outside shell: per sphere, when camera outside, draw a soft additive
camera-facing billboard sized to the sphere radius (`nebulaexternal.tga`),
rim-fading, blending into the inside fog as the camera crosses each boundary.

### Per-tick gameplay path (sim tick, decoupled from render)

Membership tracker over ships in sets that have a nebula (early-out on empty
`GetClassObjectList(CT_NEBULA)`):

- **Enter/exit:** maintain a `set()` of `(nebula, ship)` membership. New
  containment → `g_kEventManager` broadcast `ET_ENTERED_NEBULA`
  (source=nebula, dest=ship); lost containment → `ET_EXITED_NEBULA`. This is
  exactly what `Conditions/ConditionInNebula.py` and mission scripts listen for.
- **Environmental damage:** while inside, broadcast `ET_ENVIRONMENT_DAMAGE` to
  the ship each tick, scaled by `SetupDamage(hull, shields)` and by sim `dt`
  (the `150.0` is dmg/**sec**). Objects that registered `MissionLib.IgnoreEvent`
  for `ET_ENVIRONMENT_DAMAGE` (the asteroids in `Vesuvi4_S`) naturally no-op —
  we fire the event and their handler swallows it.
- **Sensor scaling:** while inside, scale the ship's sensor subsystem range by
  `sensor_density` clamped to `[0,1]` (1.0 = normal, 0.0 = blind; Vesuvi's
  `10.5` is out-of-range data → clamp to `1.0`). Restore on exit.

**Decoupling rationale:** render needs every-frame geometry for smooth visuals;
gameplay needs only sim-tick granularity and must respect `frame_dt=0` freezes
(no damage while paused). Two consumers of one model, neither blocking the other.

### Invariants

- Membership tracker **resets on mission swap** (per the MissionLib-global-leak
  lesson — leaked state across in-process swaps is a known failure mode).
- Damage uses **sim dt**, not wall-clock; **no damage at `frame_dt=0`**.
- Tracker only runs for sets with a nebula (cheap early-out).
- **Byte-identical to stock BC** when no nebula is present (empty-list early-out
  in both render and gameplay paths).

---

## 5. Testing

| Unit | Test | Assertions |
|---|---|---|
| Model | pytest | `MetaNebula_Cast` returns obj for nebula / `None` otherwise; getters return constructor values; sphere-union membership at boundaries (on-surface, just-in, just-out, multi-sphere overlap) |
| Membership tracker | pytest, fake ships crossing boundaries | exactly one enter/exit per transition (no repeats while stationary inside); damage per tick scaled by dt; `IgnoreEvent` objects take no damage; sensor range restored on exit; `frame_dt=0` → no damage; mission swap clears state |
| Render data scraper | pytest on Vesuvi4 set | one nebula, sphere `(0,1500,0,r=1500)`, tint `(155,90,185)/255`, visibility `145` |
| Render pass | C++ `FrameTest` (as `dust_pass`/`hologram_pass`) | camera inside → tinted fog at depth; camera outside → billboard shell renders |
| Live | load **Vesuvi4** via dev set loader | fly in from outside (shell → rim → fog closes in); hull damage ticks; sensors shorten; warp blocked. Multi5/Multi6 = multi-pocket. **No desktop interaction on Mark's workstation — hand off the build to drive.** |

---

## 6. Milestones

Each independently shippable, roughly ascending effort. 1–3 deliver working
gameplay nebulae **before any pixels**.

1. **Model completion** — `MetaNebula_Cast` export + getters. Tiny; unblocks
   MissionLib warp-obstacle-avoidance (`MetaNebula_Cast` is called there).
2. **Membership + events** — tracker firing `ET_ENTERED_NEBULA`/
   `ET_EXITED_NEBULA`; makes `ConditionInNebula` work. Pure Python.
3. **Environmental damage + sensor scaling** — wire `SetupDamage` + sensor
   density into the tracker. Pure Python.
4. **Render data plumbing** — `_aggregate_nebulae` + `set_nebulae` binding +
   empty pass (no pixels). Verifies data reaches C++. `nebula_style` enum seam
   lands here.
5. **Inside depth-fog** — the core visual; the pocket you fly through.
6. **Outside billboard shell** — from-a-distance cloud + rim cross-fade.

1–3 are pure Python and land fast; 4–6 are renderer work.

---

## 7. Out of scope

- **Modern volumetric rendering + lighting/scattering** — explicit next project,
  behind a Modern VFX toggle, reusing this project's data contract.
- The `treknebula3` backdrop skybox (already handled by `backdrops.py`).
- Multiplayer-specific nebula sync beyond what existing set replication covers.

---

## 8. Key references

- `sdk/Build/scripts/Systems/Vesuvi/Vesuvi4_S.py` — reference construction
- `sdk/Build/scripts/Systems/Multi5/Multi5_S.py`, `Multi6_S.py` — multi-pocket
- `sdk/Build/scripts/Conditions/ConditionInNebula.py` — event consumer
- `sdk/Build/scripts/Bridge/HelmMenuHandlers.py:785` — warp-block consumer
- `sdk/Build/scripts/MissionLib.py:4988` — `GetNebulaSpheres` / `MetaNebula_Cast`
  warp obstacle-avoidance consumer
- `engine/appc/nebula.py` — current model
- `native/src/renderer/dust_pass.cc` — render-pass + binding pattern to mirror
