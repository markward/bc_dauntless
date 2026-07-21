# CharacterClass reimplementation — SP1: owner skeleton + state model

**Date:** 2026-07-21
**Status:** design approved, awaiting spec review
**Scope of this doc:** the overall CharacterClass restructuring decomposition (context) +
the full design for **SP1** (the first sub-project). SP2–SP4 get their own specs.

---

## 1. Motivation

We have missing behaviours and features in the bridge/away-team character system, and the
existing code is organised by *host-side concern* (renderer coupling, CEF, camera) rather than
around *the character entity*. The reverse-engineered `CharacterClass` gives us a faithful map of
what the original engine actually supported. Restructuring our work around that map lets us
reimplement functionality faithfully and answer "what is a character and what can it do" from one
place.

**Constraints (from the requester):**
- Pure Python3 functional layer. **No C++ port, now or ever.** Therefore we mirror the original's
  *observable structure and semantics* — flag bits, category codes, queue conflict-resolution and
  chaining, method contracts — implemented idiomatically. We do **not** reproduce literal memory
  layout (byte offsets, slab freelists, 0x25-bucket hash-maps); that would be pointless without a
  native target.
- Keep the load-bearing boundaries the original never had (renderer/CEF/host-io) intact.

## 2. Evidence sources (ranked)

Per the project's evidence tiers (see the `project-evidence-tiers-sdk-swig-re` memory):

0. **The supplied clean-room `CharacterClass.md`** — **top tier, outranks everything below.**
   Per Mark (2026-07-21): it describes a reimplementation that was **recompiled into a hybrid
   executable and gameplay-tested**, so it is execution-validated, not merely static-interpreted.
   Trust its findings over any other source where it speaks. Confidence tags BE/DE/LV/P.
1. **Sibling RE repo** `../STBC-Reverse-Engineering-1/` (static Ghidra decompilation of `stbc.exe`)
   — used only where the tier-0 doc is *silent*:
   - `tools/merged/stbc_constants.csv` — exact extracted constant values (the tier-0 doc gives
     internal m_flags bit *meanings* but not the public `CS_*`→value table).
   - `.claude/agent-memory/.../character-class.md` — struct layout, ctor defaults, event IDs.
2. **SWIG surface** `sdk/Build/scripts/App.py:4617` — the 90-method Python-facing contract we must
   satisfy.
3. **Live SDK usage** `sdk/Build/scripts/` — `Bridge/Characters/<Name>.py`, `LoadBridge.py`,
   `BridgeHandlers.py`, `MissionLib.py`.

**Tie-break:** where tier 0 speaks, it wins. Where it is silent, tier 1 supplies the missing detail
(supplementary, not contradictory). Tier 0 and tier 1 have **agreed everywhere they overlap** so far
(the flag semantics of §5.2), which raised confidence rather than forcing a choice. Two SP1 values
come *only* from tier 1 because tier 0 does not enumerate them: the exact `CS_*`/`CPT_*` numeric
values (§5.1, from `stbc_constants.csv` — e.g. `CS_STOP_INITIATIVE = 0xFD8`, extracted, not the
agent-memory's inferred `0x1000`) and the ctor field *names* for offsets tier 0 leaves unlabelled
(§5.5, e.g. `+0x7C`→`Gender`) — both flagged inline as tier-1-sourced.

## 3. Architecture decision — "own + consolidate"

`CharacterClass` becomes the **owner/facade** holding named sub-components that mirror the
original's sub-objects (`AnimationQueue`, `SpeakQueue`, `StatusMap`, `MenuState`,
`PositionZoomTable`, `PhonemeMap`). This is the "brain"; the existing live-verified controllers
stay as the execution **backends** ("hands") that the sub-components call. Two structural cleanups
motivate the whole effort:

- **Collapse the two verb doors.** Today `CharacterClass`'s own action methods (`MoveTo`, `Turn*`,
  `Glance*`, `PlayAnimation*`) are dead `pass` stubs, while a parallel verb dispatcher in
  `engine/appc/ai.py:1301` (`CharacterAction`) does the real routing. The original has *one* door:
  `CharacterAction` verbs call `CharacterClass` methods, which drive the queue. We converge on that.
