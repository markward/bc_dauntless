# Subsystem physical parents — design

Status: APPROVED by Mark 2026-10-17. Branch `feat/physical-parents`
(worktree `.claude/worktrees/physical-parents`).
Supersedes OQ-13 of `2026-09-23-ship-part-articulation-design.md` (and
subsumes its OQ-5).

## 1. Intent

A ship subsystem has two positions that have nothing to do with each other:

- its place in the **functional tree**: BC's hardpoint hierarchy, for example
  `Disruptor Cannons` → `Port Cannon`, `Star Cannon`. A functional parent
  routinely groups children that sit on different parts of the hull;
- its place in the **physical tree**: which mesh part of the ship it
  physically lives on, for example `Port Cannon` lives on the Bird of Prey's
  port wing.

Today the physical answer is always *inferred*. One rule,
`part_severance.part_for_mount`, picks the part whose rest-pose triangles are
nearest the subsystem's authored point. That works for points on a part's
skin and fails for points inside the hull. Measured on the stock Bird of Prey
(2026-10-16, articulation spec): the `Impulse Engines` and `Warp Engines`
system points resolve to the port and starboard wings. Each whole system
therefore follows one wing's pose and is destroyed when that wing is shot off.

This design adds an explicit **physical parent**: a mesh part name stored per
property in the hardpoint file and authored in the Ship Property Viewer (SPV).
Where it is set, it wins. Where it is not, behaviour is exactly today's.

The two trees are separate concepts and are always referred to separately.
A functional parent never implies a physical parent, and vice versa.

## 2. Terms

| Term | Meaning |
|---|---|
| functional tree | BC's hardpoint subsystem hierarchy, unchanged |
| physical tree | the ship's mesh parts (below) and what lives on each |
| part | a *candidate* node of the loaded model: a named `NiNode` child of `Scene Root` (`native/src/renderer/model_parts.cc:72`, `part_parent_index` :23-33), the same list the Model Parts pane shows. Rigged or not, moving or not. The body is just another part (BoP: `birdofprey`) |
| physical parent | the part name a property is explicitly set to live on |
| **SET** | a property with a physical parent that resolves to a part |
| **AUTO** | a property with no physical parent: placed by today's nearest-part rule |
| missing | a physical parent naming a part the loaded model does not have |

UI wording is **Auto** / **Set** (Mark, 2026-10-17). Never "guess".

## 3. Goals, non-goals, anti-goals

Goals
- Explicit, per-property physical parent, saved in the hardpoint file.
- One resolution rule shared by every consumer that asks "which part is this
  authored thing on".
- An SPV Physical view to review AUTO placements and correct them.
- Robust to mesh part renames: detected, never silently mis-attached, and
  repairable in one action.
- Zero behaviour change for any ship without physical parents (all ships today).

Non-goals
- Weapon-**hit** attribution. A hit point is arbitrary, not authored; it keeps
  the box rule (`part_for_point` / `part_for_live_point`).
- Decals (§10).
- Emitter lights. They keep today's rule, placed by their **own** position
  (§6), and do not appear on the Physical tab. A SET subsystem does not move
  them. Per-light physical parents are a follow-up (§12).
- Running-light markers on the hologram (§12).
- Merging the Model Parts pane into the Physical tab (§7.8).

Anti-goals (failure even if it "works")
- Writing AUTO placements to disk. Saving a guess freezes it into data and
  hides which placements a human actually checked.
- Re-running inference over SET properties on any trigger (load, rename,
  mismatch). It would wipe deliberate fixes, e.g. the BoP engines put back on
  a wing.
- Pre-picking a repair target. With a part split into several, no rule can
  know (Mark, 2026-10-17).
- Any change to the production render or combat path for ships without
  physical parents.

## 4. Data

### 4.1 The setter

```python
if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:
    PortCannon.SetPhysicalParent("left wing")
```

- `SetPhysicalParent(name)` / `GetPhysicalParent()` on property objects.
  `GetPhysicalParent()` returns `None` when unset.
