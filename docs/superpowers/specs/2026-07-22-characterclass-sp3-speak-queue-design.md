# CharacterClass SP3 — SpeakQueue + PhonemeMap + Jaw

**Status:** design approved 2026-07-22
**Sub-project 3 of 4** in the faithful CharacterClass reimplementation
(`project_characterclass_reimplementation`). SP1 (state model) and SP2
(AnimationQueue) are merged to `main`.
**Branch:** `feat/characterclass-sp3-speak-queue` (off `main`)

## 1. Purpose

Put a faithful, owned **SpeakQueue** and **PhonemeMap** in front of the existing
speech + lip-sync backends — exactly as SP2 put the animation-record queue in
front of the clip player — and implement the now-solved **jaw motion** (BC's
repurposed `Bip01 Ponytail1` bone) so bridge-officer mouths open in lock-step
with the `SpeakA/E/U` texture swap.

Same "own + consolidate" architecture as the rest of the reimplementation:
`CharacterClass` owns the sub-objects; the live-verified host controllers
(`engine/appc/crew_speech.py`, `engine/lip_sync.py`, `engine/lip_sync_runtime.py`,
`engine/appc/lip_visemes.py`, `engine/appc/lip_data.py`) stay as the execution
**backends** the sub-objects call — NOT dissolved or rewritten.

Tier-0 authority: `docs/engine/characterclass-reference.md` §4.11 (Speaking &
sound). Jaw mechanism: reverse-engineered and cross-validated
(`project_lipsync_re_findings`, the ✅ SOLVED jaw block).

## 2. Evidence that right-sizes the work

Grepped across the 1228 SDK scripts:

| Surface | SDK call sites | Consequence for SP3 |
|---|---|---|
| `SpeakLine` | 53 | workhorse — already routes to `crew_speech.emit` |
| `SayLine` | 99 | workhorse — already routes to `crew_speech.emit` |
| `IsSpeaking` | 23 | re-entrancy guard — backed by `crew_speech.is_speaking` |
| `IsReadyToSpeak` | 4 (all Science) | used in a `if (… or IsReadyToSpeak()): return 0` guard |
| `AddSoundToQueue` | 0 | implement faithfully but unexercised |
| `IsSomeoneSpeaking` | 0 | implement for completeness |
| `SpeakHelper` | 0 | internal helper (the clear-and-play routine) |
| `SpeakLineNoFlap` | 0 | out of scope (no caller) |
| `AddPhoneme` / `UsePhonemeGroup` | 0 | phoneme group is the compiled default; shared/global |

Two live fidelity gaps fall out of this:

1. **`SpeakLine`/`SayLine` don't clear the interruptable anim set today.** BC's
   SpeakHelper clears categories `0,1,5,6` before playing (§4.11). Speaking
   should cancel idle fidgets/glances. SP3 adds that clear via SP2's
   `ClearExtraAnimations`.
2. **`IsReadyToSpeak` returns a hard `1`.** In
   `Bridge/ScienceCharacterHandlers.py` (lines 712/878/1019/1148) the guard is
   `if (pScience.IsHidden() or pScience.IsAnimatingNonInterruptable() or
   pScience.IsSpeaking() or pScience.IsReadyToSpeak()): return 0`. A constant
   `1` makes **all four Science callout blocks always early-return** — a silent
   stub bug. Faithful queue state (`0` when nothing is pending) unblocks them.

Also confirmed for the vestigial cleanup: `AT_SET_LOCATION_NAME` routes through
`SetLocation` → `GetLocation()` (`_data["Location"]`), and `SetLocationName`
(which writes `self._location_name`) has **0 SDK call sites** and no functional
reader — fully dead.

## 3. PhonemeMap model (decided in brainstorm)

Mark chose the **discrete 3-level faithful model** over the shipped continuous
acoustic approximation. BC drives both channels (jaw bone + face texture) from a
single discrete openness signal; the jaw has exactly three authored angles
(`mouth_close`≈114° / `MouthOpenPartly`≈116° / `MouthOpen`≈121°). One signal
therefore unifies jaw and texture.

`PhonemeMap` maps a `.LIP` phoneme `code` → a **Viseme** value type
`(name, jaw_angle_deg, texture_slot)`. Four visemes across BC's three jaw levels:

| viseme | jaw | texture | phonemes (from the recovered code→phoneme table) |
|---|---|---|---|
| `closed`  | 114° | `neutral` | sil (0), word-closure (1), bilabials M/B/P (40/29/43) |
| `partly`  | 116° | `e`       | most consonants; reduced vowels IH/EH/ER/EY (81/121/66/65/32) |
| `open`    | 121° | `a`       | open vowels AA/AH/AE/AO (56/64/115/139/59) |
| `rounded` | 116° | `u`       | rounded W/OW/UW (50/42/48) — pursed lips, partly-open jaw |