- **Consolidate the scattered animation modules** (`bridge_character_anim`, `bridge_node_anim`,
  `bridge_idle_gestures`, `bridge_hit_reactions`, `bridge_camera_watch`) behind one
  `AnimationQueue` owner. (Happens in SP2.)

Boundaries that **stay** as collaborators (the original spelled these as file-scope globals or did
not have them at all): `crew_speech.CrewSpeechBus` (collective speech arbitration), the pure
`lip_sync` / `lip_sync_runtime` split, `crew_menu_panel` (CEF), `bridge_placement` (SDK builder
resolution).

## 4. Decomposition (roadmap)

Each sub-project is its own spec → plan → implement → live-verify cycle.

| SP | Title | Delivers | Depends on |
|----|-------|----------|-----------|
| **SP1** | Owner skeleton + state model | Owner/facade with sub-component slots; faithful `CS_*` flag **bitfield**; `SetFlags`/`ClearFlags` (currently dead no-ops); lifecycle statics. Behaviour-equivalent, gate-verified. **No player-visible change.** | — |
| **SP2** | AnimationQueue (the heart) | `CAT_*` category-coded queue with `Classify1`/`Classify2` conflict resolution, `Special4`/`Special6` chaining, `Update`/`Release` driver; consolidates the 5 `bridge_*_anim` modules; makes the `pass`-stub action methods fire; collapses the two verb doors. **First player-visible payoff.** | SP1 |
| **SP3** | SpeakQueue + PhonemeMap | Speaking as an owned sub-object wrapping `crew_speech`; phoneme table feeding lip-sync. | SP1 |
| **SP4** | StatusMap + PositionZoomTable + MenuState | `SetStatus`/`ClearStatus`/`GetStatus` tooltip widgets (keys 0..5); position-zoom table (currently missing); menu state as an owned sub-object. | SP1 |

SP1 unlocks all; SP2/SP3/SP4 are independent of each other.

**Out of scope, all SPs (YAGNI):** `MorphBody`/`GetHeadHeight` (0 SDK call sites); literal memory
layout fidelity.

---

## 5. SP1 detailed design

All changes are in `engine/appc/characters.py` unless noted. SP1 is a **pure-substrate refactor**:
observable behaviour for every current caller is preserved; the only *new* behaviour is that the
previously-dead `SetFlags`/`ClearFlags` now do something (see §5.2).

### 5.1 Ground-truth constants

Replace the current ordinal `CS_*` and mis-valued `CPT_*` with the extracted values. Shared
vocabulary for all four sub-projects.

**`CS_*` state flags (a bitfield, `+0x80` in the original):**

| Name | Value | Role |
|------|-------|------|
| `CS_IDLE` | `0x0` | (no bits) |
| `CS_STANDING` | `0x1` | standing |
| `CS_GLANCING` | `0x2` | glance-away active |
| `CS_TURNED` | `0x4` | move / back-to-target active |
| `CS_UI_DISABLED` | `0x8` | busy / menu-suppressed (set by `MoveTo`) |
| `CS_HIDDEN` | `0x10` | **not stored in `_flags`** — toggles hidden-state (`IsHidden`→true) |
| `CS_INITIATIVE` | `0x20` | initiative |
| `CS_MIDDLE` | `0x40` | layout/posture |
| `CS_SEATED` | `0x80` | seated |
| `CS_VISIBLE` | `0x100` | **not stored in `_flags`** — toggles hidden-state (`IsHidden`→false) |
| `CS_CLEAR_GLANCE` | `0x200` | pseudo-flag |
| `CS_CLEAR_TURNED` | `0x400` | pseudo-flag |
| `CS_UI_ENABLED` | `0x800` | pseudo-flag (PlayAnimation done-flag) |
| `CS_STOP_INITIATIVE` | `0xFD8` | composite clear-mask |