- Define them **explicitly** on the `TGModelProperty` base
  (`engine/appc/properties.py:7`), not via the data-bag `__getattr__`
  (:72-99) that would accept them today. A real definition keeps the value
  typed (`str` or `None`) and out of stub territory (see the stub-heatmap
  rule in CLAUDE.md).
- Applies to every property the resolution rule places (§5): subsystem
  properties, `ObjectEmitterProperty` mounts (`subsystems.py:286` path) and
  `BlinkingLightProperty` (running lights, `properties.py:242`).
- The name is matched **exactly** against part names. That is the same
  convention the rig uses (`ArticulatedPartProperty` template name = NIF node
  name, `articulated_part.py`).
- Plain name only. A per-ship mesh fingerprint was considered and rejected:
  the only case it catches (a replacement mesh reusing the same part names)
  is one where the names are probably still right, and where every authored
  position is equally stale (Mark, 2026-10-17).

### 4.2 Where it is written

Through the existing SPV save path; no new file.

- **Stock ships** → `hardpoint_overrides.py` via `_emit_function`
  (`hardpoint_override_writer.py:273-292`), inside the subsystem's
  `p = find(name)` block. Unguarded there, like every other stock subsystem
  setter: stbc.exe never loads that file.
- **Mod ships** → the mod's own hardpoint file, in the managed
  `_dauntless_spv` block (`mod_hardpoint_writer.emit_block`, :72-83). That
  block is already wrapped in `env_guard()`, so stock BC skips it.
- `DAUNTLESS_ENV` stays **1** (my call). The App.py:337-345 rule is to bump
  only when emitted code needs surface an older Dauntless lacks; an older
  Dauntless would accept the call harmlessly into its data bag.
- `find` is `FindByName` keyed by name only (`properties.py:1126,1137`), so
  running lights are reachable by name. A name shared by two properties
  collides; that is pre-existing and accepted.

### 4.3 Removal

"Reset to Auto" must **delete** the `SetPhysicalParent` call from the file.
The writer has no remove path today: `set_setter` replaces by setter name
(`_replace_key`, :130). Add a removal edit kind to `apply_edit` (:173), for
example `(name, "__unset__", "SetPhysicalParent")`, honoured by both targets.
A subsystem block left with no calls is dropped. The builder chooses the
exact tuple shape.

Mod files can also carry a **hand-written** `SetPhysicalParent` in the
author's own text, outside the managed block. The managed block runs last,
so its value wins, and that is how every other non-in-place SPV value
already overrides the author's text. So, for a mod target (my call):
- the SPV reads the *effective* value (after the block), which is what the
  row shows;
- Reset to Auto removes the block's call, and if the author's text still
  sets one, writes `SetPhysicalParent(None)` into the block instead. The
  setter must therefore accept `None` (= unset);
- the author's own text is never rewritten (it is not in `INPLACE_SETTERS`).

## 5. Resolution rule

One function, the only answer to "which part is this authored property on",
replacing the direct `part_for_mount(leaf, point)` call in every consumer
(§6):

```
part_for_property(ship_or_leaf, prop, point, iid=None) -> part name | None
  name = prop.GetPhysicalParent()
  if name is set:
      if a model is known for the leaf and `name` is NOT one of its parts:
          warn once per (leaf, name)          -> fall through to AUTO
      else:
          return name                         -> SET
  return part_for_mount(leaf, point, iid)     -> AUTO (today, unchanged)
```

- **No physical parent ⇒ byte-identical to today.** This is the zero-change
  guarantee, and the tests must pin it.
- **Missing part** ⇒ AUTO for that property, plus one stderr warning naming
  the ship's leaf, the property and the missing part. The game keeps playing.
- **Headless / model not yet loaded** ⇒ the name is trusted as-is, mirroring
  how the rig trusts its template names. Consumers already ignore a part
  that is not rigged (`_live_part` returns None unless the name is in
  `posed_part_names`), so an unrigged SET part correctly means "does not move".
