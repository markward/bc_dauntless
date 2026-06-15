# SDK-Driven Bridge Officer Placement — Step 4 Design

**Date:** 2026-06-15
**Status:** Approved (design); implementation pending plan
**Part of:** the SDK-driven bridge initialization project (spec step 4)
**Builds on:** `2026-06-15-sdk-driven-bridge-mesh-step3-design.md`

## Problem

Steps 1–3 made bridge initialization SDK-driven: the real
`sdk/Build/scripts/LoadBridge.py::Load(name)` runs end-to-end against loud
stubs, creates the 5 standard crew + 3 random extras as logical
`CharacterClass` objects in the `"bridge"` set, and step 3 turned the
SDK-created `"bridge"` object into the rendered bridge mesh
(`host_loop._realize_bridge_model`).

**Officers do not render yet.** The old shortcut that built officer render
instances was deleted in steps 1–2:
`engine/bridge_officers.py::place_officers` / `_place_one`, the
`native/src/renderer/placement_map.{h,cc}` location→clip table, the
`resolve_placement` binding, and the `_BRIDGE_IDENTITY_MAT4` X-flip transform.
The bridge crew are absent by design until this step rebuilds placement on the
SDK path.

## Goal

For each SDK-populated `CharacterClass` in the `"bridge"` set, render a posed,
per-character skinned officer at its station — SDK-faithfully, with **no
reintroduced invented table** — by feeding the already-working SP1/SP2 skinned
renderer through the **kept** host bindings:

```
assemble_officer(body, head, body_tex, head_tex, placement_nif, sample_at_start) -> model handle
create_bridge_instance(model) -> iid
set_world_transform(iid, mat4)
set_instance_animation(iid, 0, loop=False, sample_at_start)   # play placement clip once, hold
```

`compose_officer_model` and the SP1/SP2 skinning/pose pipeline are **kept and
not modified** — they already produce coherent posed bodies in headless PNG
tests.

## The crux: where placement comes from

The SDK's authoritative station-placement logic is
`Bridge/Characters/CommonAnimations.py::SetPosition(pCharacter)` — a switch on
`pCharacter.GetLocation()` (the location alias each officer's
`ConfigureForGalaxy` sets via `SetLocation`, e.g. `"DBTactical"`). Each matched
branch does:

```python
kAM.LoadAnimation("data/animations/db_stand_t_l.nif", "db_stand_t_l")
pSequence.AppendAction(App.TGAnimPosition_Create(pAnimNode, "db_stand_t_l"))
```

and the L1 "moving-away" branches additionally call `pCharacter.SetHidden(1)`.

`SetPosition` is **never called from any SDK Python** — the original C++ engine
invokes it post-load when it positions each character. Our host legitimately
invokes the same SDK function to **capture** the selection. This executes the
SDK's own mapping rather than reinventing it — the same recording pattern step 3
used to turn `g_kModelManager.LoadModel` into `env_for`.

**Decision (approved):** run the real SDK `SetPosition(char)` under *recording*
animation surfaces and read back the clip it selects. No location→clip table in
our code.

## Architecture & components

### Recording surfaces in `engine/appc/` (headless; no renderer import)

These turn two currently-stubbed symbols faithful, mirroring step 3.

- **`engine/appc/animation_manager.py` (new).** `AnimationManager` with
  `LoadAnimation(path, name)` recording `name -> path` (data-root-relative,
  insertion-preserving) and `path_for(name) -> str | None`. Registered as
  `App.g_kAnimationManager`. Idempotent re-`LoadAnimation` of the same name is a
  no-op overwrite (matches the SDK calling `LoadAnimation` once per matched
  branch).
- **`TGAnimPosition_Create(animNode, name)` (in `engine/appc/actions.py`).** A
  recording factory returning a `TGAnimPosition` action (a `TGAction` subclass)
  that stores `name`. It is appended to the SDK's `TGSequence`, which is
  harmless headless — the sequence is never played. The capture reads the
  action's `name`, not the sequence execution.

### Placement-capture helper `engine/appc/bridge_placement.py` (new; headless)

```python
def capture_placement(character) -> dict | None:
    """Run the SDK's CommonAnimations.SetPosition(character) under the recording
    animation surfaces and return the placement it selects.

    Returns {"clip_nif": <data-root-relative path>,
             "hidden": bool,
             "sample_at_start": bool}
    or None when the character has no location / no matching SetPosition branch
    (nothing to place)."""
```

- Imports `Bridge.Characters.CommonAnimations` (pure SDK Python; no renderer).
  SDK is importable in tests via `conftest._SDKFinder` and live via
  `tools.mission_harness.setup_sdk`.
- Resets the recording surfaces, calls `SetPosition(char)` (which returns the
  built `TGSequence`), then reads the selected clip name from that sequence's
  single appended `TGAnimPosition` action (`GetAction(GetNumActions()-1).name`)
  and resolves it through `g_kAnimationManager.path_for(name)`. The matched
  `SetPosition` branch creates exactly one `TGAnimPosition`; an unmatched
  location appends none → `GetNumActions() == 0` → return `None`.
- `hidden` = truthy `character.IsHidden()` after `SetPosition` (the L1 branches
  set it).
- `sample_at_start` = **clip-name heuristic**: clip names whose station end is
  frame 0 — `*StoL1*`, `*EtoL1*`, `*L1to*` (the move-from-station clips) — map
  to `True`; in-place `stand`/`seated` clips map to `False`. Keyed off the SDK's
  own clip names, refined during live verify; not a location table.