The `rounded` viseme gives the `SpeakU` texture a home (rounding is orthogonal to
openness), so no shipped shape is wasted, while the jaw stays on its three
authored levels.

**Caveat (recorded honestly):** the exact code→viseme *bucketing* is our
linguistic reconstruction from the empirically recovered code→phoneme table
(`project_lipsync_re_findings`), **not** BC's compiled phoneme group. The model
is structurally BC-exact; the per-code assignment is tunable data. Mark can trace
`FUN_00706c60` later to make the bucketing byte-exact if desired.

The table ships as data (`engine/appc/lip_phonemes.json`) so tuning needs no code
change. The acoustic `lip_visemes.json` is **retired as the default source**
(kept only if a plan-time A/B toggle proves useful).

## 4. Architecture — three workstreams, one branch

Sequenced low-risk → high-risk. Each workstream is a small piece reviewed before
the next (`subagent-driven-development`), with a running ledger.

### 4.1 SpeakQueue — owned sub-object over `crew_speech` (Python)

New `engine/appc/speak_queue.py`: `class SpeakQueue`, owned by `CharacterClass`
(fills the existing `self._speak_queue` slot). A **thin faithful facade** — the
single-channel `crew_speech` bus stays the backend; per-character concurrency
(BC gives each character its own queue and lets two officers overlap) stays out
of scope, tracked separately as the speech-architecture divergence noted in
`crew_speech.is_speaking`.

