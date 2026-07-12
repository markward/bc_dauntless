# Lift-door coordination / ownership (SP-D)

**Date:** 2026-07-12
**Status:** Design — approved, pending spec review
**Branch:** `feat/lift-door-ownership`
**Follows:** SP-D, the first deferred follow-up from the E1M1 character walk-on
(`docs/superpowers/specs/2026-07-07-e1m1-character-walk-on-design.md`, "Follow-ups
to pick up after this plan", item 1).

## Problem

The walk-on spec deferred the door with: *"the door is driven by the camera walk-on
path and this `AT_MOVE` path no-ops the builder's `LiftDoorAction`. Decide the
long-term owner."* Investigation found the deferred item understates it — there are
**four** defects, and the "coordination" one is a silent data race in the renderer.

### 1. Every lift cue animates every door on the bridge

`BridgeCutsceneController._update_doors` (`engine/bridge_cutscene.py:69`) throws away
the requested door name and plays the **bridge model's own embedded clip**:

```python
renderer.play_instance_node_anim(iid, 0, loop=False, reverse=False)
```

That embedded clip is not one door. Loading the NIFs:

| model | embedded clip 0 |
|---|---|
| `Dbridge.NIF` | **12 tracks** — all six door pairs (`door 02a/02b`, `03a/03b`, `04a/04b`, `05a/05b`, …) |
| `EBridge.nif` | **10 tracks** — all doors **plus `chair commander 01` and `chair commander 02`** |

So one officer stepping out of lift 1 currently opens every door on the Galaxy
bridge, and on the Sovereign bridge also moves both commander chairs.

### 2. Bridge-node animations silently clobber each other (the ownership bug)

Doors and **chairs** both animate the same bridge instance's node hierarchy, and the
native layer holds exactly **one** node-anim per instance:

```cpp
std::unordered_map<std::uint32_t, BridgeNodeAnim> g_bridge_node_anims;   // host_bindings.cc:318
...
inst->node_overrides = renderer::sample_node_overrides(a.clip, *m, t);   // :584 — assignment, not merge
```

`play_instance_node_clip(bridge, …)` therefore **overwrites whatever was playing**. A
door opening during a turn-to-captain kills the chair clip and vice versa;
`stop_instance_node_anim(bridge)` on chair reset kills any door mid-cycle; and two
doors can never be open at once. This is the real "coordination / ownership" issue.

### 3. `AT_MOVE` opens no door at all

`capture_move` (`engine/appc/bridge_placement.py:167`) extracts only the character's
walk clip from the builder sequence and drops the `LiftDoorAction`. E1M1's captain
gets a door only because the **camera** walk-on sequence happens to fire one. All
**15** `LiftDoorAction` sites in `MediumAnimations` — every crew walk-on and walk-off,
both bridges, lifts L1 and L2 — open nothing.

### 4. `GetAnimationLength()` returns 0.0

The SDK schedules the walk-**off** door relative to the walk clip's length:

```python
fTime = kAM.GetAnimationLength("db_PtoL1_P")            # PicardAnimations.py:145
pSequence.AddAction(pDoorAction, pAnimAction_Stand, fTime - 1.25)
```

Our `AnimationManager.GetAnimationLength` returns `0.0`, making that offset **−1.25 s**.

## SDK ground truth

Everything below is verified against `sdk/Build/scripts/`, not assumed.

**Doors are named external keyframe NIFs**, registered exactly like character clips:

```python
GalaxyBridge.PreloadAnimations()      kAM.LoadAnimation("data/animations/db_door_l1.nif", "doorl1")
SovereignBridge.PreloadAnimations()   kAM.LoadAnimation("data/animations/EB_door_l1.nif", "EB_Door_L1")
LoadBridge.PreloadCommonAnimations()  kAM.LoadAnimation("data/animations/DB_Door_L1.nif", "DB_Door_L1")
```

Both entry points run under `LoadBridge.Load` (`:107` and `:231`), so **every door name
the builders use already resolves through our `AnimationManager.path_for()`**.

**Each door clip drives exactly one door pair and closes itself.** `DB_door_L1.NIF` keys
`door 04a` + `door 04b` only, 3 keys over 1.0 s, returning to the start pose. That is
why not one of the 19 `LiftDoorAction` call sites passes the optional `pcDoorClose` /
`fTimeOpen` arguments: the clip **is** the open-and-close cycle. `LiftDoorAction` plays
its own inner sequence and returns 0, so the parent never waits on it — fire-and-forget
is correct.

**The SDK never arbitrates.** There is no busy-check, queue, or "is the node free" guard
anywhere in the 1228 SDK files. Doors just play; chair turns just play. The turned-chair
pose **persists** after its clip ends — that is why BC ships a dedicated *reverse* NIF
(`db_chair_H_face_capt_reverse`) to bring it back. BC's model: many named animations
coexist, each drives its own nodes, each **holds its last frame**.

**Builder sequences are authored to be played, not mined.** They carry
`AddCompletedEvent(...)` and `AppendAction(AT_SET_LOCATION_NAME, …)`, and E1M1 takes
`CommonAnimations.WalkCameraToCaptOnD(pCamera)` and plays it wholesale
(`E1M1.py:1836`). A sequence merely scanned for a clip name would need none of that.

**BC double-drives E1M1's L1 door, by design.** The camera sequence fires
`LiftDoorAction(pBridge, "DB_Door_L1", …)` and Picard's `MoveFromL1ToP1` fires
`LiftDoorAction(pBridge, "doorl1", …)` — **the same physical door under two registered
names**, both resolving to `DB_door_L1.NIF`. We do not suppress either.

## Architecture

Six components. One native change (rebuild required); the rest is Python.

### 1. Native — concurrent bridge-node clips

`g_bridge_node_anims` becomes a **set of active clips per instance**, keyed by the
clip's **resolved, case-normalized path**:

- `update_bridge_node_anims` samples every active clip for an instance and **merges**
  their node overrides into one map, instead of assigning one clip's samples wholesale.
  Clips touch disjoint node sets (`door 04a/04b` vs `console seat NN`), so the merge is
  unambiguous; on the rare overlap, insertion order decides (last writer wins).
- **Every clip holds its last frame** when it settles. One uniform rule, matching BC: the
  chair stays turned, and a door clip ends at rest so holding it is invisible. No
  door-specific retirement rule — that would be a distinction BC does not make, and it
  would silently break any door clip that did not happen to end at rest.
- Replaying an already-active path **restarts that clip in place**; it never stacks a
  second copy fighting over the same nodes. This is what makes E1M1's authored
  double-drive (`"DB_Door_L1"` + `"doorl1"`) benign — **path**-keying collapses the two
  name aliases; name-keying would let them collide.
- `stop_instance_node_anim(iid)` keeps its clear-all semantics (mission reset / teardown).

### 2. Doors play by name

`BridgeCutsceneController._update_doors` resolves the requested clip **name** through
`AnimationManager.path_for()` and calls `renderer.play_instance_node_clip(bridge, path,
loop=False, reverse=False)` — the identical route `BridgeNodeAnimController` already uses
for chairs. `play_instance_node_anim(iid, 0)` (the all-doors clip) is deleted.

Completion stays fire-and-forget. An unresolvable name completes the action, logs once,
and plays nothing — it must never stall a mission `TGSequence`.

### 3. `AT_MOVE` plays the builder sequence

`CharacterAction._queue_move` stops extracting a clip and `Play()`s the SDK's
`TGSequence`, so BC's own authoring drives the scene: the walk clip, the `LiftDoorAction`
**at its scheduled offset**, the door sound, the trailing `AT_SET_LOCATION_NAME`, and the
`CS_*` completion events. `AT_MOVE`'s own `Completed()` fires when the sequence completes
(via an engine-internal completion hook on `TGSequence` — not new SDK surface).

**The walk action is marked explicitly.** `AT_MOVE` tags the sequence's walk action — the
**last** action targeting the character anim node, which is `capture_move`'s existing rule
— and only that one routes to `BridgeCharacterAnimController`'s root-motion walk path
(deferring completion until the clip settles, and keeping today's reveal).

Every **other** character-node `TGAnimAction` keeps today's instant-complete behaviour.
This is load-bearing, not laziness: `EyesOpenMouthClosed` is *also* a character-node
`TGAnimAction` (a 0.1 s facial clip) and is the very dependency the door is scheduled off
(`AddAction(pDoorAction, pOpenEyes, 0.125)`). Routing it to root-motion playback would
drive the officer's whole skeleton from an eyes-and-mouth clip and stall the walk behind
facial animation **we do not support at all** (we render facial images, never facial
clips). Consequence: because our eyes action completes instantly rather than in 0.1 s, the
door fires ~0.1 s earlier than BC. Accepted.

Blast radius of the routing change is nil: character-node `TGAnimAction`s exist **only**
inside the `Bridge/Characters/` builders (148 of them; no mission constructs one), and no
current engine path plays those sequences — every consumer (idle gestures, hit reactions,
placement, turn, move) *extracts* clips instead.

### 4. `ET_CHARACTER_ANIMATION_DONE` → character state

**This event is handled nowhere in our engine today** (zero hits in `engine/` and the `App`
shim). It does not matter while nothing plays the builder sequences — but the moment
`AT_MOVE` does, it becomes load-bearing:

```python
pEvent.SetInt(App.CharacterClass.CS_HIDDEN)     # PicardAnimations.py:151
# SDK's own comment: "Add event to hide character after it gets into the turbolift"
```

Add the `ET_CHARACTER_ANIMATION_DONE` constant and dispatch it: on delivery to a character
destination, apply the carried state — `CS_STANDING`, `CS_SEATED`, `CS_HIDDEN`. Without
it, **every officer who walks off would stand in the turbolift forever.**

### 5. The bridge module's `LoadSounds()` — a documented deviation

`"LiftDoor"` (`sfx/door.wav`) is loaded **only** by `GalaxyBridge.LoadSounds()` /
`SovereignBridge.LoadSounds()` — and **nothing in the SDK calls them**. `LoadBridge.Load`
calls `CreateBridgeModel`, `ConfigureCharacters` and `PreloadAnimations` but not
`LoadSounds`, while its *unload* path does call `UnloadSounds()`. The SDK unloads a sound
it never loads.

**We cannot tell from the SDK whether BC's native engine calls it or whether this is a
shipped BC bug, and this spec does not pretend to know.** Either way the sound must be
loaded or `TGSoundAction("LiftDoor")` resolves to nothing and the door is silent. So our
bridge-load path calls the bridge module's `LoadSounds()`, restoring the pairing the
unload path already assumes. It loads exactly one sound, so the blast radius is nil.

### 6. `GetAnimationLength()` returns the real duration

Return the clip's true length (max track time), cached by name, so the walk-off door lands
at `fTime − 1.25` instead of −1.25 s. Blast radius is nil: `GetAnimationLength` is called
at 24 SDK sites, **all** inside `Bridge/Characters/` builders, **all** to schedule door
actions. Nothing else in the SDK uses it.

## Data flow

```
AT_MOVE("P1")  ──▶ resolve builder "DBL1MToP1" ──▶ MoveFromL1ToP1() ──▶ TGSequence.Play()
                                                                            │
   ┌────────────────────────────────────────────────────────────────────────┤
   ▼ (t=0)                    ▼ (dep pOpenEyes +0.125s)                     ▼ (on complete)
 EyesOpenMouthClosed     LiftDoorAction("doorl1")                    CS_STANDING event
 (instant-complete)             │                                    AT_SET_LOCATION_NAME
   ▼                            ├─▶ TGAnimAction(bridge node,"doorl1")      │
 walk TGAnimAction  [MARKED]    │      └▶ path_for → play_instance_node_clip ▼
   └─▶ walk controller          └─▶ TGSoundAction("LiftDoor")         character state
       (reveal + root motion,                                          + location set
        defers completion)
```

## Error handling

Every step degrades rather than raising: an unresolved door name plays nothing and
completes; a missing renderer (headless) completes inline; a builder that raises completes
the action inline. A mission `TGSequence` must never stall on a door.

## Testing

**Python units.** Door name → path resolution, including both aliases of the L1 door.
A door clip and a chair clip **coexisting** (the regression that exists today). Replaying
the same path restarts rather than stacks. Settled clips hold their last frame.
`GetAnimationLength` returns real durations and the walk-off door offset is positive.
`ET_CHARACTER_ANIMATION_DONE` applies `CS_STANDING`/`CS_SEATED`/`CS_HIDDEN`. `AT_MOVE`
plays the sequence, completes **exactly once**, and is headless-safe.

**C++ ctest** for the concurrent-clip merge.

**Gate:** `scripts/check_tests.sh` green; no new `tests/known_failures.txt` entries.

**GUI verify:** E1M1 walk-on — lift 1's door opens (once), the **other five door pairs do
not move**, and the chairs do not move; the door is audible. A crew walk-off to the
turbolift opens the door on time and the officer **disappears** into the lift. A
turn-to-captain overlapping a door cycle: both survive.

## Out of scope (explicit follow-ups)

- **Facial / eye animation** (`eyes_open_mouth_close`, `twitch`). We render facial images,
  never facial clips. Component 3 deliberately leaves these instant-complete.
- **Non-player bridges** (Cardassian, Klingon, Romulan, Ferengi, Kessok sets). The
  mechanism is general; only DBridge and EBridge are verified here.
- The remaining walk-on follow-ups: SP-A (concurrent `AT_MOVE` overwriting `_active[iid]`),
  SP-B (other-mission `AT_MOVE` sweep).

## Related memories

`project_e1m1_character_walkon`, `project_bridge_character_animation_shipped`,
`project_bridge_character_placement`, `feedback_sdk_drives_everything`,
`feedback_no_invented_mechanism_stories`, `feedback_host_bindings_build_target`.