- Returns `None` if no clip was recorded (location empty / unmatched).

### Host placement `engine/host_loop.py::_place_bridge_officers(controller, r)`

Module-level, renderer-side. Called from `_after_mission_loaded` immediately
after `_realize_bridge_model(controller, r)`.

```
bridge = App.g_kSetManager.GetSet("bridge"); if None: return
destroy + clear controller.officer_instances   # leak-free swap
for off in bridge.GetObjectsByType(CharacterClass):
    if off._render_instance is not None: continue       # double-place guard
    p = capture_placement(off)
    if not p or p["hidden"]: continue
    ap = off.appearance()
    if not ap["body_nif"]: continue
    model = assemble_officer(abs(body_nif), abs(head_nif),
                             abs(body_tex), abs(head_tex),
                             abs(p["clip_nif"]), p["sample_at_start"])
    iid = create_bridge_instance(model)
    try:
        set_world_transform(iid, OFFICER_TRANSFORM)
        set_instance_animation(iid, 0, loop=False, sample_at_start=p["sample_at_start"])
    except Exception:
        destroy_instance(iid); raise        # no orphaned tracked-nowhere instance
    off._render_instance = iid
    controller.officer_instances.append(iid)
```

- Enumeration via `GetObjectsByType(CharacterClass)` covers the 5 standard crew,
  the 3 random extras, and any mission-added guest (e.g. Picard via
  `SetLocation`) — satisfies the "enumerate all CharacterClass, not just the 5"
  requirement.
- Per-officer `try/except` (logged) so one bad NIF/clip cannot abort the rest.
- Absolute path resolution joins data-root-relative SDK paths to
  `PROJECT_ROOT/game/...`, the same way `_realize_bridge_model` resolves the
  bridge NIF.

## Data flow

```
_after_mission_loaded:
  _realize_bridge_model(controller, r)        # step 3 — bridge mesh instance
  _place_bridge_officers(controller, r)        # NEW — officer instances
      for off in bridge.GetObjectsByType(CharacterClass):
          capture_placement(off)               # runs SDK SetPosition under recorders
          assemble_officer / create_bridge_instance / set_world_transform / set_instance_animation
  dump_stub_summary()                          # g_kAnimationManager + TGAnimPosition_Create
                                               #   drop off the [BRIDGE-STUB] SUMMARY
```

## Transform / orientation (explicit live-tuning anchor)

Start from the SP2-validated transform — negate-X-basis identity, row-major
`[-1,0,0,0; 0,1,0,0; 0,0,1,0; 0,0,0,1]` (det<0) — the exact matrix the deleted
layer used and the skinned sub-pass was validated against. The placement clip's
root track carries the station offset, so per-officer translation is **not** set
here; the instance sits in bridge-set identity space like the bridge mesh.

The X-flip assumption lived in the *replaced* placement layer, so this is the
designated re-verification point: with the SDK now driving real poses/positions,
the orientation is expected to need live iteration with Mark. The transform is a
single named module constant (`OFFICER_TRANSFORM`) so tuning/flipping it is a
one-line change. The skinned bridge sub-pass already renders culling-off (the
X-flip det<0 × left-handed bone palette det<0 nets det>0, which would invert
winding under back-face cull) — kept, unchanged.

## Idempotency & leak-free (step-3 discipline)

- `controller.officer_instances: list[InstanceId]` — new, initialised next to
  `controller.bridge_instance` in the controller constructor.
- `_place_bridge_officers` destroys every prior officer instance
  (`r.destroy_instance`) and clears the list **before** placing, so a mission /
  bridge-config swap recycles cleanly.
- `reset_sdk_globals()` already clears `g_kSetManager._sets` every swap, so each
  load enumerates a fresh set of `CharacterClass` objects (fresh
  `_render_instance is None`), and the destroy-prior step always recycles the
  previous load's instances.
- Per-character `_render_instance` tag guards against double-placement within a
  single load, matching `_realize_bridge_model`'s `obj.render_instance is None`
  reuse check.

## Testing (focused subsets only — never the full suite; it OOMs the host)

- **`tests/unit/test_bridge_placement_capture.py` (new):** `capture_placement`
  returns the correct clip for `DBTactical` / `DBHelm` / `DBCommander`; the
  frame-0 heuristic flags `db_StoL1_S` / `db_EtoL1_s` as `sample_at_start=True`
  and `db_stand_*` as `False`; returns `None`/`hidden` for the L1 branches and
  for an empty location.
- **`tests/unit/test_place_bridge_officers.py` (new):** fake renderer; asserts
  the per-officer `assemble_officer → create_bridge_instance →
  set_world_transform → set_instance_animation` call sequence and arguments; the
  idempotency / destroy-prior matrix on swap; and that **all** `CharacterClass`
  in the set are enumerated (seed a guest in addition to the standard crew).
- **`tests/integration/test_sdk_bridge_load.py` (update):** assert
  `g_kAnimationManager` and `TGAnimPosition_Create` are now **absent** from the
  fired-stub set (they became faithful recording surfaces).
- **C++ untouched** → no `cmake` rebuild; existing skinned-bridge tests stay
  green.
- **Live verification by Mark** — no synthetic desktop input, no full-screen
  capture. Build artifact `./build/dauntless`.

## Out of scope

The open renderer bug — officer heads render as blocky/untextured
"lego/skeleton" (`felix_head.tga` not landing as a recognizable face) — is a
**separate** renderer-pipeline issue independent of bridge init. Step 4 makes
officers visible again but does **not** fix it.
