# Ship Property Viewer — part articulation authoring

**Status:** DESIGNED 2026-09-23. Not built.
**Supersedes the data half of:** `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`
(that spec's §3 `_RIGS`, §4.2 `PART_BOXES` and §5 `DETACHABLE` are hardcoded
Python dicts; this spec turns all three into authored templates.)

---

## 1. The problem

Three things, in the order they were raised:

1. **The SPV edits hardpoints through whatever pose the ship happens to be in.**
   The hologram re-draws the live player instance, and `HologramPass::render`
   deliberately honours `inst->node_overrides`
   (`native/src/renderer/hologram_pass.cc:51-56` — it must, or subsystem pins on
   an articulated part land in the wrong place). Opening the SPV freezes the sim
   but does **not** reset deflection: `_sync_ship_articulation`
   (`engine/host_loop.py:7022-7062`) runs in the render pass, not the sim tick,
   and re-pushes the frozen deflection every frame. So a Bird of Prey opened at
   green alert is drawn **wings up**, its pins follow that pose, and any mount
   position authored through it is written back as a rest-pose number. The error
   is ~0.9 ship units (~150 m) at the wingtip, and nothing on screen says so.

2. **Nothing can enumerate a model's nodes from Python.** Every `m.def` in
   `native/src/host/host_bindings.cc` touching model/node/instance was checked:
   `instance_node_world(iid, node_name, animated)` takes a name as *input* and
   returns one matrix; there is no enumerator. `articulation.py` therefore
   hardcodes `"left wing"` as a string literal read off the NIF by hand, and its
   own comment concedes the same for bounds: "nothing exposes per-part bounds to
   Python" (`engine/appc/articulation.py:335-338`).

3. **Articulation is hardcoded and binary.** One scalar `deflection` eased 0→1,
   target derived from alert level. There is no way to author a rig, mark a part
   detachable, or express more than two poses.

## 2. Decisions

Each was settled in conversation; the rationale is recorded because the
reasoning is the part that does not survive in code.

### 2.1 The NIF pose is the anchor

A NIF stores exactly one authored geometry. `deflection = 0` means "no rotation
applied", so the NIF pose is the frame hardpoint mounts are authored in. Every
other pose is a rotation away from it.

For the Bird of Prey the NIF pose is **wings down** — the attack configuration,
which in the four-state scheme below is Red Alert, not Cruising.

**Consequence, accepted:** the SPV shows a BoP in attack posture whenever
hardpoints are being edited, even though Cruising is the nominal resting state.

**Rejected:** declaring Cruising to be the anchor and authoring a rotation from
it to the NIF pose. That would give the BoP a non-zero rotation on the state it
spends most of its combat life in, and that rotation would have to be applied to
hardpoints too.

### 2.2 The format is a BC property template, and it has two homes

`hardpoint_overrides.py` exists because we **cannot write into BC's own
hardpoint files** — the SDK tree stays byte-identical
(`engine/appc/override_routing.py:1-6`). It is a stop-gap for STOCK ships. A
modded ship owns its hardpoint file and will eventually have its SPV edits
written straight into it.

So the format is designed for a hardpoint file from day one. A hardpoint file is
nothing but this, repeated:

```python
X = App.SomeProperty_Create("Name")
X.SetFoo(...)
App.g_kModelPropertyManager.RegisterLocalTemplate(X)
```

An articulated part is therefore **a property template like any other**, which
is also exactly the shape `hardpoint_overrides.py` already replays
(`find(name).SetX(...)`).

**Rejected:** a separate `engine/appc/ship_parts.py`. It would have been one
file keyed by the same hardpoint leaf — no new naming convention needed, since
`hardpoint_overrides.py` has no declared location either and is keyed by the
leaf the ship script declares. But it would have had no path into a mod's own
hardpoint file, which is where this data belongs long-term.

### 2.3 The stbc.exe compatibility guard sits on `App`, not on the instance

The established convention guards a block of Dauntless-only setters with
`hasattr` on the **property object** (`README.md:118`, real instance at
`sdk/.../ships/Hardpoints/galaxy_dauntless_mods.py:735`):

```python
if hasattr(SensorArray, "SetGlowRegionShape"):
    SensorArray.SetGlowRegionShape(0, "Sphere")
```