- Caching: `part_for_mount` caches on `(leaf, point)`. The explicit branch
  must not be cached under that key; it reads the property live, so an SPV
  edit takes effect at once (§7.6).

## 6. Consumers to switch

Each must pass the property identity, not only a point. Facts from a code
survey of this tree, 2026-10-17:

| Consumer | Where | Has the property? |
|---|---|---|
| mount follows its part (beam origin, SPV pin, shuttle-bay mount) | `subsystems.subsystem_world_position` (`subsystems.py:49`) → `articulation.part_transform_point` (:704) → `_live_part` (:755-784, `part_for_mount` at :774) | yes: `sub.GetProperty()`, or the `ObjectEmitterProperty` itself at :286. Thread it into `part_transform_point` |
| target offset | `subsystems.target_offset_world` (:86) | offset only; `is_authored_mount` (`part_severance.py:502`) matches it back via `_mounted_subsystems`, which holds the sub. Return the sub, not a bool |
| SPV selected-pin road | `_effective_world_pos(index)` (`ship_property_viewer_panel.py:1168`) | descriptor name |
| severed part destroys its subsystems | `part_severance._destroy_subsystems_on_part` (:517-540, call :533) | yes |
| emitter lights follow their part | `host_loop._articulate_emitter_light` (:1709) → `_part_pose_at` (:1677-1706) | the subsystem is in scope at :1811/:1824 from `_build_ship_emitter_cache`; emitter index `j` is enumerated at :1489 but not kept. ⚠️ Today the part is decided from the **light's own position, deliberately not the subsystem's** (docstring: "a light authored on a wing but parented to a body subsystem must still ride, and die with, the wing"). **Unchanged by this work**: keeps calling `part_for_mount` on its own position, never the subsystem's physical parent (§12) |
| running lights follow their part | `host_loop._articulated_running_lights` (:728-742) → `_part_pose_at` | **no**: `running_lights.lights_for` (:29-49) drops the property. Keep the name (or property) alongside each `RunningLightSpec` without changing `as_tuple()`, which feeds C++ |

`hull_bounds.py` and `glow_region_overlay.py` pass `part=` explicitly and are
unaffected. `part_transform_vector` has no callers.

## 7. Ship Property Viewer

Visual reference: brainstorm mockup `physical-tab-v6.html` (gitignored
`.superpowers/brainstorm/`), built on the live SPV stylesheet. Not
committed; this section is the authority.

### 7.1 Tabs

The **Subsystems** header bar is unchanged. Directly under it sits a
two-tab strip, **Functional** | **Physical** (Mark: under the header, not in
it). Functional is the default and is today's list, unchanged. Styling:
uppercase, the active tab gets a gold underline and faint gold tint, the
same colours as a chosen row. The tab choice is per-session SPV state.

### 7.2 Physical tab contents

