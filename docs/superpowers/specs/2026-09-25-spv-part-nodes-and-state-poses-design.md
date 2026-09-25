# SPV part nodes and full per-state poses

**Status:** DESIGNED 2026-09-25, sections approved in conversation. Not built.
**Supersedes:** the per-part authoring surface and the hinge-angle format of
`docs/superpowers/specs/2026-09-23-spv-part-articulation-authoring-design.md`
(§3 format, §4.1 easing, §5.2-5.3 pane and controls). Everything else there
stands: part candidates, derived bounds, the forced NIF pose while editing
mounts, the safety lock, warp-wins state selection, NPC states.

---

## 1. The problem

Mark, using the Model Parts pane live:

1. **The anchor cannot be found.** It is settable (select the part, then the
   Move tool drags `pivot`, `ship_property_viewer_panel.py:535`), but nothing
   says so: no readout, no field, no drawn hinge. A new part's pivot defaults
   to **(0, 0, 0)**, the ship's centre (`ship_property_viewer_panel.py:507`),
   contrary to the earlier spec's "defaults to the node's derived centre", so
   the gizmo appears nowhere near the part.
2. **A pose per state cannot be set.** The format holds one hinge (pivot +
   axis) and one angle per state. The earlier spec excluded translation and
   more than one hinge (§3 "Deliberately excluded"). The Rotate tool edits the
   hinge AXIS, not a state's angle, so angles can only be typed.
3. **The pane's layout does not read.** State rows sit inside the parts list;
   the bare number beside each state has no meaning to an author; "Detachable"
   plus a 0-1 fraction does not say what the fraction is.

## 2. Decisions

### 2.1 A part's rules are child nodes, like lights and emitters

A part row gets up to six children, each a node with one job: **Anchor**, one
**{State} Transformation** per state (Cruising, Yellow Alert, Red Alert,
Warp), and **Breakage**. One of each at most. They are added and removed by
right-click, and selecting one is how it is edited. This reuses the SPV's
existing nested-row idiom (lights and emitters under a subsystem) and its
existing right-click menus (`spvShowMenuItems`).

### 2.2 A state stores a full rigid pose

A state transformation is the part's whole pose in that state: a rotation and
a translation. A state with no transformation is the NIF pose. This lifts the
single-hinge limit; a part may slide, or swing about any axis, per state.

### 2.3 The anchor shapes the swing, not the destination (option A)

Poses are stored independently of the anchor. Moving the anchor after poses
are authored leaves every pose exactly where it was; it only changes the path
the part takes between states, which swings around the anchor instead of
sliding. **Rejected (option B):** storing poses relative to the anchor, so
moving it moves every pose; authored work would move unexpectedly.

The transition time belongs to the anchor for the same reason: both describe
the motion between states, not the states.

### 2.4 An anchor is required before any transformation

A transformation without an anchor has no defined swing. Adding one without
an anchor shows a toast and does nothing; removing the anchor while
transformations exist likewise.

### 2.5 Breakage is stated as the rule it is

The stored value is unchanged in meaning: damage accumulated **on this part**
as a fraction of the **ship's maximum hull**. The UI shows it as a percentage
with that sentence, never as a bare 0-1 number.

## 3. The format

