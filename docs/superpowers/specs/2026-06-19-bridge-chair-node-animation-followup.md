**SUPERSEDED by docs/superpowers/specs/2026-06-19-bridge-node-animation-design.md (implemented 2026-06-19).**

# Bridge Chair-Node Animation — Queued Follow-up

**Date:** 2026-06-19
**Status:** Queued (next project after turn-to-captain merges). Findings captured so they
need not be re-investigated.
**Context:** Turn-to-captain (officers turn their BODY to face the captain on station-select,
hold, and turn back) is merged. STANDING officers (XO/Science/Engineer on D-bridge, XO on
E-bridge) and **Helm** turn correctly. This follow-up resolves the two remaining gaps, both of
which are **chair-driven** in the original game.

## Known gaps this project fixes

1. **Tactical does not turn TO the captain (turns back only).** `db_face_capt_t` — Tactical's
   forward body-turn clip — is **EMPTY in BC's data** (41 tracks, **0 rotation keys**; dur 0.0s).
   Its reverse, `db_face_capt_t_reverse`, has 216 keys (which is why "turns back but not to").
   In BC, Tactical's *forward* turn comes entirely from the rotating **chair** (`db_chair_T_face_capt`
   on the bridge set), which carries the seated officer. Without chair animation, Tactical has no
   forward-turn source.
2. **Chairs never rotate.** Seated officers' chairs are part of the static bridge mesh; the
   original rotates the chair's seat node, and the officer rides it. Helm currently turns its
   *body* (its body clip is self-contained), but its **seat** stays static — a visible compromise.

## SDK facts (verified)

- Seated `TurnCaptain` builders are multi-action: the officer's **body** clip on the character node
  (e.g. `db_face_capt_h` Helm, `db_face_capt_t` Tactical) **plus** the **chair** clip on the
  **bridge set node** (`pBridgeNode`), e.g.:
  `MediumAnimations.TurnAtHTowardsCaptain` → `TGAnimAction(pCharacter.GetAnimNode(), "db_face_capt_h")`
  AND `TGAnimAction(pBridgeNode, "db_chair_H_face_capt")`.
- The chair clips (`db_chair_*_face_capt.nif`, `eb_chair_*`) rotate a **`console seat NN`** node
  ~60° about the bridge vertical, and bake a `Camera captain` view-path (the zoom camera).
- The bridge `assets::Model` already carries its **node hierarchy** (`nodes` vector with
  `local_transform`). The chair seat nodes live there.

## Why it's a real renderer feature

Rotating the chair needs **non-skinned node-keyframe animation** — the renderer currently
**ignores** node animation on non-skinned models. This is the deferred "bridge door animations"
item (`native/src/host/docs/deferred_work.md` #38: `DBridge.NIF`'s 12 `NiKeyframeController` blocks
are unwired). Building it also unlocks bridge **doors** and ship **engine flares** (same controller
type). So this project is foundational, not chair-specific.

## Implementation sketch (for the future spec)

1. **Non-skinned node animation (the foundation):** play a clip on a non-skinned instance (the
   bridge), sampling named nodes' transforms per frame and overriding them in the node-walk render
   path. Reuses the existing `Model::animations` + the keyframe sampler; the new part is applying
   sampled node transforms to a non-skinned instance's node hierarchy at draw time.
2. **Chair on the bridge:** on `MenuUp`, play `db_chair_*_face_capt` on the bridge instance's seat
   node (ignore the baked `Camera captain` track — it's the zoom camera, not the chair); reverse on
   `MenuDown`.
3. **Officer-seat coupling:** query the seat node's (animated) world transform from the bridge and
   rotate the seated officer around that pivot so body + chair move together. This finally gives
   Tactical a forward turn (the chair carries it) and makes Helm's seat rotate with the body.
4. **Decision to make in design:** whether the seated officer's body clip still plays *on top* of
   the chair rotation (Helm has a real body clip; Tactical's is empty) or whether the chair pivot
   alone suffices — i.e. how body-clip and chair-rotation compose for each station.

## Current behavior to preserve

- Standing officers + Helm turn their bodies and hold; reverse on close. The root-translation
  anchor in `sample_pose_over_base` keeps `db_face_capt_h`'s root track from displacing the officer.
  Do not regress these when adding chair coupling.

See [[project_bridge_character_animation_shipped]].