Interface (what it does / how it's used / what it depends on):

- `speak_line(db, line, priority)` and `say_line(db, line, addressee, flag,
  priority)` — BC's **SpeakHelper**: (a) clear the interruptable anim set via the
  owner's `ClearExtraAnimations()` (cats 0,1,5,6); (b) route to
  `crew_speech.emit(name, db, line, priority)`; (c) return the line duration.
- `is_speaking()` → `crew_speech.is_speaking(name)` (unchanged).
- `is_ready_to_speak()` → `1` iff a sound is queued and ready but not yet
  playing; `0` when the queue is idle. Backed by real queue state (fixes the
  Science guard).
- `add_sound_to_queue(pSound, sound_type, data)` → BC `0x0066CB90`: no-op unless
  `pSound`; if `sound_type == 2` and ready/speaking → play immediately; else
  enqueue. Implemented faithfully; no SDK caller exercises it.
- `IsSomeoneSpeaking` (global) → active-speaker count > 0. The bus serializes, so
  the count is `{0,1}`; exposed as a `CharacterClass` static/classmethod.

`CharacterClass.SpeakLine` / `SayLine` / `IsSpeaking` / `IsReadyToSpeak` forward
to the owned queue. Depends on: `crew_speech` (backend), the owner's
`ClearExtraAnimations` (SP2).

### 4.2 PhonemeMap — discrete code→viseme surface (Python data)

New `engine/appc/phoneme_map.py`: `class PhonemeMap` (§3). A shared/global default
(BC's phoneme group is compiled and shared by all rigs; the never-called
`AddPhoneme`/`UsePhonemeGroup` mean the default is the only group). `CharacterClass`
holds a reference to the shared instance via a `self._phoneme_map` slot; all
characters point at the same default.

- `viseme_for(code) -> Viseme` — unknown code → `closed`.
- Backed by `engine/appc/lip_phonemes.json` (code→viseme name), loaded once.

`engine/lip_sync.py` (the controller) refactors from continuous-weight blending
to **discrete-viseme + crossfade**: `LipTimeline`/`LipSyncController` resolve each
`.LIP` segment through `PhonemeMap` to a `(jaw_angle, texture_slot)` pose and
crossfade between successive poses over the existing ~0.1s window (`_xfade`). The
sink signature grows a jaw channel (see 4.3). `viseme_weights`/`dominant_pair`
(`lip_visemes.py`) are removed from the live path.

### 4.3 Jaw animation — drive `Bip01 Ponytail1` (C++ skinning/renderer + signal)

The viseme's `jaw_angle` rotates BC's repurposed jaw bone in lock-step with the
texture, crossfaded on the same easing.

- **Skinning:** stop rigid-welding `Bip01 Ponytail1` in
  `native/src/assets/src/model_compose.cc` (`weld_head_bones`) so its local
  rotation is per-instance drivable. Ponytail1 is already an appended,
  body-missing bone (`project_bc_character_rigid_skinning`), so this drives an
  existing distinct bone — it does **not** re-plumb the neck seam.
  `native/tests/renderer/head_weld_seam_test.cc` is the regression net.
- **Drive:** new host binding `set_officer_jaw(iid, angle_deg)` (or an added arg
  on `set_officer_face`); the skeleton pose sets Ponytail1's local rotation
  before palette build (`native/src/scenegraph/src/world.cc` +
  `native/src/host/host_bindings.cc`).
- **Direct-angle-set, not clip playback** (decided): the `mouth_*.NIF` clips are
  static single-pose holds, so setting the bone's local rotation to the target
  angle reproduces them without a clip-playback subsystem. The exact rest
  axis/rotation is confirmed with the `probe_mouth.cc` / `probe_skin.cc` tools
  before wiring. `mouth_flapping` (the no-`.LIP` sweep) falls out of the
  random-phoneme fallback stepping through buckets + crossfade.
- Requires `cmake -B build -S .` reconfigure + `dauntless` rebuild + Mark's live
  pass (player-visible).

### 4.4 Data flow (end to end)

```
crew_speech.emit(name, db, line, prio)
  → CrewSpeechBus.speak (accepted)
    → _notify_speech(name, wav, duration, now)
      → LipSyncRuntime._on_speech
        → parse .LIP (or random-phoneme flap for a no-.LIP voice line)
          → LipSyncController.start(segments, t0)
            → per frame: PhonemeMap.viseme_for(code)
                         → (jaw_angle, texture_slot), crossfaded
              → sink: renderer.set_officer_face(iid, tex_a, tex_b, mix)
                      renderer.set_officer_jaw(iid, angle_deg)
```

## 5. Vestigial cleanup (SP2 fold-in)

Each removal grep/test-confirmed before deletion (§2 confirms the third):

- `self._anim_queue` dead slot — remove; update the slot-existence assertion
  (`tests/unit/test_character_state_flags.py:125`).
- lowercase `set_current_animation` / `clear_current_animation` shims — remove;
  migrate `tests/unit/test_character_animation_state.py` (the SP2-flagged
  transitional tests) to the queue model.
- `self._location_name` + `SetLocationName` — 0 functional readers / 0 SDK call
  sites; remove. `test_at_set_location_name_updates_location` asserts
  `GetLocation()` and is unaffected.

## 6. Error handling

- SpeakQueue best-effort like `crew_speech` — never raises out of a speak entry
  point (headless/early-boot safe). `ClearExtraAnimations` failures are swallowed.
- PhonemeMap unknown code → `closed` (mouth shut), never an exception; the JSON
  loads once and a malformed/missing entry degrades to `closed`.
- Jaw binding: an unresolved instance or missing Ponytail1 bone is a no-op
  (texture path still runs), matching the existing `set_officer_face` tolerance.

## 7. Testing

- **SpeakQueue** (Python units, patch `host_io._h` / `crew_speech`): emit funnel;
  interruptable-set cleared on speak; `is_ready_to_speak` reflects pending state;
  the Science re-entrancy guard no longer always-returns; `add_sound_to_queue`
  type==2 immediate vs enqueue; `IsSomeoneSpeaking` count.
- **PhonemeMap** (Python units): code→viseme bucketing for the 35 codes;
  completeness (every code resolves); `rounded`→`u`, bilabials→`closed`, open
  vowels→`open`; unknown→`closed`.
- **lip_sync controller** (Python units): discrete pose + crossfade; jaw angle
  emitted with the texture; no-`.LIP` flap stepping.
- **Jaw** (C++ ctest): Ponytail1 driven-rotation applies to the pose;
  `head_weld_seam_test.cc` seam invariant still holds; viseme→angle mapping.
- **Gate:** `scripts/check_tests.sh` (pytest + ctest), diffed against
  `tests/known_failures.txt` (the one baselined emitters flake is unrelated).
- **Live pass by Mark** — SP3 is player-visible (crew speech + lip-sync + new jaw
  motion); do NOT claim done from green tests
  (`feedback_green_tests_cannot_see_asset_paths`).

Any whole-SDK-module stubs touched are fixed in **both**
`tools/mission_harness.py` and `tests/conftest.py`
(`project_duplicate_sdk_ast_transforms`).

## 8. Out of scope (YAGNI)

- Per-character concurrent speaking (the single-channel bus divergence — separate
  speech-architecture spec).
- `SpeakLineNoFlap` / `AT_SPEAK_LINE_NO_FLAP_LIPS` (0 SDK callers).
- Clip-playback subsystem for the `mouth_*.NIF` files (direct-angle-set replaces
  it).
- Byte-exact code→viseme bucketing (needs a `FUN_00706c60` trace — Mark's side;
  our reconstruction is tunable data).