**`CPT_*` phoneme channels (corrected):** `CPT_DEFAULT = -1`, `CPT_BLINK = 0`, `CPT_SPEAK = 1`,
`CPT_EYEBROW = 2`.

**Unchanged (already correct):** `CAT_*` (`BREATHE=0, INTERRUPTABLE=1, NON_INTERRUPTABLE=2,
TURN=3, TURN_BACK=4, GLANCE=5, GLANCE_BACK=6`), `CAM_*` (`MUTE=0, EXTREMELY_VOCAL=1, VOCAL=2,
REDUCED=3`), gender (`MALE=0, FEMALE=1, MAX_GENDERS=2`), size (`SMALL=0, MEDIUM=1, LARGE=2,
MAX_SIZES=3`), posture (`BOTH=0, SITTING_ONLY=1, STANDING_ONLY=2`), `EST_*` (0..42).

> **Migration risk:** `CS_*` currently double as `set` keys *and* ordinals. Changing their values
> to real bits changes any code that compares/stores them. `ProcessEvent` (§5.3) is the notable
> consumer and is handled explicitly. A repo-wide grep for `CS_` consumers is a plan task.

### 5.2 Flag bitfield (replaces the `set`)

`self._states: set` → `self._flags: int` (default `0`).

- **`SetFlags(mask)`** (new — currently a silent `__getattr__` no-op):
  - `mask == 0` → no-op.
  - `mask == CS_HIDDEN (0x10)` → set hidden-state (so `IsHidden()`→true); do **not** store the bit
    in `_flags`, and do **not** push a render call. Return.
  - `mask == CS_VISIBLE (0x100)` → clear hidden-state (`IsHidden()`→false); do not store. Return.
  - else → OR `mask` into `_flags`; then if `CS_UI_DISABLED (0x8)` is now set **and** the menu is
    up, call `MenuDown()` (BC menu suppression).
- **`ClearFlags(mask)`** (new): `0x10` → clear hidden-state; `0x100` → set hidden-state; else
  AND-NOT from `_flags`.

