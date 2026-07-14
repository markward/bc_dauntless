# CharacterAction Verb Table — Design

**Date:** 2026-07-14
**Status:** approved, ready for implementation plan
**Derived from:** an audit of Dauntless's bridge-crew subsystem against
`/Users/mward/Documents/Projects/STBC-Reverse-Engineering-1/docs/gameplay/bridge-character-system.md`
(2026-07-14 revision, RE'd from `stbc.exe`).

## Problem

`CharacterAction.Play()` (`engine/appc/ai.py:1191-1237`) dispatches 14 of BC's ~25 `AT_*` verbs.
**Everything unmatched falls through to `_do_play()`, which returns `0.0`, which completes the action
inline and silently.** The sequence marches on; nothing logs; nothing raises. That fall-through is the
shape of the whole defect: a no-op that reports success.

The casualties, ranked by SDK call-site count:

| Verb | SDK sites | Effect today |
|---|---|---|
| `AT_SAY_LINE` — `turnTo`/`turnBack` args | **3977** | Args stored, never read (`ai.py:1153-1171`). Nobody turns to the captain; no chair swivels. The bridge is frozen through every line of dialogue in the game. |
| `AT_PLAY_ANIMATION` | 58 | Silent no-op. Every console/button/gesture beat is dead — including the routine button-push on every scan, repair and course change. |
| `AT_BREATHE` / `AT_FORCE_BREATHE` | 18 | Silent no-op. Officers never re-enter idle after a scripted beat. |
| `AT_PLAY_ANIMATION_FILE` | 10 | Silent no-op. One-off mission clips (Picard pointing at a station). |
| `AT_DEFAULT` | 9 | Silent no-op. Officer never resets to default pose. |
| `AT_SAY_LINE_AFTER_TURN` | 2 | Speaks, never turns. |

And two predicates the SDK uses as guards are **hardcoded constants**:

- `IsAnimatingNonInterruptable()` → `0` (`characters.py:673`) — **20 SDK sites**
- `IsSpeaking()` → `0` (`characters.py:668`) — **23 SDK sites**

They appear together in the standard SDK guard:
`if (pOfficer.IsHidden() or pOfficer.IsAnimatingNonInterruptable() or pOfficer.IsSpeaking()): return`
(`Bridge/EngineerCharacterHandlers.py:514`, and 19 more). Both being permanently open does not matter
*today*, because the gestures they guard do not play. The moment `AT_PLAY_ANIMATION` works, it does:
an officer mid-gesture accepts another gesture on top of it, and an officer mid-sentence gets re-tasked.

**Why none of this was on the roadmap:** `docs/stub_heatmap.md` contains **zero `CharacterClass` rows**.
`CharacterClass.__getattr__` (`characters.py:770-786`) absorbs every unknown `Set*`/`Add*` into a data
bag and everything else into `lambda: None`, bypassing `engine/core/stub_telemetry.py` entirely. The
instrument could never have seen these.

## What is already right — do not rebuild it

The load-bearing mechanism of the entire system (RE doc §4) is **correct in our engine**: an animation
name resolves to a **dotted Python function path**, not an asset. `bridge_placement._resolve_builder_sequence`
(`:73-103`) splits the path at the last `.`, imports the module, calls the function with the character,
and plays the `TGSequence` it *returns*. That is exactly BC's `PlayAnimation` → `TG_CallPythonFunction`
indirection.

The completion idiom is correct too. `_queue_move` (`ai.py:1239-1279`) resolves the builder sequence,
hangs an `ET_ACTION_COMPLETED` `TGObjPtrEvent` addressed **back at itself** so the `CharacterAction`
completes when the sequence does, then calls `seq.Play()`. `TGActionManager.ProcessEvent`
(`actions.py:748-759`) routes it. **Every new verb reuses this pattern verbatim.** We are filling in a
table, not building a mechanism.

## Design

### 1. Split the key resolver: literal keys vs. composed keys

BC composes an animation key from the character's **current location** plus the requested action —
`AT_MOVE "P1"` while at `"DBL1M"` looks up `"DBL1MToP1"`. Our resolver hard-codes that composition
(`bridge_placement.py:83-91`: `key = str(location) + suffix`).

`AT_PLAY_ANIMATION` is **the one verb whose key is literal** — `"PushingButtons"`, with no location
prefix. So:

- Extract a literal-key core: `resolve_builder(character, key)` — look `key` up in the character's
  `_animations` registry, import, call, return the `TGSequence` (or `None` on a miss).
- Keep the existing location-composing behaviour as a thin wrapper over it.
- Every verb then names its own key form and shares one lookup path.

### 2. The new verbs

Each follows `_queue_move`'s shape: resolve → if `None`, `Completed()` immediately (never stall a mission
sequence) → else hang the self-addressed `ET_ACTION_COMPLETED` event and `Play()`.