That works because `SensorArray` already exists in stock BC — the guard only
gates an *extension*. An articulated part is a property stock BC has never heard
of, so `App.ArticulatedPartProperty_Create(...)` raises before any instance
exists to guard on. **The guard moves one level up, onto `App`.**

`hasattr(x, "name")` is a two-argument builtin valid back to Python 1.0, so the
guard parses under stbc.exe's Python 1.5. Everything inside a guarded block must
still be 1.5-safe: no `True`/`False` literals, no f-strings, no `import X as Y`.

`hardpoint_overrides.py` needs **no** guard — stbc.exe never executes it.

### 2.4 Four states, warp wins

| State | Player | NPC |
|---|---|---|
| `warp` | at warp | at warp |
| `red` / `yellow` / `cruise` | alert level | `red` if it has a target, else `cruise` |

Warp outranks alert level: wing position is a flight configuration, so warp entry
visibly re-configures the ship.

**NPCs never show `yellow`.** BC never takes an NPC off Red Alert — measured,
not assumed (stbc-oracle bible §13 N2), which is why the original spike keyed NPC
articulation off "has a target". Inventing NPC alert levels was rejected.

### 2.5 Bounding boxes are derived, not authored

Once nodes can be enumerated, a part's bounds come from its own geometry. This
deletes an entire authoring surface and cannot drift from the mesh.

**Consequence, accepted and load-bearing:** today's `PART_BOXES` are hand-drawn
and deliberately loose — the BoP's wing boxes swallow the body box at the roots,
and `part_for_point` returns `None` wherever boxes overlap. Derived boxes are
tighter, so attribution gets **sharper**: hits near the wing root that currently
attribute to nothing will attribute to the wing, and a wing will accumulate
severance damage faster. The 20% detach threshold was tuned against the loose
boxes. **This needs a live re-check, not a test.**

### 2.6 Part candidates are children of `Scene Root`

The "Top Level Object" marker in the NIF is a **stream-framing label**, not a
node flag: `native/src/nif/src/file.cc:81-91` reads it and then re-reads the
block's real type name. It is discarded, and `assets::Node`
(`native/src/assets/include/assets/model.h:36-42`) has no field for it.
Filtering on it would mean threading a new field through the reader, the model
builder and the binding.

Unnecessary — the hierarchy already says it. Measured with
`native/tools/dump_nif_tree` on `BirdOfPrey.nif`:

```
[5] NiNode 'Scene Root'  (children=4, shapes=10)
      [6]  NiNode 'head'          (children=1, shapes=2)
      [20] NiNode 'left wing'     (children=1, shapes=2)
      [32] NiNode 'left wing01'   (children=1, shapes=2)
      [42] NiNode 'birdofprey'    (children=1, shapes=4)
```

The four parts are exactly the children of `Scene Root`. `Scene Root` itself
sits under two unnamed wrapper nodes ([0] and [2]), so the rule is **children of
the node named `Scene Root`, else children of the first node with more than one
child**, with a "show all" toggle as the escape hatch.

Every part's geometry hangs off an interposed `__NDL_MultiMtl_Node` — a 3ds Max
exporter artifact. A real hull is **three levels**, and a two-level test fixture
is what let a picking bug reach live play in the preceding work. Fixtures here
mirror three.

---

## 3. The format

One template per movable or detachable node:

```python
if hasattr(App, "ArticulatedPartProperty_Create"):
    LeftWing = App.ArticulatedPartProperty_Create("left wing")
    LeftWing.SetPivot(-0.16, 0.0, 0.05)
    LeftWing.SetAxis(0.0, 1.0, 0.0)
    LeftWing.SetStateAngle("red",    0.0)
    LeftWing.SetStateAngle("cruise", 45.0)
    LeftWing.SetStateAngle("yellow", 45.0)
    LeftWing.SetStateAngle("warp",   20.0)
    LeftWing.SetDetachFraction(0.20)
    App.g_kModelPropertyManager.RegisterLocalTemplate(LeftWing)
```