One template per part, keyed by NIF node name, in `hardpoint_overrides.py`
(and, later, a mod's own hardpoint file). Numbers only; the block is emitted
under the existing `hasattr(App, "ArticulatedPartProperty_Create")` guard and
is Python-1.5-safe.

```python
if hasattr(App, "ArticulatedPartProperty_Create"):
    LeftWing = App.ArticulatedPartProperty_Create("left wing")
    LeftWing.SetAnchor(-0.16, 0.0, 0.05)
    LeftWing.SetTransitionSeconds(2.0)
    LeftWing.SetStatePose("cruise", tx, ty, tz, rx, ry, rz)
    LeftWing.SetStatePose("warp",   tx, ty, tz, rx, ry, rz)
    LeftWing.SetBreakFraction(0.20)
    App.g_kModelPropertyManager.RegisterLocalTemplate(LeftWing)
```

| Call | Units | Meaning |
|---|---|---|
| `SetAnchor(x, y, z)` | SHIP units, body frame | swing centre; optional, required by any pose |
| `SetTransitionSeconds(s)` | seconds | time for any state change; default 2.0 |
| `SetStatePose(state, tx,ty,tz, rx,ry,rz)` | SHIP units; degrees | the part's rigid pose in `state` |
| `SetBreakFraction(f)` | fraction of MAX hull | shears the part; omit = unbreakable |

**Pose convention (pinned by a test against the renderer's matrix):** a
body-frame point `x` of the part is drawn at `R·x + t`, with
`R = Rz(rz) · Ry(ry) · Rx(rx)` — rotate about body X first, then Y, then Z,
right-handed, column-vector (CLAUDE.md's convention) — and `t = (tx, ty, tz)`.
`R` and `t` are about the body ORIGIN, not the anchor: that is what makes a
pose independent of the anchor (§2.3).

**Legacy calls still load.** `SetPivot`, `SetAxis`, `SetStateAngle` and
`SetDetachFraction` are read and converted on load (§6); the writer never
emits them again. `SetDetachFraction` maps to `SetBreakFraction`.

## 4. Runtime

### 4.1 Motion between states

Each rigged part holds a transition: the pose it started from `(R₀, t₀)`, the
target pose `(R₁, t₁)` of the state it is heading to, and progress
`u ∈ [0, 1]`, advanced by `dt / TransitionSeconds`. With anchor `a`:

```
a₀ = R₀·a + t₀        a₁ = R₁·a + t₁          (where the anchor starts / ends)
R(u) = slerp(R₀, R₁, u)
anchor(u) = lerp(a₀, a₁, u)
x(u) = R(u)·(x − a) + anchor(u)
```

At `u = 0` this is `R₀·x + t₀`; at `u = 1`, `R₁·x + t₁`, for any anchor, which
is exactly §2.3. Between them the part rotates about the anchor while the
anchor travels straight: a swing, not a slide.

A state change mid-transition starts a new transition from the CURRENT pose
`(R(u), t(u))`. A change to a state whose pose equals the current one does
nothing.

### 4.2 One reader for the live pose

`ship._articulation_angles` ({name: degrees}) becomes `ship._articulation_poses`
({name: (R, t)}, the current pose). Every consumer already routes through the
shared helpers made single-source this session, so each changes at one point:

| Today | Becomes |
|---|---|
| `articulation.rotation_for` / `point_at_angle` / `vector_at_angle` | `point_at_pose(pose, x)` / `vector_at_pose(pose, v)` |
| `articulation.angle_for_part` | `pose_for_part(ship, part)` |
| `articulation.part_transform_point` | unchanged signature; applies the pose |
| `part_severance.part_for_live_point` / `rest_point_for_live_point` | inverse pose `Rᵀ·(x − t)` |
| `hull_bounds` travel reach | each state's pose (as it evaluates each state's angle today) |
| `host_loop._sync_ship_articulation` | pushes a matrix (§5) |
| `force_pose(ship, state)` | snaps `_articulation_poses` to the state's poses |

Consumers this reaches, all through `part_transform_point` or the pose: mounts
and SPV pins, cast lights (`_articulate_emitter_light`), splash catchment,
target offsets and Manual Aim, severance attribution, hull bounds, the render
sync. Unrigged ships stay byte-identical: no rig, no pose, no call.

Unchanged: warp outranks alert level; NPCs use "has a target" and never show
yellow; the SPV forces the NIF pose while mounts are edited; the `K` dev key
cycles the whole rig.

## 5. Native surface

`set_instance_node_rotation(iid, node, pivot, axis, theta)` is replaced by

```
set_instance_node_transform(iid, node, m16) -> bool
```

`m16` is a 4×4 column-major matrix in the node's PARENT (model) space, MODEL
units; the node's override becomes `M · local_transform`, and the identity
clears the override (the empty-map fast path). Python builds `M` from the pose
with the translation divided by `MODEL_TO_SHIP` (0.01), the one place ship and
model units meet, as today. A severed (hidden) node keeps its zero override:
the sync never pushes a pose onto it, as today.

## 6. Migration

The Bird of Prey's hinge data converts once, through the writer, into the new
calls. A legacy hinge (pivot `p`, axis `n`, angle `θ` for a state) becomes
anchor `p` and pose `R = rot(n, θ)`, `t = p − R·p`. Its motion is unchanged:
slerp between rotations about one shared axis with the anchor on that axis is
exactly the old linear angle ease, and every BoP transition already swings the
full range in 2 s (cruise = yellow = warp = ±45°, red = 0°), which is
`TransitionSeconds = 2.0`.

Verified by asserting that sampled points on each wing land in the same place
under the old maths and the new, at every state and mid-transition. The frozen
test rig (`tests/conftest.py:bop_fixture_rig`) moves to the new calls with
values produced by the same conversion.

## 7. The SPV

### 7.1 Tree

The Model Parts pane renders as a tree in the subsystem tree's row style:

```
▾ left wing
    Anchor
    Cruising Transformation
    Warp Transformation
    Breakage
  head
    Breakage
```

### 7.2 Menus

Part row (right-click):
- **Add Anchor**, hidden once present. The anchor starts at the part's derived
  box centre.
- **Add State Transformation ▸** listing only states without one. Without an
  anchor: toast "Add an anchor first — transformations swing around it", no
  change. A new transformation starts at the NIF pose (identity).
- **Make Breakable**, hidden once present; starts at 20%.

Child row (right-click): **Remove**. Removing the anchor while transformations
exist: toast, no change.

### 7.3 Selection

| Node | Part drawn | Gizmos | Inline field |
|---|---|---|---|
| Part row | NIF pose, derived box | none | none |
| Anchor | NIF pose, anchor marker | Move (the anchor) | Transition time (s) |
| {State} Transformation | posed in that state (this part only) | Move + Rotate the part, Rotate centred on the anchor | none |
| Breakage | NIF pose, derived box | none | "Breaks off after taking [20]% of the ship's hull strength" |

While a transformation is selected, subsystem, light and emitter editing are
locked with the existing one-line reason. Selecting anything else, or closing
the SPV, returns the part to the NIF pose.

### 7.4 Toast

A transient message at the top of the SPV, a few seconds, one at a time. New:
the SPV has no toast today.

### 7.5 Removed

The angle rows, the Preview buttons, and the Detachable checkbox + fraction.

Edits join the existing undo stack, rows show the unsaved-edit marker, and
Save writes through the existing writer (`set_part` / `_emit_part`, now
emitting §3's calls).

## 8. Staging

Each stage leaves the game working.

1. **Format, maths, migration.** New template calls and legacy loading;
   poses, transitions, `_articulation_poses`; every §4.2 consumer switched;
   the BoP converted. The BoP must behave identically (§6's test).
2. **Native.** `set_instance_node_transform`; the render sync pushes
   matrices; a gtest that a pose's matrix matches the Python maths.
3. **SPV tree.** Tree payload, rows, menus, toast, selection rules, lock,
   Save, undo; the old controls removed.
4. **SPV gizmos.** Anchor Move; pose Move + Rotate about the anchor, writing
   the selected state's pose.

## 9. Testing

- **Maths (pure):** the Euler convention against a hand-built matrix; pose
  composition and inverse; the swing (midpoint on the arc, not the chord);
  an interrupted transition; moving the anchor leaves end poses unchanged;
  the migration equivalence (§6).
- **Runtime:** every existing consumer test re-pointed at poses, still
  asserting on what the renderer or combat receives.
- **Native:** the node-transform matrix equals the Python pose, including the
  unit conversion.
- **SPV (pure):** tree payload; each menu rule; the no-anchor toast; the
  remove-anchor refusal; one node per kind; selection poses only that part and
  locks mounts; inline fields stage edits; Save emits §3 and round-trips.
- **Live (Mark):** author an anchor and a Warp pose on the BoP and see it on
  warp entry; the swing reads as a hinge; moving the anchor leaves the poses
  where they were.

## 10. Risks

| Risk | Handling |
|---|---|
| Euler order mismatch between Python and the renderer | Pinned by a test against the native matrix (§9) |
| Wide blast radius (~11 source files, ~20 test files) | Stage 1 must be behaviour-identical for the BoP before any UI work |
| Hull-bounds reach ignores the swing path between states | Same limitation as today's per-state evaluation; recorded, not designed around |
| Legacy files with a hinge but no pivot | A hinge with no `SetPivot` converts with the anchor at the origin, matching today's default |