| Verb | Key form |
|---|---|
| `AT_PLAY_ANIMATION` | **literal** `self._detail` |
| `AT_BREATHE`, `AT_FORCE_BREATHE` | `<Location>` + `"Breathe"` (this key form already exists at `bridge_placement.py:187`, but is reachable only from the idle controller — the verb never reaches it) |
| `AT_DEFAULT` | **no registry** — re-run the SDK's own location→pose dispatcher, `CommonAnimations.SetPosition(character)`, which `bridge_placement.capture_placement` (`:39-70`) already calls at bridge load. "Default" for a character *is* its location's placement pose. |
| `AT_PLAY_ANIMATION_FILE` | **no registry** — raw NIF path, BC's escape hatch (`PlayAnimationFile`, `characters.py:640`) |

### 3. `AT_SAY_LINE` — honour `turnTo` / `turnBack`

Args 4 and 5. `("Captain", 1)` means *turn to the captain, speak, turn back*, with the chair swivelling
under her — because the SDK's turn builder animates the character clip and the chair clip in lock-step,
as parallel siblings of one sequence predecessor (which our action layer already supports).

No new machinery: `AT_TURN` works today and already composes `Turn<Target>` / `Back<Target>` keys via
`_queue_turn` (`ai.py:1281-1310`). `AT_SAY_LINE` becomes **turn → speak → turn back**, where the speak
step is the existing (already correctly blocking) path. `AT_SAY_LINE_AFTER_TURN` routes through the same
code.

`(None, 0)` must continue to speak with no turn at all. That is the regression guard.

### 4. Restore the two SDK gates