| Call | Units | Meaning |
|---|---|---|
| `_Create(name)` | — | **The template name IS the NIF node name.** |
| `SetPivot(x, y, z)` | SHIP units, parent/model frame | hinge point; defaults to the node's derived centre |
| `SetAxis(x, y, z)` | direction, normalised on use | hinge axis; defaults to ship-forward `(0, 1, 0)` |
| `SetStateAngle(state, deg)` | degrees | rotation about the hinge in that state |
| `SetDetachFraction(f)` | fraction of MAX hull | damage on this part that shears it; omit = not detachable |

**No `SetNode`.** One string serves as both the template name and the node name,
and it is the same key `find()` already uses.

> ⚠️ **Accepted risk:** a node named identically to a subsystem would collide in
> `FindByName`. No stock ship does this. Written down rather than designed
> around.

**Three things fall out of this shape:**

- **The anchor pose needs no declaration.** The NIF *is* angle 0, so the SPV's
  safe editing pose is simply "every part at 0". There is no "which state is
  canonical" field to get wrong. For the BoP that is Red Alert; for another ship
  it might be Cruising, and nothing in the format cares.
- **Detachable-but-static costs no extra concept.** A part with all four angles
  0 and a detach fraction is a breakable panel — the `head`, for instance.
- **Bounds are absent**, per §2.5.

**Deliberately excluded** (YAGNI; re-openable): per-part travel time, easing
curves beyond linear, more than one hinge per part, translation.

---

## 4. Runtime

### 4.1 What replaces `deflection`

A ship carries one float 0→1 today, and `rotation_for` computes
`theta = radians(angle_deg) * deflection`. That cannot express four independent
angles. It becomes **a current angle per part**, eased toward the target state's
angle for that part.

Each part eases at its own rate — its full range (max authored angle minus min)
divided by `TRAVEL_SECONDS` — so a part swinging its whole travel always takes
2 s, and parts moving between the same two states stay in sync. **Interrupting a
transition needs no special handling:** the target angle changes and the part
keeps easing from wherever it is.

### 4.2 Blast radius

`GetArticulationDeflection()` is read in exactly five places, all of which move
from "one scalar" to "ask the part for its angle":

| Site | Today |
|---|---|
| `articulation.part_transform_point` | `deflection == 0.0` early return, then `rotation_for` |
| `host_loop._sync_ship_articulation` | pushes `set_instance_node_rotation` per part |
| `engine/appc/hull_bounds.py` | via `part_transform_point` |
| `engine/appc/part_severance.py` | via `part_transform_point` / `part_for_live_point` |
| `engine/dev_keybindings.py` `K` | cycles `None → 0.0 → 0.5 → 1.0` |

A ship with no rig stays a no-op throughout — the overwhelmingly common case
must remain byte-identical.

The `K` binding becomes a **state** cycle: `follow → cruise → yellow → red →
warp → follow`. More useful than 0/0.5/1, because those are now the authored
states themselves.

---

## 5. Authoring

### 5.1 The anchor pose is forced (problem 1)

On SPV open, every part's override is set to angle 0 and the hull is drawn in its
NIF pose; on close, the live state resumes. **Unconditional** — it does not
depend on the Model Parts pane being open — so hardpoint editing always happens
in the frame hardpoint mounts are stored in.

### 5.2 The Model Parts pane

A collapsed pane beneath the subsystem tree, header **Model Parts**. Clicking the
header expands it to 25% of the vertical space. It lists part candidates per
§2.6, with a "show all" toggle.

Selecting a part draws its derived bounding box on the hull, so the author sees
what severance will test against before committing.

### 5.3 Per-part controls

- **Detachable** — checkbox plus a fraction field, default `0.20`.
- **Pivot** — defaults to the node's derived centre; placed with the existing
  Transform gizmo.
- **Axis** — defaults to ship-forward; set with the existing Rotate tool.
- **Angle per state** — four rows (Cruising / Yellow / Red / Warp), each a number
  field plus a Preview button.

Pivot and axis reuse the existing gizmo suite rather than adding a fourth tool.

### 5.4 The safety lock

Preview on a state whose angles are not all zero articulates the hull and
**disables subsystem, light and emitter editing**, with a one-line reason in the
panel. Angles stay editable.

**Why a lock rather than a warning:** the failure it prevents is silent and
invisible — a wingtip cannon authored 0.9 ship units out, discovered only in
combat. A banner relies on the author reading it. This project has shipped
several bugs of exactly that shape.

