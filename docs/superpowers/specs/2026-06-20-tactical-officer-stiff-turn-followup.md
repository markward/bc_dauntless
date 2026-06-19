# Tactical Officer Rigid Turn — NIF-Reader Follow-up

**Date:** 2026-06-20
**Status:** Queued follow-up (deferred from the bridge-node-animation branch).
**Context:** The bridge node animation project (chairs + doors + officer-seat coupling)
shipped working: chairs rotate, doors lift, the officer-seat coupling is correct, and
Helm / standing crew / the whole E-bridge turn correctly. The ONE remaining imperfection
is the **D-bridge Tactical officer (Felix): he rotates to face the captain via the chair,
but as a rigid mannequin** — no spine/head/arm articulation — because his body-turn clip
fails to load.

## Root cause (confirmed)

`db_face_capt_t.nif` (Felix's `TurnAtTTowardsCaptain` body clip) **parses to entirely
empty** through our NIF reader: every track's rotation, translation, AND visibility keys
load as **zero**, despite the file being 16 KB with dozens of `NiKeyframeData` /
`NiVisController` blocks. Verified via `load_animation_clips`:

| Clip | NIF ver | Vis controllers | Loads as |
|---|---|---|---|
| `db_face_capt_t` | **3.1** | **41** | **dur 0.0, ROT 0, TRANS 0, VIS 0** (BROKEN) |
| `db_face_capt_h` (Helm) | 3.1 | 0 | dur 0.533, ROT 198, TRANS 11 (OK) |
| `db_face_capt_t_reverse` | 3.0 | 41 (has vis) | dur 0.533, ROT 216, TRANS 18 (OK) |

So it is **NOT** a version issue (`db_face_capt_h` is also v3.1 and loads) and **NOT** the
Euler-rotation gap (the `xyz_rotations` arrays are also empty — see "Ruled out" below). The
discriminating signature is **NIF v3.1 + `NiVisController` blocks** → the reader appears to
**mis-align while parsing the v3.1 vis-controller/vis-data blocks, zeroing every subsequent
keyframe-data read** for that file. `db_face_capt_h` escapes it (no vis blocks);
`db_face_capt_t_reverse` escapes it (v3.0 vis layout, which the reader handles).

This is a byte-level NIF binary-parsing bug, independent of the bridge-animation work, and
fixing it would also repair any other v3.1 clips that carry visibility controllers (facial
blink/eye animations are common, so this likely affects more than just Felix).

## Where to look

- `native/src/nif/src/blocks/animation.cc` — `NiVisController` (line ~208) and `NiVisData`
  (line ~277) parsers; and `parse_NiKeyframeData_body` (line ~126). Suspect the v3.1
  vis-controller/vis-data field layout reads the wrong number of bytes, shifting the stream.
- `native/src/nif/src/reader.cc` — block iteration / type-name dispatch for v3.1 (no
  block-type table). Confirm whether a mis-sized block silently desyncs subsequent reads.
- **Repro (headless, no GUI):**
  ```
  PYTHONPATH=build/python python3 -c "import _dauntless_host as h; \
    c=h.load_animation_clips('game/data/animations/DB_face_capt_T.NIF')[0]; \
    print(c['duration'], sum(len(t.get('rotation') or []) for t in c['tracks']))"
  ```
  Expect `0.0 0` (broken) today; a fix makes it `~0.533 198`-ish. Cross-validate the loaded
  rotations against `DB_face_capt_T_reverse.NIF` (quaternion-encoded, same motion reversed):
  forward last-frame pose ≈ reverse first-frame pose.

## Ruled out (do not re-investigate)

- **Euler XYZ rotation (rotation_type 4):** added a converter to `animation_build.cc`
  (`apply_keyframe_data`) and it did NOT trigger — `db_face_capt_t`'s `xyz_rotations` are
  also empty, confirming the data never reaches the struct (the mis-parse is upstream, in
  the block reader). The Euler converter was reverted as unvalidated; if a genuinely
  Euler-encoded clip turns up later, that converter (axis order Z·Y·X, validate against a
  quaternion twin) is the starting point.
- Duplicate node names (fixed separately — `resolve_overridden_node`).
- The coupling math / instance identity / path resolution (all verified correct via the
  now-removed `BRIDGE_COUPLING_DEBUG` instrumentation).

## How this surfaces in the bridge code (no code change needed once the loader is fixed)

`bridge_character_anim._body_turns_officer` classifies an officer as **chair-driven** when
its forward body clip has no rotation. Today `db_face_capt_t` loads empty → Felix is
chair-driven (rigid chair-carry). **Once the loader is fixed**, `db_face_capt_t` will load
with real rotation → Felix auto-classifies as **body-driven** (like Helm) and articulates
through his own clip — no change to `bridge_character_anim` or `bridge_node_anim` required.
(If `db_face_capt_t` turns out to only articulate the head/spine and rely on the chair for
the base turn, a hybrid — couple AND play the body clip — may be wanted; decide after
seeing the loaded clip's actual root vs head deltas.)

See [[project_bridge_character_animation_shipped]].