**`IsAnimatingNonInterruptable()`** reads the currently-playing animation's `CAT_` category. BC's rules
(RE doc §3.4, proven from the binary's own predicates):

- `IsAnimatingNonInterruptable()` ≡ `category == CAT_NON_INTERRUPTABLE`
- `IsAnimatingInterruptable()` ≡ `category in {BREATHE, INTERRUPTABLE, GLANCE, GLANCE_BACK}`

So `CharacterClass` grows a *currently-playing animation* field (category + name), set by the verb
dispatch on play and cleared on completion. The verb dispatch is already the natural owner — it is the
only thing that starts these sequences.

**Correct the `CAT_` values while here.** Ours are a bitmask (`characters.py:377-383`: `1, 2, 4, 8…`);
BC's are plain ordinals `0..6` (`0 = BREATHE, 1 = INTERRUPTABLE, 2 = NON_INTERRUPTABLE, 3 = TURN,
4 = TURN_BACK, 5 = GLANCE, 6 = GLANCE_BACK`). Note the inversion: BC's `CS_` state flags are the bitmask
and `CAT_` the ordinal, and we have both backwards. **This spec fixes `CAT_` only** — `CS_` is
self-consistent today (`IsStateSet` has zero SDK call sites) and is deferred.

Also fix `ClearAnimationsOfType` (`characters.py:518-519`), which compares a `CAT_` int against the
animation *name* and can therefore never match anything.

**`IsSpeaking()`** becomes a query against the existing speech bus for a live line from this character.
`crew_speech` already tracks per-speaker state (`last_talk_time(name)`), so this is an `is_speaking(name)`
sibling. **This is not the speech rewrite** — the global-arbiter problem (BC arbitrates *within* one
character; we arbitrate across all of them) is a separate spec and is explicitly out of scope here.

### 5. Fix the `PushButtons` misspelling — a deliberate divergence

BC ships a real bug: `MissionLib.PushButtons` and 40 other call sites request key `"PushButtons"`, but
all 14 character registrations spell it `"PushingButtons"`. In the original **those calls are silent
no-ops**. The 18 correctly-spelled sites — all of `EngineerCharacterHandlers.py`,
`ScienceCharacterHandlers.py` and `HelmMenuHandlers.py` — do work.

**Decision: alias `"PushButtons"` → `"PushingButtons"` at the single lookup point.** The original authors
plainly *meant* those calls to fire; this is a typo-fix, not a behaviour change.

**Recorded risk:** officers will now gesture in ~41 mission beats where BC left them still. If a scripted
scene looks over-animated, this alias is the first suspect. It is one line, in one place, and trivially
revertible.

### 6. Fix the instrument

Route `CharacterClass.__getattr__`'s misses (`characters.py:770-786`) through
`engine/core/stub_telemetry.py`, exactly as `App.__getattr__`/`_NamedStub` does, so `CharacterClass`
rows finally appear in `docs/stub_heatmap.md`. This makes the *remaining* gaps visible on the roadmap
instead of silently absorbed: `SetLookAtAdj` (5 SDK sites), `SetBlinkChance` (36), `SetRandomAnimationChance`
(44), `SetFlags`/`ClearFlags`.

Additionally, the `Get*` data-bag fallback returns `None` for a never-set field, which is a latent
`TypeError` for any SDK caller doing arithmetic on it — the same class of bug the `GetLastTalkTime`
comment at `characters.py:660-666` was written to prevent. Give the numeric ones real getters with real
defaults.

## Out of scope (each is its own spec)

- **Speech architecture** — per-character queues, reject-if-busy for `CSP_SPONTANEOUS`, deleting the
  global cross-character arbiter, the inverted `CSP_*` constants.
- **Bridge damage feedback** — `bridgeeffects` is entirely unwired (`DoCrewReactions`, `FlickerLCARs`,
  `DoHullDamage`, `SetShake`); seated officers get no hit clip at all; the guest chair never moves.
- **Animation layering on skinned characters** — one clip slot in C++; a gesture cannot play over a sit.
- **`CS_` as a real bitfield**, and BC's write-only `CS_HIDDEN`/`CS_VISIBLE` cull commands.
- Idle-gesture fidelity (weights, `SetRandomAnimationChance` 0.75-vs-0.01), head look-at, blink chance,
  officer-picking dot-product contest, low-detail gate.

## Testing

**Unit:**
- Key composition per verb; the literal-key path specifically (no location prefix).
- The `PushButtons` alias resolves; an unregistered key resolves to `None` and completes **immediately**
  (a missing clip must never stall a mission sequence).
- `AT_SAY_LINE("Captain", 1)` produces turn → speak → turn-back in that order; `(None, 0)` produces speak
  alone.
- Gates: a second gesture is **refused** while a `CAT_NON_INTERRUPTABLE` animation plays, and while the
  officer is speaking. `IsAnimatingInterruptable()` true for exactly `{0, 1, 5, 6}`.
- `CharacterClass` stub misses reach the telemetry sink.

**Live GUI verification (required):** issue a bridge order (scan / repair / course change) and watch the
officer actually push the buttons. That is the whole point of the change, and no unit test can see it.

**Gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against
`tests/known_failures.txt`) before the final commit. No C++ change is expected in this spec, so a pure
pytest loop is fine during development.

## Expected behavioural change

The bridge becomes visibly alive: officers turn to the captain when they speak and turn back, chairs
swivel under them, and consoles get used on every routine order.

**Some things will get *less* busy, and that is correct.** Closing the two gates suppresses gestures that
currently fire during speech and during non-interruptable animations — BC suppressed them deliberately.
A scene that looks calmer after this lands is the gates working, not a regression.