> **Visibility is a pull model — do not break it.** The host loop reads `IsHidden()` every frame
> and calls `set_visible(iid, not ch.IsHidden())` (`host_loop.py:4759`, `:4787`). `SetFlags`/
> `ClearFlags`/`SetHidden` therefore only mutate the hidden-state bool; the per-frame pull does the
> actual cull. This matches the project's established view-sync pull model.
- **`IsStateSet(mask)`** → `1 if (self._flags & mask) == mask else 0`.
- Derived, reconciled onto the bitfield (observable result identical to today):
  - `SetStanding(value=None)` — bare → `SetFlags(CS_STANDING)`; with a posture arg → store
    `StandingMode` (unchanged). `IsStanding` → `IsStateSet(CS_STANDING)`.
  - `SetInitiative(bOn)` (new) → `SetFlags`/`ClearFlags(CS_INITIATIVE)`; `IsInitiativeOn` reads it.
  - `SetHidden(hidden=1)` → `SetFlags(CS_HIDDEN)` / `ClearFlags(CS_HIDDEN)`; `IsHidden` returns the
    hidden-state bool (kept explicit, since the bit isn't stored in `_flags`). The host-loop pull
    (above) is unchanged.
  - `IsTurned` → `IsStateSet(CS_TURNED)`, `IsGlancing` → `IsStateSet(CS_GLANCING)`, `IsUIDisabled`
    → `IsStateSet(CS_UI_DISABLED)`.

### 5.3 Disentangle status-strings from flags

Today `SetStatus("Waiting")` (string, tooltip display) and `SetStatus(CS_*)` (int flag) both land
in the one `_states` set. Split:

- **Flag path:** CS_* ints go through the bitfield (§5.2).
- **Status path:** strings (and the 0..5 status keys) go to a new `self._status: dict` placeholder.
  `SetStatus`/`ClearStatus` route by type (`str`/key → `_status`; the flag-style callers, if any,
  keep working). SP4 replaces `_status` with the real keys-0..5 `StatusMap`.
- **`ProcessEvent`** (`ET_CHARACTER_ANIMATION_DONE` → apply carried `CS_*`) is re-expressed against
  the bitfield/`SetHidden`, preserving the exact observable behaviour (officer hides after the
  turbolift walk; `CS_STANDING` reveal; `CS_SEATED` clears standing). Must never raise.

### 5.4 Owner skeleton — named sub-component slots

Construct, in `__init__`, the slots later SPs fill (mirroring the original's sub-objects). SP1
leaves them `None` or thin placeholders with clear construction points:

- `self._anim_queue` — SP2 (the `CAT_*` queue). SP1: `None`; `_current_anim` stays as the interim
  single-slot state so nothing regresses.
- `self._speak_queue` — SP3. SP1: `None`; `SayLine`/`SpeakLine`/`IsSpeaking`/`GetLastTalkTime`
  keep routing to `crew_speech` as today.
- `self._status` — §5.3 dict placeholder (SP4 → `StatusMap`).
- `self._menu_state` — SP4. SP1: the existing `_menu`/`MenuUp`/`MenuDown` machinery is untouched.
- `self._position_zoom` — SP4. SP1: absent (feature is missing today; stays missing until SP4).
- `self._phonemes` — SP3. SP1: the existing `_phonemes` list is retained as-is.

The point of SP1 is that these slots *exist and are named*, so SP2–SP4 plug in without re-shaping
the class.

### 5.5 Constructor faithfulness

Seed the RE'd ctor defaults as real attributes (out of the ad-hoc `_data` bag):
`_size = SMALL`, `_gender = FEMALE` (RE ctor default `+0x7C = 1`), `_audio_mode = CAM_VOCAL`,
`_blink_chance = 0.1`, `_random_anim_enabled = True`, `_blink_stages = -1`, `_flags = 0`,
`_is_active = False` (RE ctor `+0xCC = 0`). The un-RE'd long tail stays in `_data` (YAGNI).

> Note: the existing `IsActive` defaults to `True` via `_data.get("Active", True)`; RE ctor default
> is `0` (inactive). This is a behaviour change — flagged as a plan task to verify against live
> callers before flipping, since `SetActive` is called during bridge load.

### 5.6 Lifecycle statics

Audit and cover with tests (mostly already present): `CharacterClass_Create` (ctor + NIF record),
`CharacterClass_CreateNull` (null-object), `CharacterClass_Cast` (class-ID `0x8016`),
`CharacterClass_GetObject` (reverse-iterate the character-set registry; first non-null cast),
`CharacterClass_GetObjectStrict`. Confirm they match reference §4.1/§4.13 semantics.

---

## 6. Verification

- **`scripts/check_tests.sh`** gate green (pytest + ctest, diffed against `known_failures.txt`).
- **Equivalence tests** for load-bearing current behaviours: string `SetStatus`/`ClearStatus`;
  `IsStateSet`; `SetHidden(0)` reveal (the ViewscreenOn hail-character path); `ProcessEvent`
  turbolift-hide (`ET_CHARACTER_ANIMATION_DONE` → `CS_HIDDEN`).
- **New unit tests** for `SetFlags`/`ClearFlags`/`IsStateSet` against the §5.1 bit table, including
  the `0x10`/`0x100` cull dispatch and the `0x8`-busy → `MenuDown` coupling.
- **No live in-game pass claimed for SP1** — nothing here is player-visible. The first live pass is
  SP2. (Per project practice: never assert "it works" in-game before it is seen running.)

## 7. Resolved decisions

- **Keep the `_data` bag** for the un-RE'd long tail rather than enumerating every field now (YAGNI).
- **`SetFlags(0x10)`/`(0x100)` route through the same hidden-state that `SetHidden` sets**, so the
  new flag API and the existing host-loop visibility pull stay in agreement. No new render wiring
  and no push — the per-frame `set_visible(not IsHidden())` pull is left as-is.
- **Behavioural, not literal-layout, fidelity** (pure-Python constraint).