### 5.5 Persistence

Through the existing Save button and the existing writer
(`engine/appc/hardpoint_override_writer.py`), which gains **one new verb:
find-or-create**. Today it can only modify templates BC already registered —
`find("left wing")` returns `None` for a template that does not exist and the
override is skipped. Creating one is the only structural change the writer needs.

---

## 6. Native surface

**One new binding:**

```
model_nodes(instance_id) -> list of {
    name:       str,
    parent:     str | None,
    candidate:  bool,          # per §2.6
    bounds_min: (x, y, z),     # SHIP units, rest pose
    bounds_max: (x, y, z),
}
```

One crossing covers enumeration **and** derived bounds — the `model_part_bounds`
call `articulation.py:335-338` already wishes it had. Bounds are computed from
the node's subtree geometry composed through the rest-pose node chain, so they
include the `__NDL_MultiMtl_Node` children where the meshes actually live.

No NIF reader change, no new `assets::Node` field (§2.6).

---

## 7. Migration

`articulation.py` **stops holding data**. `_RIGS`, `PART_BOXES` and `DETACHABLE`
become lookups against the registered templates. The module keeps the
mathematics — `rotation_for`, `part_transform_point`, `_rotate_about`, the
easing — and loses the dicts.

The Bird of Prey's current numbers migrate verbatim into
`hardpoint_overrides.py`: same pivots, same axes, 45° / −45° on the non-Red
states, `0.20` detach. Day-one behaviour is therefore unchanged **except** for
the derived-bounds sharpening of §2.5, which makes the migration verifiable
rather than a rewrite.

**`warp` is seeded to the "cruise" angle (45° / −45°), not left at 0.** The
spike had no 4-state model, only a binary fold — Red down/armed, everything
else (including warp) up/cold, i.e. 45°/−45° — so a warping ship shipped
wings-up. Leaving `warp` unauthored in the migration would have SILENTLY
dropped it to 0° (the Red/rest pose) instead, a real behaviour regression the
migration is not supposed to introduce (fix round 1, Task 5). Authoring a
DISTINCT warp pose in the SPV — rather than one that merely happens to equal
cruise — is still the first real exercise of the new per-state surface.

---

## 8. Staging

**§5.1 (the forced anchor pose) depends on none of the rest and ships first.**
It is the fix for the live hazard, it needs no binding, no format and no writer
change, and it is independently verifiable.

Everything after it depends on `model_nodes`.

---

## 9. Risks

| Risk | Handling |
|---|---|
| **Derived bounds change severance tuning** (§2.5) | Live re-check. No test can see it. The 20% threshold may need re-tuning. |
| **Template name / subsystem name collision** (§3) | Accepted, documented, no stock ship does it. |
| **Leaf-keyed rigs describe NIF nodes** | A rig belongs to the model; keying by hardpoint leaf is a proxy that holds because one ship script declares both. Every existing part table already keys this way. |
| **Five call sites move off a scalar** (§4.2) | The unrigged path must stay byte-identical; that is the thing to test hardest. |
| **`model_nodes` fixtures** | Three levels, per §2.6. A two-level fixture already let one bug reach live play. |

## 10. Testing

The format, the state machine and the easing are pure Python and test normally.
The binding gets C++ tests against a synthetic **three-level** model. The safety
lock gets a test asserting that editing is disabled while a non-anchor state is
previewed — the lock is the feature, so an untested lock is no lock.

What no test can cover, and what needs live eyes:

1. A Bird of Prey opened in the SPV is drawn wings-down, whatever alert it was at.
2. Previewing Cruising raises the wings and greys out mount editing.
3. Authoring a warp pose and seeing it on warp entry.
4. Whether sharper derived bounds make wings shear too readily.

## 11. Open questions

- **OQ-1.** Should `warp` interpolate on warp *entry* (as the nacelles spool) or
  snap? Assumed: eases like any other transition.
- **OQ-2.** Is one hinge per part enough for any ship beyond the BoP? Nothing in
  the stock fleet needs two. Re-openable without a format break — a second
  template on a child node composes.
- **OQ-3.** Should a modded ship's hardpoint file be written directly today, or
  does everything keep going through `hardpoint_overrides.py` until the mod
  write path exists? Assumed: the latter; the format is ready either way.