- One row per **part**, in model node order, with a caret, rendered like a
  category row. Parts with nothing on them are still listed ("any part on the
  ship", Mark).
- Under each part, **flat**: every property resolved to it. Functional
  parents appear as ordinary rows beside their children, so no functional
  nesting shows here.
- What is listed: every subsystem and mount row the Functional tab lists,
  plus **running lights**. Running lights appear nowhere in the SPV today;
  they are new here and have no Functional-tab row. Light-volume rows are
  not listed, and neither are emitter-light rows (they keep their own AUTO
  placement, §6).
- Each row ends in a tag: **AUTO** (dim) or **SET** (gold). There is **no
  left rail** on SET rows (Mark). The gold "dirty" rail is the Functional
  tab's unsaved marker; on the Physical tab, unsaved state is carried by the
  Save button's pending count.
- A property with no authored position is not listed. Neither source lists
  one: `build_descriptors` (`ship_property_viewer.py:215`) skips subsystems
  without a position, and `running_lights.lights_for` skips unplaced lights.
  No consumer can act on one anyway, since every consumer starts from a point.
- Row click selects the subsystem exactly as the Functional tab does (same
  pin selection), so the hologram shows what you are moving. A running-light
  row has no pin, so clicking it highlights the row only. Hologram markers
  for running lights are separate future work (§12).

### 7.3 Context menu (subsystem or light row)

Reuses `#spv-ctxmenu` and gains a submenu (new to this menu):

- **Move to ▸** → every part, the current part ticked. Choosing one sets the
  physical parent (row becomes SET). On an **AUTO** row the ticked part is
  live: choosing it **confirms** the placement, writing SET to that same part,
  so "a human checked this" can be recorded (my call). On a SET row the
  ticked part is inert.
- **Reset to Auto**: removes the physical parent. Inert on AUTO rows.
- Existing items (Set Radius… etc.) stay as they are.

### 7.4 Missing parts (repair)

When a SET name is not a part of the loaded model:

- A **missing-part group** heads the list, labelled with the missing name and
  a warning glyph, holding every property set to it.
- **No target is pre-picked** (anti-goal, §3).
- Right-click on the missing-part row:
  - **Move all to ▸** → every part: retargets them all to one chosen part.
    This is the right answer when the user knows they belong together, e.g.
    a renamed body that deliberately holds the engines.
  - **Reset all to Auto**: each property finds its own nearest part. This
    handles a part split into several, and is what the game is already doing
    for them in the meantime.
- Right-click on one of its children still offers **Move to** and **Reset
  to Auto** for one-offs.
- After the last child leaves, the group disappears.

### 7.5 Saving

Save works as today (`ship_property_viewer_panel.py:2984-3068` →
`resolve_override_target(ship).write(leaf, edits)`). Physical-parent edits
join the edits list:

- SET → `(name, "SetPhysicalParent", (part,))`;
- Reset to Auto → the removal edit (§4.3).

They count in the save-confirm tally (`_pending_edits()`, :1861). AUTO
placements are never written.

### 7.6 Pending state, preview, undo

- A new pending dict, `_pending_physical_parent` (keyed like the other
  per-property pending dicts), with its `_saved_*` twin.
- **Add it to the `_snapshot_pending` / `_restore_pending` tuple**
  (:1205-1251), or undo silently skips it.
- A pending change previews live: the moved subsystem's pin follows its new
  part's pose, and the Physical tab re-groups at once. How preview reaches the
  resolver (setting the property directly versus an overlay) is the builder's
  call. It must not leak into the next mission if the SPV is cancelled.

### 7.7 Pose-preview lock

The mount-lock gate (:2426-2473) blocks mount authoring while an articulated
pose is previewed. Physical-parent edits author no position, so they are
**allowed** while posed (my call).

### 7.8 Model Parts pane

Stays exactly as it is, below the Subsystems pane: rigging (anchor, state
poses, breakage) and membership are different jobs (my call; raised with
Mark, not explicitly ruled). The two lists show the same part names. A later
merge is not precluded.

## 8. Behaviour after this ships, Bird of Prey worked example

1. Open the BoP in the SPV → Physical. `Impulse Engines` shows under `left
   wing` (port), and `Warp Engines` under `left wing01` (starboard), both
   AUTO. These are the measured placements.
2. Right-click `Impulse Engines` → Move to ▸ `birdofprey`; same for `Warp
   Engines`. Both show SET.
3. Save. The overrides file gains two `SetPhysicalParent("birdofprey")` calls.
4. In game: deflecting the wings no longer moves those two systems' mounts,
   and severing a wing no longer destroys impulse or warp. `Port Warp` /
   `Star Warp` still follow and die with their wings (AUTO, correct).

## 9. Testing expectations

- Zero-change: with no physical parents, every existing consumer test passes
  unmodified (`test_part_for_mount.py`, `test_articulation*.py`,
  `test_subsystem_part_parenting.py`, `test_target_offset_articulation.py`,
  `test_part_severance.py`, `test_running_lights*.py`).
- Resolver: SET wins; missing falls to AUTO and warns once; headless trusts
  the name; an SPV change is seen without a stale cache.
- Each consumer in §6 honours SET, including running lights through the host
  push. The exception is emitter lights, which must stay on their own-position
  placement even when their subsystem is SET (pin that with a test). Also the
  BoP §8 scenario end to end: severance does not take impulse/warp.
- Writer round-trip for both targets: set, replace, remove; stock unguarded,
  mod inside the guard; Python 1.5-safe emitted text (no `True`/`False`, no
  `import X as Y`).
- SPV: Physical rows/grouping/tags, Move to, Reset to Auto, missing-part
  group and both bulk actions, undo/redo of each, Save tally.
- The UI needs Mark's in-game look before the gate (memory: UI look first,
  gate last).

## 10. Out of scope: decals (IMMEDIATE follow-up)

Decals already carry an explicit physical binding: each placement names its
NIF **shape** (`2026-09-28-hull-name-decals-design.md`, `shape`), from which
the part follows via the mesh hierarchy. A missing shape is skipped with one
warning, the same failure policy as §5. No new relationship is needed.

The real gap is rendering: the projector works in the ship-body frame
(`p_body`, no `u_node_rest_fix`), so a decal on an articulated part slides as
the part moves (decal spec line 312). **The LC Intrepid needs this soon**
(Mark, 2026-10-17): its rig moves `wing left` / `wing right`. That makes it
an immediate follow-up, not a parked one. Also unverified: whether a decal
leaves with its part on severance.

## 11. Decisions

By Mark (2026-10-17)
- Two trees, kept and named separately; subsystems are not nested under parts.
- Physical tree = every part on the ship, rigged or not.
- Stored in the hardpoint file, behind the Dauntless check; the name contains
  "parent": `SetPhysicalParent`.
- Plain-name identity; no mesh fingerprint.
- Design for renames even though they "genuinely won't" happen.
- SPV: Functional/Physical tabs **under** the Subsystems header; the
  Physical tab lists subsystems flat under parts; right-click → Move to.
- Wording Auto / Set; no left rail on SET rows.
- Missing-part repair: no pre-picked target.
- Decal sliding: out of this work, immediate follow-up for the Intrepid.
- Emitter lights: unchanged, own-position AUTO, not listed; per-light
  physical parents only if it proves a real problem.
- No running-light hologram markers in this work.

Calls I made (check these)
- No inheritance down the functional tree: an untagged child is AUTO, not
  its parent's part.
- Running lights get physical parents and appear on the Physical tab.
- `DAUNTLESS_ENV` stays 1.
- Explicit typed setter on `TGModelProperty`, not the data bag.
- Physical-parent edits allowed during pose preview.
- Model Parts pane unchanged and separate.
- Headless (no model) trusts the name.
- Choosing the ticked part on an AUTO row confirms it as SET.
- Positionless properties are not listed (neither source yields them).
- Mod files: hand-written physical parents are overridden by the managed
  block; Reset writes `SetPhysicalParent(None)` when needed.

Left to the builder
- Exact removal-edit tuple, pending-dict keying, preview mechanism, label of
  the unplaceable group, submenu implementation in `#spv-ctxmenu`.

## 12. Follow-ups (not this work)

- **Decal sliding on articulated parts**: immediate, for the LC Intrepid (§10).
- **Per-emitter-light physical parents**: only if mis-placed emitter lights
  turn out to be a real problem (Mark, 2026-10-17). Emitter lights are placed
  by their **own** position, on purpose (`host_loop._articulate_emitter_light`
  docstring: "a light authored on a wing but parented to a body subsystem must
  still ride, and die with, the wing"), so one subsystem's lights can sit on
  different parts. If needed later: an indexed setter such as
  `SetLightEmitterPhysicalParent(i, "<part>")` plus a row per light. A SET
  subsystem must never drag its emitter lights along, because that would
  break the rule above.
- **Running-light markers on the hologram**: separate future work (Mark).
