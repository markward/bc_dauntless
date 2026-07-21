# CharacterClass SP2 — AnimationQueue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CharacterClass` own BC's faithful `CAT_*` animation queue — the single referee (`classify`), `SetCurrentAnimation`/`UpdateAnimationQueue`, `Special4/6` chaining, release/cleanup, predicates — turn the `pass`-stub action methods into real enqueues, demote `BridgeCharacterAnimController` to a clip-player, collapse the two verb doors into one, and land `SetActive` faithfulness.

**Architecture:** `CharacterClass` (the brain) owns a record queue and decides *which* record plays *when* (conflict resolution, ordering, chaining, release). `BridgeCharacterAnimController` (the hands) keeps its proven clip resolution + playback and is called through a thin seam (`play`/`is_active`/`stop`/`return_to_default`). The pure referee + record type live in a new focused module `engine/appc/character_anim_queue.py`; the queue *methods* hang off `CharacterClass`. `CharacterClass` never imports the renderer — it reaches the clip-player through the existing `get_controller()` seam (host_io/façade rule).

**Tech Stack:** Python 3 (pytest); the App shim under `engine/appc/`; host controllers under `engine/`. No C++/native changes.

**Spec:** `docs/superpowers/specs/2026-07-21-characterclass-reimplementation-sp2-design.md` (the §5 referee table and §4 method contracts are the source of truth; tier-0 `CharacterClass.md` §4.8–4.10 are the method bodies).

## Global Constraints

- **Pure Python3, no C++.** Behavioural fidelity to BC, not memory layout.
- **The §5 referee is EXACT** — implement the 7×7 verdict table verbatim; tests assert it cell-for-cell. Verdicts: `stop-old`, `reject-new`, `stop-both`, `coexist`. Null existing ⇒ `coexist`. `name*` (cells (3,4) and (5,6)) ⇒ `stop-both` iff both `+0x0C` names non-null & equal & existing **not** currently-playing, else `coexist`.
- **Category integers:** `CAT_BREATHE=0, CAT_INTERRUPTABLE=1, CAT_NON_INTERRUPTABLE=2, CAT_TURN=3, CAT_TURN_BACK=4, CAT_GLANCE=5, CAT_GLANCE_BACK=6` (already on `CharacterClass`).
- **CharacterClass stays renderer-free** — reach the clip-player via `bridge_character_anim.get_controller()`; never import the renderer/host into `engine/appc/`.
- **Visibility/flags** use SP1's model: `SetFlags`/`ClearFlags`/`IsStateSet`/`_flags`; `CS_GLANCING=0x2`, `CS_TURNED=0x4`, `CS_UI_DISABLED=0x8`.
- **Shared checkout:** stage commits with explicit pathspecs ONLY — never `git add -A`/`.`; the tree carries another session's uncommitted `engine/appc/objects.py` and `engine/host_loop.py` — never stage those.
- **Test gate:** authoritative check is `scripts/check_tests.sh` (pytest + ctest). Per-task runs use focused `uv run pytest`.
- **SP2 is player-visible.** It re-homes live behaviors (idle gestures, hit reactions, turn-to-captain, walk-on, glances). The final task is a **live-verification checklist for Mark**, not a green-tests "done" claim. Do NOT assert in-game correctness from tests alone.

## File Structure

- **Create:** `engine/appc/character_anim_queue.py` — the pure referee (`classify`), the `AnimRec` record, verdict constants. No side effects, no imports of `characters`/renderer. Fully unit-testable.
- **Modify:** `engine/appc/characters.py` — replace the interim `_current_anim` with the queue; add `SetCurrentAnimation`/`UpdateAnimationQueue`/`ReleaseCurrentAnimation`/`OnAnimRelease`/`ShouldPlayNow`/`PreparePlay`/`Special4`/`Special6`/`ClearAnimationsOfType`/`ClearExtraAnimations`/`ClearAnimations`; re-express the predicates; make the action methods real; `SetActive` faithfulness.
- **Modify:** `engine/bridge_character_anim.py` — demote to the clip-player seam (`play`/`is_active`/`stop`/`return_to_default`); keep resolution+playback internals; remove the `_Action` priority-queue / `submit`/`request_*`/`is_busy` layer.
- **Modify:** `engine/appc/ai.py` (`CharacterAction.Play`), `engine/bridge_idle_gestures.py`, `engine/bridge_hit_reactions.py`, `engine/bridge_character_walk.py`, `engine/host_loop.py` (per-frame tick) — re-point to the single door.
- **Create:** `tests/unit/test_character_anim_queue.py` (referee + queue), extend `tests/unit/test_characters.py` / `tests/unit/test_character_action_verbs.py` as needed.

---

## Task 1: The `classify` referee (the 7×7 table)

Pure, standalone, fully specified by spec §5. No dependency on `CharacterClass`.

**Files:**
- Create: `engine/appc/character_anim_queue.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Produces: `AnimRec` (fields `category:int, name:str|None, flags:int, play`), verdict constants `STOP_OLD, REJECT_NEW, STOP_BOTH, COEXIST`, and `classify(existing: AnimRec|None, new: AnimRec, existing_is_current: bool) -> int`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_character_anim_queue.py`:

```python
"""SP2 — the single Classify referee (spec §5, RE-confirmed 7x7 table)."""
import pytest
from engine.appc.character_anim_queue import (
    AnimRec, classify, STOP_OLD, REJECT_NEW, STOP_BOTH, COEXIST,
)

def R(cat, name=None):
    return AnimRec(category=cat, name=name, flags=0, play=object())

# The authoritative table (spec §5). rows=existing, cols=new; 'N' = name* cell.
TABLE = [
    # new: 0    1    2    3    4    5    6
    ["RN","SO","SO","SO","SO","SO","SO"],  # 0 BREATHE
    ["CO","RN","SO","SO","CO","CO","CO"],  # 1 INTERRUPTABLE
    ["CO","CO","CO","CO","CO","CO","CO"],  # 2 NON_INTERRUPTABLE
    ["CO","CO","CO","CO","N ","CO","CO"],  # 3 TURN
    ["CO","CO","CO","CO","CO","CO","CO"],  # 4 TURN_BACK
    ["CO","CO","SO","SO","SO","CO","N "],  # 5 GLANCE
    ["CO","CO","SO","SO","SO","CO","CO"],  # 6 GLANCE_BACK
]
_CODE = {"SO": STOP_OLD, "RN": REJECT_NEW, "CO": COEXIST}

@pytest.mark.parametrize("ex", range(7))
@pytest.mark.parametrize("nw", range(7))
def test_table_cells_without_names(ex, nw):
    cell = TABLE[ex][nw].strip()
    verdict = classify(R(ex), R(nw), existing_is_current=False)
    if cell == "N":
        # name* with null names collapses to coexist
        assert verdict == COEXIST
    else:
        assert verdict == _CODE[cell]

def test_null_existing_is_coexist():
    assert classify(None, R(2), existing_is_current=False) == COEXIST

def test_name_cell_stop_both_when_names_equal_and_not_current():
    # existing TURN(3) vs new TURN_BACK(4), same non-null name, existing queued
    assert classify(R(3, "Captain"), R(4, "Captain"), existing_is_current=False) == STOP_BOTH
    # existing GLANCE(5) vs new GLANCE_BACK(6)
    assert classify(R(5, "Kirk"), R(6, "Kirk"), existing_is_current=False) == STOP_BOTH

def test_name_cell_coexists_when_existing_is_current():
    assert classify(R(3, "Captain"), R(4, "Captain"), existing_is_current=True) == COEXIST

def test_name_cell_coexists_when_names_differ_or_null():
    assert classify(R(3, "Captain"), R(4, "Data"), existing_is_current=False) == COEXIST
    assert classify(R(3, None), R(4, "Data"), existing_is_current=False) == COEXIST
    assert classify(R(3, "Captain"), R(4, None), existing_is_current=False) == COEXIST
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement `engine/appc/character_anim_queue.py`:**

```python
"""The CharacterClass animation-queue referee + record type (spec §5).

Pure and side-effect-free: a single referee `classify(existing, new,
existing_is_current)` implementing BC's RE-confirmed 7x7 verdict table. Kept out
of characters.py so the table is testable cell-for-cell in isolation.
"""
from dataclasses import dataclass

# Verdict codes. Values chosen for readability; callers use the names.
STOP_OLD = 0       # stop the existing animation, let the new one play
REJECT_NEW = 1     # keep the existing, drop the new
STOP_BOTH = 2      # stop the existing AND drop the new
COEXIST = 3        # leave both; the new joins the queue


@dataclass
class AnimRec:
    """A queued animation record (BC's 0x10-byte AnimRec).

    category : CAT_* code (0..6)
    name     : the record's own name (BC +0x0C, the 4th SetCurrentAnimation arg);
               compared by the referee in the two name* cells. May be None.
    flags    : CS_* flags to apply while playing (BC +0x04).
    play     : the resolved thing the clip-player runs (SDK sequence / clips).
    """
    category: int
    name: object = None
    flags: int = 0
    play: object = None


# Sentinel for the two name-tiebreaker cells.
_NAME = object()

# rows = existing category, cols = new category (spec §5, verbatim).
_T = None  # filled below for readability
_VERDICT_TABLE = [
    # new: 0BREATHE    1INTERRUPT  2NON_INT    3TURN       4TURN_BACK  5GLANCE     6GLANCE_BACK
    [REJECT_NEW, STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD,  STOP_OLD ],  # 0 BREATHE
    [COEXIST,    REJECT_NEW, STOP_OLD, STOP_OLD,  COEXIST,   COEXIST,   COEXIST  ],  # 1 INTERRUPTABLE
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST  ],  # 2 NON_INTERRUPTABLE
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   _NAME,     COEXIST,   COEXIST  ],  # 3 TURN
    [COEXIST,    COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST,   COEXIST  ],  # 4 TURN_BACK
    [COEXIST,    COEXIST,   STOP_OLD,  STOP_OLD,  STOP_OLD,  COEXIST,   _NAME    ],  # 5 GLANCE
    [COEXIST,    COEXIST,   STOP_OLD,  STOP_OLD,  STOP_OLD,  COEXIST,   COEXIST  ],  # 6 GLANCE_BACK
]


def classify(existing, new, existing_is_current):
    """Return the verdict for enqueuing `new` against `existing` (spec §5).

    `existing` is None when there is no conflict partner (⇒ COEXIST).
    `existing_is_current` distinguishes Classify1 (vs the currently-playing
    animation, lenient) from Classify2 (vs a queued record, strict).
    """
    if existing is None:
        return COEXIST
    cell = _VERDICT_TABLE[existing.category][new.category]
    if cell is _NAME:
        if (existing.name and new.name and existing.name == new.name
                and not existing_is_current):
            return STOP_BOTH
        return COEXIST
    return cell
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q`
Expected: PASS (49 table cells + name cases).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/character_anim_queue.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t1 — Classify referee (RE-confirmed 7x7 table)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Queue data model on `CharacterClass`

Replace the interim single `_current_anim` tuple (SP1) with the record queue; populate the SP1 `_anim_queue` slot's role.

**Files:**
- Modify: `engine/appc/characters.py` (`__init__`; the `_current_anim` field and its interim readers)
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: `AnimRec` (Task 1).
- Produces on `CharacterClass`: `self._anim_current: AnimRec|None`, `self._anim_pending: list[AnimRec]`; helpers `_anim_count() -> int`. The SP1 `_glance_name`/`_target_name` name buffers are introduced here (both `None`).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_character_anim_queue.py`:

```python
from engine.appc.characters import CharacterClass_Create

def test_fresh_character_queue_is_empty():
    c = CharacterClass_Create()
    assert c._anim_current is None
    assert c._anim_pending == []
    assert c._anim_count() == 0
    # SP2 target-name buffers (BC +0xa0 / +0xa4)
    assert c._target_name is None
    assert c._glance_name is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q -k queue_is_empty`
Expected: FAIL (`_anim_current`/`_anim_pending`/`_anim_count`/`_target_name`/`_glance_name` absent).

- [ ] **Step 3: Implement.** In `engine/appc/characters.py __init__`, replace the interim
`self._current_anim: tuple | None = None` line with:

```python
        # ── Animation queue (SP2 — the CAT_* record queue; brain) ──────────
        self._anim_current = None        # AnimRec | None (BC +0x15C)
        self._anim_pending = []          # list[AnimRec] FIFO (BC +0x164 head)
        self._target_name = None         # move/back-to target (BC +0xa0)
        self._glance_name = None         # glance target (BC +0xa4)
```

Add the count helper near the other animation methods:

```python
    def _anim_count(self) -> int:
        return (1 if self._anim_current is not None else 0) + len(self._anim_pending)
```

Update the SP1 `_anim_queue = None` slot comment to note SP2 now uses
`_anim_current`/`_anim_pending` (leave the slot or repurpose it — do not leave a
dangling reference). Grep `_current_anim` and migrate any remaining reader
(`GetCurrentAnimation`, `set_current_animation`, `clear_current_animation`,
`IsAnimating*`) to the new fields; those are fully replaced in Tasks 3–5, so a
minimal interim shim here is fine as long as the module imports and existing
tests referencing them do not crash.

- [ ] **Step 4: Run to verify pass + no import breakage**

Run: `uv run pytest tests/unit/test_character_anim_queue.py tests/unit/test_characters.py -q`
Expected: PASS (the empty-queue test; existing tests still import/collect).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t2 — record-queue data model on CharacterClass

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `SetCurrentAnimation` — enqueue with the referee

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: `classify`, `AnimRec` (Task 1); the queue fields (Task 2); the clip-player seam's `stop` (Task 10) — until Task 10 lands, calls a private `self._anim_stop_play(rec)` that is a no-op stub introduced here and given a body in Task 10.
- Produces: `CharacterClass.SetCurrentAnimation(anim, category, flags=0, name=None) -> None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_character_anim_queue.py`:

```python
from engine.appc.characters import CharacterClass

def _mk(cat, name=None):
    return object()  # opaque 'play' handle

def test_enqueue_into_empty_coexists():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(2), CharacterClass.CAT_NON_INTERRUPTABLE, 0, None)
    assert c._anim_count() == 1

def test_new_breathe_rejected_against_breathe_incumbent():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # pending[0]
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # reject-new
    assert c._anim_count() == 1

def test_real_move_stops_queued_idle_then_enqueues():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(_mk(0), CharacterClass.CAT_BREATHE)          # idle queued
    c.SetCurrentAnimation(_mk(2), CharacterClass.CAT_NON_INTERRUPTABLE)  # stop-old + enqueue
    # the idle was stopped/removed; the move is queued
    cats = [r.category for r in c._anim_pending]
    assert CharacterClass.CAT_BREATHE not in cats
    assert CharacterClass.CAT_NON_INTERRUPTABLE in cats
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q -k "enqueue or rejected or stops_queued"`
Expected: FAIL (`SetCurrentAnimation` absent / still a stub).

- [ ] **Step 3: Implement** `SetCurrentAnimation` on `CharacterClass` (faithful to tier-0 §4.8 + spec §5). Also add the interim `_anim_stop_play` no-op:

```python
    def SetCurrentAnimation(self, anim, category, flags=0, name=None) -> None:
        from engine.appc import character_anim_queue as q
        rec = q.AnimRec(category=int(category), name=name, flags=int(flags), play=anim)
        # 1) Classify against the CURRENT animation (Classify1 — lenient).
        cur = self._anim_current
        if cur is not None:
            v = q.classify(cur, rec, existing_is_current=True)
            if v in (q.STOP_OLD, q.STOP_BOTH):
                self._anim_stop_play(cur)
                self._anim_current = None
            if v in (q.REJECT_NEW, q.STOP_BOTH):
                self._anim_stop_play(rec)
                return
        # 2) Classify against each QUEUED record (Classify2 — strict).
        survivors = []
        for other in self._anim_pending:
            v = q.classify(other, rec, existing_is_current=False)
            if v in (q.STOP_OLD, q.STOP_BOTH):
                self._anim_stop_play(other)          # drop the queued record
                continue
            survivors.append(other)
            if v in (q.REJECT_NEW, q.STOP_BOTH):
                self._anim_pending = survivors + self._anim_pending[len(survivors):]
                self._anim_stop_play(rec)
                return
        self._anim_pending = survivors
        # 3) Append the survivor at the tail.
        self._anim_pending.append(rec)

    def _anim_stop_play(self, rec) -> None:
        # Interim no-op; Task 10 wires this to the clip-player seam (stop the
        # record's live playback). Safe to call on records that never played.
        pass
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t3 — SetCurrentAnimation enqueue via the referee

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Predicates re-expressed against the queue

**Files:**
- Modify: `engine/appc/characters.py` (the existing `IsAnimating`/`IsGoingToAnimate`/`IsAnimatingInterruptable`/`IsAnimatingNonInterruptable`, currently reading `_current_anim`)
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: the queue fields; `CAT_*` sets. Produces the four predicates on the queue (tier-0 §4.9).

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_predicates_track_the_queue():
    c = CharacterClass_Create()
    assert c.IsAnimating() == 0 and c.IsGoingToAnimate() == 0
    c.SetCurrentAnimation(object(), CharacterClass.CAT_NON_INTERRUPTABLE)  # cat 2
    assert c.IsGoingToAnimate() == 1
    assert c.IsAnimatingNonInterruptable() == 1
    assert c.IsAnimatingInterruptable() == 0

def test_interruptable_predicate_true_only_for_0156():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_GLANCE)  # 5 -> interruptable
    assert c.IsAnimatingInterruptable() == 1
    assert c.IsAnimatingNonInterruptable() == 0
```

- [ ] **Step 2: Run to verify failure** (current predicates read `_current_anim`, now gone)

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q -k predicate`
Expected: FAIL.

- [ ] **Step 3: Implement** (replace the SP1 predicate bodies; interruptable set = `{0,1,5,6}`, non-interruptable = `{2}` per tier-0 §4.9). `IsAnimating`/`IsGoingToAnimate`/`IsAnimatingInterruptable`/`IsAnimatingNonInterruptable` read `_anim_current` + `_anim_pending`; call `ReleaseCurrentAnimation(0)` first where tier-0 specifies (§4.9 — Task 5 provides it; until then guard with `getattr`). Provide the exact bodies:

```python
    _ANIM_INTERRUPTABLE = (0, 1, 5, 6)

    def IsAnimating(self) -> int:
        if self._anim_pending:
            return 1
        self.ReleaseCurrentAnimation(0)
        return 1 if self._anim_current is not None else 0

    def IsGoingToAnimate(self) -> int:
        return 1 if self._anim_count() != 0 else 0

    def IsAnimatingInterruptable(self) -> int:
        self.ReleaseCurrentAnimation(0)
        recs = ([self._anim_current] if self._anim_current else []) + self._anim_pending
        if not recs:
            return 0
        return 1 if all(r.category in self._ANIM_INTERRUPTABLE for r in recs) else 0

    def IsAnimatingNonInterruptable(self) -> int:
        self.ReleaseCurrentAnimation(0)
        recs = ([self._anim_current] if self._anim_current else []) + self._anim_pending
        return 1 if any(r.category == self.CAT_NON_INTERRUPTABLE for r in recs) else 0
```

> `ReleaseCurrentAnimation` arrives in Task 5. To keep Task 4 green in isolation,
> add a minimal `def ReleaseCurrentAnimation(self, param=0): pass` now if it does
> not yet exist; Task 5 replaces the body. (Do not duplicate the def — Task 5
> edits it in place.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_anim_queue.py tests/unit/test_characters.py -q -k "predicate or animat"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t4 — animation predicates over the queue

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `ReleaseCurrentAnimation` + `OnAnimRelease`

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: the clip-player seam's `is_active` (Task 10) — until then, a private `self._anim_is_active(rec) -> bool` stub returning `False` (so a record is considered finished once handed over). Produces `ReleaseCurrentAnimation(param=0)` and `OnAnimRelease(rec)` (tier-0 §4.8).

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_onanimrelease_glance_away_clears_state():
    c = CharacterClass_Create()
    c._glance_name = "Kirk"
    c.SetFlags(CharacterClass.CS_GLANCING)          # 0x2
    from engine.appc.character_anim_queue import AnimRec
    c.OnAnimRelease(AnimRec(category=CharacterClass.CAT_GLANCE_BACK))  # 6
    assert c._glance_name is None
    assert c.IsStateSet(CharacterClass.CS_GLANCING) == 0

def test_onanimrelease_turn_back_clears_state():
    c = CharacterClass_Create()
    c._target_name = "Captain"
    c.SetFlags(CharacterClass.CS_TURNED)            # 0x4
    from engine.appc.character_anim_queue import AnimRec
    c.OnAnimRelease(AnimRec(category=CharacterClass.CAT_TURN_BACK))    # 4
    assert c._target_name is None
    assert c.IsStateSet(CharacterClass.CS_TURNED) == 0

def test_release_retires_finished_current():
    c = CharacterClass_Create()
    c.SetCurrentAnimation(object(), CharacterClass.CAT_NON_INTERRUPTABLE)
    # promote pending -> current so there is something to release (Task 8 does
    # this in the driver; here set it directly for the unit)
    c._anim_current = c._anim_pending.pop(0)
    c.ReleaseCurrentAnimation(0)     # stub is_active False -> finished -> cleared
    assert c._anim_current is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q -k "onanimrelease or retires"`
Expected: FAIL.

- [ ] **Step 3: Implement** (tier-0 §4.8). Replace the interim `ReleaseCurrentAnimation` stub body; add `OnAnimRelease` and the `_anim_is_active` stub:

```python
    def ReleaseCurrentAnimation(self, param=0) -> None:
        cur = self._anim_current
        if cur is None:
            return
        if not self._anim_is_active(cur):
            self.OnAnimRelease(cur)
            self._anim_current = None

    def OnAnimRelease(self, rec) -> None:
        cat = rec.category
        if cat == self.CAT_GLANCE_BACK:          # 6 — glance-away
            self._glance_name = None
            self.ClearFlags(self.CS_GLANCING)    # 0x2
        elif cat == self.CAT_TURN_BACK:          # 4 — turn-back
            self._target_name = None
            self.ClearFlags(self.CS_TURNED)      # 0x4

    def _anim_is_active(self, rec) -> bool:
        # Interim: a handed-over record is considered finished. Task 10 wires
        # this to the clip-player seam (is_active on the character's instance).
        return False
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t5 — ReleaseCurrentAnimation + OnAnimRelease cleanup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `ShouldPlayNow` + `PreparePlay`

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Produces `ShouldPlayNow(rec) -> bool` and `PreparePlay(rec) -> None` (tier-0 §4.8). `PreparePlay` writes the `_target_name`/`_glance_name` buffers and applies `rec.flags` via `SetFlags`.

- [ ] **Step 1: Write the failing tests** — append (encode tier-0 §4.8 exactly; pin the observable result per spec §4.6):

```python
from engine.appc.character_anim_queue import AnimRec

def test_shouldplaynow_cat2_always_plays():
    c = CharacterClass_Create()
    c._target_name = "P1"                       # a pending move-target set
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_NON_INTERRUPTABLE)) is True

def test_shouldplaynow_move_target_blocks_non_turnback():
    c = CharacterClass_Create()
    c._target_name = "P1"
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_GLANCE)) is False   # blocked
    assert c.ShouldPlayNow(AnimRec(category=CharacterClass.CAT_TURN_BACK)) is True # cat 4 exempt

def test_prepareplay_applies_flags_and_sets_glance_target():
    c = CharacterClass_Create()
    c.PreparePlay(AnimRec(category=CharacterClass.CAT_GLANCE, name="Kirk",
                          flags=CharacterClass.CS_UI_DISABLED))
    assert c.IsStateSet(CharacterClass.CS_UI_DISABLED) == 1   # flags applied
    assert c._glance_name == "Kirk"                            # cat 5 -> glance target
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q -k "shouldplaynow or prepareplay"`
Expected: FAIL.

- [ ] **Step 3: Implement** (tier-0 §4.8 verbatim; categories: 2 always; move-target blocks all but cat 4; no glance-target ⇒ play; cats 6 and 3 play; else defer):

```python
    def ShouldPlayNow(self, rec) -> bool:
        cat = rec.category
        if cat == self.CAT_NON_INTERRUPTABLE:          # 2 — always
            return True
        if self._target_name is not None:              # pending move-target
            return cat == self.CAT_TURN_BACK           # only cat 4 gets through
        if self._glance_name is None:                  # no glance pending
            return True
        if cat in (self.CAT_GLANCE_BACK, self.CAT_TURN):  # 6, 3
            return True
        return False

    def PreparePlay(self, rec) -> None:
        self.SetFlags(rec.flags)
        if rec.category == self.CAT_TURN:              # 3 — move/turn target
            self._target_name = rec.name
            if self.IsStateSet(self.CS_GLANCING):      # 0x2
                self._glance_name = None
                self.ClearFlags(self.CS_GLANCING)
        elif rec.category == self.CAT_GLANCE:          # 5 — glance target
            self._glance_name = rec.name
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_anim_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_anim_queue.py
git commit -m "feat(character): SP2 t6 — ShouldPlayNow + PreparePlay

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `Special4` / `Special6` follow-up chaining

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: the builder-resolution helper (Task 11 introduces `self._resolve_anim(key)`; Task 7 uses it and a guard). Produces `Special4(rec) -> bool` and `Special6(rec) -> bool` (tier-0 §4.8): compose the follow-up name and chain it; return True if handled, False if declined.

- [ ] **Step 1–5:** Write tests that a `Special4` on a record with `_target_name` set composes `"%sBack%s"` from `_location_name`+`_target_name` and enqueues a follow-up (mock `self._resolve_anim` to return a sentinel); `Special6` composes `"%sGlanceAway%s"` from `_location_name`+`_glance_name`. Declines (returns False) when the relevant name buffer is unset or the builder resolves None. Implement per tier-0 §4.8 (guard on the name field; compose the name; `self._resolve_anim(name)`; if None return False; else enqueue via `SetCurrentAnimation` and return True). Follow the same RED→GREEN→commit rhythm. Commit message: `feat(character): SP2 t7 — Special4/Special6 chaining`.

> Full method bodies are in tier-0 `CharacterClass.md` §4.8 (`Special4` `0x0066BC40`,
> `Special6` `0x0066B8C0`). Transcribe them; keep `_resolve_anim` as the single
> builder-resolution seam introduced in Task 11.

---

## Task 8: `UpdateAnimationQueue` — the per-frame driver

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: `ReleaseCurrentAnimation`, `ShouldPlayNow`, `PreparePlay`, `Special4/6`, and the clip-player seam's `play`/`stop` (Task 10 — until then `_anim_play_now(rec)`/`_anim_stop_play(rec)` stubs). Produces `UpdateAnimationQueue() -> None` (tier-0 §4.8).

- [ ] **Steps:** TDD `UpdateAnimationQueue` per tier-0 §4.8:
  1. `ReleaseCurrentAnimation(0)`; if `_anim_current is not None` or no pending → return.
  2. Pop `_anim_pending[0]` as the candidate.
  3. Dispatch: `CAT_TURN_BACK`→`Special4`(if declines, `_anim_stop_play`); `CAT_GLANCE_BACK`→`Special6`(if declines, stop); else if `ShouldPlayNow`→`PreparePlay`+`_anim_play_now`, else `_anim_stop_play`.
  4. `self._anim_current = rec`.
  5. If this character is the current tooltip owner and `IsStateSet(CS_UI_DISABLED)`, fire the bridge `DropCharacterToolTips` seam (guarded; reuse the existing tooltip-owner check used elsewhere in `characters.py`).

  Add interim `_anim_play_now(rec)` (no-op) alongside the existing `_anim_stop_play`; Task 10 wires both. Tests: promotion of a pending record to current; a `CAT_TURN_BACK` candidate routes to `Special4`; a deferred candidate (blocked by a move-target) is stopped, not made current. RED→GREEN→commit. Message: `feat(character): SP2 t8 — UpdateAnimationQueue driver`.

---

## Task 9: `ClearAnimationsOfType` / `ClearExtraAnimations` / `ClearAnimations`

**Files:**
- Modify: `engine/appc/characters.py` (there is an existing `ClearAnimations`/`ClearAnimationsOfType`/`ClearExtraAnimations` surface from SP1 — replace with the queue-aware versions)
- Test: `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Produces the three clears (tier-0 §4.8): `ClearAnimationsOfType(cat)` stops/skips every record (current + pending) of that category; `ClearExtraAnimations()` = `ClearAnimationsOfType` for `0,1,5,6`; `ClearAnimations()` drains the whole queue + frees `_location_name`/`_target_name`/`_glance_name` (the SP2 half; SP3/SP4 add speak-queue/position-table draining later).

- [ ] **Steps:** TDD each. `ClearAnimationsOfType(cat)`: `_anim_stop_play` + drop every current/pending record whose `category==cat`. `ClearExtraAnimations`: calls it for `0,1,5,6`. `ClearAnimations`: stop+drop all, `_anim_current=None`, `_anim_pending=[]`, null the three name buffers. Tests assert counts + that a targeted category is removed while others remain. RED→GREEN→commit. Message: `feat(character): SP2 t9 — category-targeted animation clears`.

> Verify the existing `SetActive`/`ProcessEvent`/any current caller of the old
> `ClearAnimations*` still behaves; grep for callers and keep them green.

---

## Task 10: Demote `BridgeCharacterAnimController` to the clip-player seam

The integration task that carves the controller into the "hands" API and wires the `CharacterClass` queue's play/stop/is_active stubs to it. **Read `engine/bridge_character_anim.py` in full before editing.**

**Files:**
- Modify: `engine/bridge_character_anim.py`
- Modify: `engine/appc/characters.py` (give bodies to `_anim_play_now`/`_anim_stop_play`/`_anim_is_active` via `get_controller()`)
- Test: `tests/unit/test_bridge_character_anim.py` (adapt), `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Produces the seam on `BridgeCharacterAnimController`: `play(character, rec, on_complete=None)`, `is_active(character) -> bool`, `stop(character)`, `return_to_default(character)`, plus the retained per-frame `update(dt, *, renderer, anim_mgr=None)`.
- Consumes on `CharacterClass`: `_anim_play_now(rec)` → `get_controller().play(self, rec, on_complete=...)`; `_anim_stop_play(rec)` → `get_controller().stop(self)` for the record it owns; `_anim_is_active(rec)` → `get_controller().is_active(self)`.

- [ ] **Step 1: Characterize current behavior** — read the controller; list every behavior its `submit`/`request_*`/`_process_turn`/`_process_glance`/`_start_clip`/`_return_to_default`/node-coupling provides. Write/adjust tests that pin the KEPT playback behaviors (turn body+chair interleave via `_process_turn`/`_body_turns_officer`; `_real_duration`; return-to-default) so the carve cannot silently drop them.

- [ ] **Step 2: Carve the seam (RED→GREEN).** Keep `_start_clip`/`_real_duration`/`_return_to_default`/`_process_turn`/`_process_glance`/`_body_turns_officer`/`set_node_controller`/`update`/`reset`. Add `play(character, rec, on_complete)` that resolves the record (its `category`/`name`/`play` payload) into the same clip playback the old `request_*` used (route `CAT_TURN`/`CAT_TURN_BACK`→the turn path, `CAT_GLANCE`/`CAT_GLANCE_BACK`→the glance path, `CAT_NON_INTERRUPTABLE` move→the move/walk path, `CAT_BREATHE`/`CAT_INTERRUPTABLE`→`_start_clip`), reusing `_process_turn`/`_process_glance`/`_start_clip`. Add `is_active(character)` (was `is_busy`), `stop(character)`, `return_to_default(character)`. Remove `submit`/`request_turn`/`request_turn_back`/`request_turn_to`/`request_glance`/`request_default`/`is_busy`/`_Action` and the pending-lists queue layer. Wire the `CharacterClass` stubs.

- [ ] **Step 3: Verify.** `uv run pytest tests/unit/test_bridge_character_anim.py tests/unit/test_bridge_character_anim_complete.py tests/unit/test_bridge_character_anim_reentrancy.py tests/unit/test_character_anim_queue.py -q` — all green. Adapt tests that called the removed `submit`/`request_*` to drive through `CharacterClass` action methods (Tasks 11–12) or the seam.

- [ ] **Step 4: Commit** — `feat(character): SP2 t10 — demote BridgeCharacterAnimController to clip-player seam`.

> This task will surface which callers still use the removed API; those are
> re-pointed in Task 13. Leaving them temporarily broken between t10 and t13 is
> acceptable ONLY if the full suite is not run between them — but per the gate,
> run t13 immediately after and do not leave the tree red across a stopping point.
> If safer, fold Task 13's re-pointing into this task's commit.

---

## Task 11: Action methods, part 1 — `Breathe`, `MoveTo`, `PlayAnimation`, `PlayAnimationFile`

**Files:**
- Modify: `engine/appc/characters.py` (replace the `pass` stubs)
- Test: `tests/unit/test_character_anim_queue.py`, `tests/unit/test_characters.py`

**Interfaces:**
- Consumes: `SetCurrentAnimation`, `SetFlags`, `_location_name`; introduces `self._resolve_anim(key) -> play|None` — the single builder-resolution seam (composes nothing itself; takes a fully-composed key, resolves via `engine/appc/bridge_placement.resolve_builder(self, key)`; returns None when unresolved). Produces real `Breathe`/`MoveTo`/`PlayAnimation`/`PlayAnimationFile` (tier-0 §4.10 + the mode table, spec §4.6).

- [ ] **Steps:** TDD each method against tier-0 §4.10:
  - `_resolve_anim(key)` — resolve `bridge_placement.resolve_builder(self, key)`; return None if unresolved. (Mock in tests.)
  - `Breathe(param=0)` — only if idle (not animating, nothing queued, `_target_name is None`, not `IsStateSet(CS_GLANCING)`); compose `"%sBreathe"` from `_location_name`, fallback bare `"Breathe"`; if resolved, `SetCurrentAnimation(anim, CAT_BREATHE, 0, None)`; return True/False.
  - `MoveTo(dest, completed=None)` — compose `"%sTo%s"`; `SetFlags(CS_UI_DISABLED)`; `SetCurrentAnimation(anim, CAT_NON_INTERRUPTABLE, CS_UI_DISABLED, None)`; return True.
  - `PlayAnimation(name, mode=1, done=None)` — resolve `name`; mode table (spec §4.6): `mode>0`→cat 1/flags 0; `mode==0`→cat 2/flags 8 (done 0x800); `mode<0`→cat 2/flags 0.
  - `PlayAnimationFile(file, mode=1, done=None)` — build from file; `mode==0`→cat 2/flags 8 else cat 1/flags 0.
  Pin: key composition (assert the string passed to `_resolve_anim`), the category+flags handed to `SetCurrentAnimation`, and `Breathe`'s idle gate. RED→GREEN→commit. Message: `feat(character): SP2 t11 — real Breathe/MoveTo/PlayAnimation[File]`.

---

## Task 12: Action methods, part 2 — `TurnTowards`, `TurnBack`, `GlanceAt`, `GlanceAway`, `LookAtMe`

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_anim_queue.py`, `tests/unit/test_characters.py`

**Interfaces:**
- Produces real `TurnTowards`/`TurnBack`/`GlanceAt`/`GlanceAway`/`LookAtMe` (tier-0 §4.10). `GlanceAt` carries the name (cat 5); `GlanceAway`/`TurnBack` clear the interruptable pair/set first; `LookAtMe` routes to the camera-watch seam (NOT the queue).

- [ ] **Steps:** TDD each per tier-0 §4.10:
  - `GlanceAt(name, done=None)` — compose `"%sGlance%s"`; `ClearAnimationsOfType(0); ClearAnimationsOfType(1)`; `SetCurrentAnimation(anim, CAT_GLANCE, 2, name)`.
  - `GlanceAway(done=None)` — clear `0,1`; `SetCurrentAnimation(seq, CAT_GLANCE_BACK, 0, None)`.
  - `TurnBack(done=None)` — clear `0,1,5,6`; `SetCurrentAnimation(seq, CAT_TURN_BACK, 0, None)`.
  - `TurnTowards(name, arg2=None)` — acts only when active and `name=="Captain"`; builds the SDK sequence; returns False (per tier-0 — it always returns False).
  - `LookAtMe(...)` — route to `bridge_camera_watch.get_controller()` (the separate subsystem), not the queue.
  Pin category/flags/name and the clear-set ordering. RED→GREEN→commit. Message: `feat(character): SP2 t12 — real TurnTowards/TurnBack/Glance{At,Away}/LookAtMe`.

---

## Task 13: Collapse the two doors + re-point callers

**Files:**
- Modify: `engine/appc/ai.py` (`CharacterAction.Play` — the `AT_*` dispatch)
- Modify: `engine/bridge_idle_gestures.py`, `engine/bridge_hit_reactions.py`, `engine/bridge_character_walk.py`
- Modify: `engine/appc/characters.py` (`_notify_menu`)
- Modify: `engine/host_loop.py` (per-frame tick → `UpdateAnimationQueue` for each active character + clip-player `update`)
- Test: `tests/unit/test_character_action_verbs.py`, `test_character_action_glance.py`, `test_character_action_watch.py`, `test_crew_menu_turn.py`, `test_bridge_character_anim*`

**Interfaces:**
- Consumes: the real action methods (Tasks 11–12); the clip-player seam (Task 10).

- [ ] **Step 1:** Re-point `CharacterAction.Play()`'s `AT_*` branches to the `CharacterClass` methods: `AT_MOVE`→`MoveTo`, `AT_TURN`/`AT_TURN_NOW`→`TurnTowards`, `AT_TURN_BACK`/`AT_TURN_BACK_NOW`→`TurnBack`, `AT_GLANCE_AT`→`GlanceAt`, `AT_GLANCE_AWAY`→`GlanceAway`, `AT_BREATHE`/`AT_FORCE_BREATHE`→`Breathe`, `AT_PLAY_ANIMATION`→`PlayAnimation`, `AT_PLAY_ANIMATION_FILE`→`PlayAnimationFile`, `AT_DEFAULT`→queue drain/`return_to_default`. Leave speak (`AT_SAY_LINE`/`AT_SPEAK_LINE*`), camera (`AT_WATCH_ME`/`AT_LOOK_AT_ME*`/`AT_STOP_WATCHING_ME`), menu (`AT_MENU_UP`/`DOWN`), status, audio, initiative, active branches unchanged (SP3/SP4/separate subsystems — but `AT_BECOME_ACTIVE`/`AT_BECOME_INACTIVE`→`SetActive` once Task 14 lands). Preserve each branch's completion semantics (`Completed()` timing) so mission `TGSequence`s still advance.

- [ ] **Step 2:** `bridge_idle_gestures` → `character.Breathe()` / a random-animation enqueue; `bridge_hit_reactions` → enqueue the reaction record via `SetCurrentAnimation` (engine-driven, sibling §6.4); `bridge_character_walk` → drive `AT_MOVE` clip via the seam; `_notify_menu` → `self.TurnTowards("Captain")`.

- [ ] **Step 3:** `host_loop` per-frame bridge tick: call `character.UpdateAnimationQueue()` for each active bridge character (replacing the controller-queue tick), then the clip-player `update(dt, renderer=…, anim_mgr=…)` for playback. Read the current tick site (`engine/host_loop.py:~2058`) and preserve its gating/ordering.

- [ ] **Step 4: Verify** the full character/bridge suite green; adapt tests that asserted the old `request_*`/`submit` path. `uv run pytest tests/unit -q -k "character or bridge or menu or anim"`. Commit: `feat(character): SP2 t13 — collapse verb doors onto CharacterClass; re-point callers`.

---

## Task 14: `SetActive` faithfulness (deferred from SP1)

**Files:**
- Modify: `engine/appc/characters.py` (`SetActive`, and the SP1-deferred ctor default)
- Test: `tests/unit/test_characters.py`, `tests/unit/test_character_anim_queue.py`

**Interfaces:**
- Consumes: `ClearAnimationsOfType` (Task 9). Produces faithful `SetActive(bActive)` (tier-0 §4.2) + the RE inactive constructor default.

- [ ] **Steps:** TDD:
  - `SetActive(bActive)` stores the arg (today it ignores it and always sets active); if `not bActive` → `ClearAnimationsOfType(0); (1); (5); (6)` (the interruptable set).
  - Apply the SP1-deferred inactive ctor default ONLY after confirming live bridge-load callers still activate their officers (grep `SetActive` callers; the walk-on/bridge-load path calls `SetActive(1)`). If flipping the default breaks a live path, keep the current default and note it — do not regress bridge load.
  Tests: `SetActive(0)` clears queued interruptable records but leaves a queued `CAT_NON_INTERRUPTABLE`; `SetActive(1)` marks active. RED→GREEN→commit. Message: `feat(character): SP2 t14 — SetActive honors arg + clears interruptable anims`.

---

## Task 15: Full gate + live-verification checklist

**Files:** none (verification only).

- [ ] **Step 1:** `grep -n "_current_anim\|\.submit(\|\.request_turn\|\.is_busy(" engine/` — confirm the removed controller-queue API has no surviving callers (except inside the demoted controller's own history, which should be gone). Any hit is an un-re-pointed caller — fix it.

- [ ] **Step 2:** `scripts/check_tests.sh` — green, or only the baselined failures in `tests/known_failures.txt`. Any other failure is an SP2 regression; fix before proceeding.

- [ ] **Step 3: Live-verification checklist for Mark** (SP2 is player-visible; do NOT claim done from tests). Present this list for Mark to run in-game and confirm:
  1. Bridge idle gestures still play (officers breathe/fidget at station).
  2. Turn-to-captain on crew-menu open still turns the officer (and the chair).
  3. A hull hit still triggers crew hit reactions.
  4. The E1M1 walk-on (officer walks to station) still completes.
  5. A scripted glance (`AT_GLANCE_AT`) still plays and returns to rest.
  6. A direct `pChar.MoveTo(...)`/`TurnBack()` from a mission now fires (the new door) — pick a mission that calls one, or verify via the dev console.
  7. No officer freezes mid-animation or fails to return to rest (queue drains).

- [ ] **Step 4:** Only after Mark confirms the live checklist, the branch is done. Record the live-pass result in the ledger before finishing the branch.

---

## Self-Review

**Spec coverage:** §4.1 queue model → T2; §4.2 SetCurrentAnimation → T3; §4.3 UpdateAnimationQueue → T8; §4.4 release/cleanup → T5,T9; §4.5 predicates → T4; §4.6 action methods → T11,T12; §4.7 clip-player seam → T10; §4.8 door collapse → T13; §4.9 SetActive → T14; §5 referee → T1; §6 verification → T15. All covered.

**Placeholder scan:** Tasks 7, 8, 9, 11, 12, 13, 14 use a "TDD per tier-0 §X, pin these observables" form with the exact contracts, categories, flags, and file references rather than transcribed literal bodies, because those bodies come verbatim from tier-0 `CharacterClass.md` §4.8/§4.10 (which the implementer has) and/or require reading live code (T10/T13). This is deliberate for a refactor of this size; each such task names the exact method, category/flags, and the observable to assert. Tasks 1–6 carry complete literal code.

**Type consistency:** `AnimRec` (fields `category/name/flags/play`) and the verdict constants (`STOP_OLD/REJECT_NEW/STOP_BOTH/COEXIST`) are defined in T1 and used consistently (T3, T5, T6, T8). The clip-player seam names (`play`/`is_active`/`stop`/`return_to_default`) and the `CharacterClass` stubs (`_anim_play_now`/`_anim_stop_play`/`_anim_is_active`) are introduced as stubs in T3/T5/T8 and given bodies in T10 — consistent throughout. `_resolve_anim` is introduced in T11 and consumed by T7 (note: T7 precedes T11 in number but depends on `_resolve_anim` — reorder so T11's `_resolve_anim` seam lands before T7, OR have T7 introduce the `_resolve_anim` stub; the implementer should introduce `_resolve_anim` as a stub in T7 and give it its body in T11).

**Known ordering fix:** T7 (`Special4/6`) depends on `_resolve_anim` from T11. Resolution: T7 introduces `_resolve_anim` as a mockable stub (raise/return None by default) and T11 gives it its real `bridge_placement` body — the same introduce-stub-then-implement pattern used for the clip-player seam.

---

# REVISED integration plan — T10–T15 (supersedes the T10–T15 above)

> Re-planned 2026-07-21 (Mark) after reading `engine/bridge_character_anim.py` in full. The controller
> is hard-won, live-verified code (body/chair coupling, `on_complete` rescue, re-entrancy, and a
> completion guarantee that advances mission `TGSequence`s — wrong ⇒ **missions hang**). So SP2 does
> **not** rewrite its playback; the queue **drives** the controller through one thin seam, threading
> the completion callback on the record. See spec §4.7 (refined). Design also in the ledger.

## Task 10 (revised): Completion fields on the record + `SetCurrentAnimation` threading

**Files:** Modify `engine/appc/character_anim_queue.py` (extend `AnimRec`), `engine/appc/characters.py` (`SetCurrentAnimation` signature). Test: `tests/unit/test_character_anim_queue.py`.

- Extend `AnimRec` with `on_complete=None`, `hold=False`, `now=False`, `done_flags=0` (all defaulted — backward compatible; existing constructions unaffected).
- Extend `SetCurrentAnimation(self, anim, category, flags=0, name=None, on_complete=None, hold=False, now=False)` — stamp these onto the built record. All new params default so existing callers are unchanged.
- Tests: `SetCurrentAnimation(..., on_complete=cb)` produces a queued record carrying `cb`; defaults are None/False/0.
- Commit: `feat(character): SP2 t10 — completion fields on AnimRec + SetCurrentAnimation`.

## Task 11 (revised): The controller clip-player seam (`play_record`/`is_active`/`stop`)

**Files:** Modify `engine/bridge_character_anim.py`. Test: `tests/unit/test_bridge_character_anim.py` (+ new cases).

**Read the controller first.** Keep EVERYTHING (`_process_turn`/`_process_glance`/`_start_clip`/`_return_to_default`/`_body_turns_officer`/`submit`/`request_*`/`update`/pending lists/node coupling) intact. ADD:
- `is_active(self, character) -> bool` — alias of the existing `is_busy` (keep `is_busy` too, or make `is_busy` call `is_active`).
- `stop(self, character) -> None` — evict the character's `_active` entry and any pending turn/glance/default for its iid (best-effort; never raise). Fire a rescued `on_complete` off an evicted `_Action` (mirror the existing rescue in `submit`/`request_default`) so a waiting sequence never hangs.
- `play_record(self, character, rec) -> None` — map `rec.category` to the EXISTING deferred playback, threading `rec.on_complete`/`rec.hold`/`rec.now`:
  - `CAT_TURN (3)` → `request_turn_to(character, rec.name or "Captain", back=False, hold=rec.hold, now=rec.now, on_complete=rec.on_complete)`.
  - `CAT_TURN_BACK (4)` → `request_turn_to(character, rec.name or "Captain", back=True, hold=rec.hold, now=rec.now, on_complete=rec.on_complete)`.
  - `CAT_GLANCE (5)` / `CAT_GLANCE_BACK (6)` → `request_glance(character, rec.name or "", on_complete=rec.on_complete)`.
  - `CAT_NON_INTERRUPTABLE (2)` (move) → the move/walk path: submit the resolved move clip (or route to the walk controller if that is where AT_MOVE playback lives — read `bridge_character_walk.py`); thread `on_complete`.
  - `CAT_BREATHE (0)` / `CAT_INTERRUPTABLE (1)` → `submit(character, clips, priority, hold=rec.hold, on_complete=rec.on_complete)` where `clips` come from `rec.play` (a resolved clip descriptor) — read how `submit` expects `clips` and adapt; if `rec.play` is already a clip list use it, else resolve via the existing `capture_registered_clip` path the controller already uses.
  - Import the `CAT_*` values from `CharacterClass` or duplicate the small int constants locally with a comment (avoid a circular import — the controller must not import `characters` at module load; do a local import inside `play_record` if needed).
- Tests: with a fake character (`_render_instance` set) + a FakeRenderer, `play_record` with a `CAT_TURN` rec appends a pending turn carrying the `on_complete`; a `CAT_GLANCE` rec appends a pending glance; `stop` evicts + fires a rescued callback; `is_active` reflects `_active`. Reuse the existing test harness in `test_bridge_character_anim.py`.
- Commit: `feat(character): SP2 t11 — controller play_record/is_active/stop seam (playback intact)`.

## Task 12 (revised): Wire the CharacterClass seam + `_resolve_anim` + real action methods

**Files:** Modify `engine/appc/characters.py`. Test: `tests/unit/test_character_anim_queue.py`, `tests/unit/test_characters.py`.

- Wire the three seam stubs (headless-guarded — `get_controller()` may be None in unit tests):
  ```python
  def _anim_play_now(self, rec):
      c = _anim_controller()
      if c is not None: c.play_record(self, rec)
  def _anim_stop_play(self, rec):
      c = _anim_controller()
      if c is not None: c.stop(self)
  def _anim_is_active(self, rec) -> bool:
      c = _anim_controller()
      return bool(c.is_active(self)) if c is not None else False
  ```
  where `_anim_controller()` lazily imports `engine.bridge_character_anim.get_controller` (guard ImportError → None). **Keep CharacterClass renderer-free** — never import the renderer.
- Give `_resolve_anim(key)` its real body: `from engine.appc import bridge_placement; return bridge_placement.resolve_builder(self, key)` (guard exceptions → None). This is the single builder-resolution seam (used by the action methods and Special4/6).
- Make the action methods real (tier-0 §4.10; reference `docs/engine/characterclass-reference.md`), threading the SDK completion callback onto the record via `SetCurrentAnimation(..., on_complete=...)`:
  - `Breathe`, `MoveTo`, `PlayAnimation`, `PlayAnimationFile` (this task) — key composition + category/flags per the mode table, `on_complete` threaded.
- Tests: each method composes the expected key (assert via a capturing `_resolve_anim`), enqueues a record with the right category/flags/`on_complete`; `Breathe`'s idle gate; headless `_anim_is_active` returns False (no controller). **This task heals the predicate transitional failures** for the queue-driven path — verify `test_character_animation_state.py` state (some may need updating to the new model in T14).
- Commit: `feat(character): SP2 t12 — wire clip-player seam + resolve + Breathe/MoveTo/PlayAnimation*`.

## Task 13 (revised): Remaining action methods — `TurnTowards`/`TurnBack`/`Glance{At,Away}`/`LookAtMe`

**Files:** Modify `engine/appc/characters.py`. Test: `tests/unit/test_character_anim_queue.py`.

- Implement per tier-0 §4.10 (as the original T12), threading `on_complete`, using `_resolve_anim`. `GlanceAt` carries the name (cat 5); `GlanceAway`/`TurnBack` clear the interruptable set first; `LookAtMe` routes to `bridge_camera_watch` (NOT the queue).
- Commit: `feat(character): SP2 t13 — TurnTowards/TurnBack/Glance{At,Away}/LookAtMe`.

## Task 14 (revised): Collapse the two doors + re-point callers + host tick + heal transitional tests

**Files:** Modify `engine/appc/ai.py` (`CharacterAction.Play`), `engine/bridge_idle_gestures.py`, `engine/bridge_hit_reactions.py`, `engine/bridge_character_walk.py`, `engine/appc/characters.py` (`_notify_menu`), `engine/host_loop.py` (tick). Update the transitional tests. Tests: `test_character_action_verbs.py`, `test_character_animation_state.py`, `test_character_action_glance.py`, `test_crew_menu_turn.py`, `test_bridge_character_anim*`.

- `CharacterAction.Play()` `AT_*` → the `CharacterClass` methods, passing `self.Completed` as the completion callback: `AT_MOVE`→`MoveTo(detail, self.Completed)`, `AT_TURN`/`AT_TURN_NOW`→`TurnTowards`, `AT_TURN_BACK*`→`TurnBack`, `AT_GLANCE_AT`→`GlanceAt`, `AT_GLANCE_AWAY`→`GlanceAway`, `AT_BREATHE`/`AT_FORCE_BREATHE`→`Breathe`, `AT_PLAY_ANIMATION[_FILE]`→`PlayAnimation[File]`, `AT_DEFAULT`→queue drain + controller `return_to_default`. Preserve the exact completion timing of every branch (speak/camera/menu branches unchanged; `AT_BECOME_ACTIVE/INACTIVE`→`SetActive` once T15 lands). **The `on_complete=self.Completed` thread is what keeps mission `TGSequence`s advancing — verify with the existing multi-action-sequence tests.**
- `bridge_idle_gestures` → `character.Breathe()` / random-anim enqueue; `bridge_hit_reactions` → enqueue via `SetCurrentAnimation` (engine-driven, sibling §6.4); `bridge_character_walk` → drive `AT_MOVE` via the seam; `_notify_menu` → `self.TurnTowards("Captain")`.
- `host_loop` tick: `character.UpdateAnimationQueue()` for each active bridge character, ordered **before** the existing controller `update()` (read `host_loop.py:~2058`).
- **Heal the 7 tracked transitional failures.** Re-run them; the verb tests (`test_character_action_verbs.py`) heal once the door is collapsed + a controller is present. The `test_character_animation_state.py` tests encode the OLD single-slot model (`set_current_animation` legacy + expect "animating" with no clip) — update them to the new queue model (enqueue + a fake controller so `is_active` is True, or assert `IsGoingToAnimate`), NOT by weakening assertions. Any legacy `set_current_animation` still referenced should be reconciled.
- Commit: `feat(character): SP2 t14 — collapse verb doors, re-point callers, host tick; heal transitional tests`.

## Task 15 (revised): `SetActive` faithfulness + full gate + live checklist

**Files:** Modify `engine/appc/characters.py` (`SetActive` + SP1-deferred ctor default). Verification only for the gate/live parts.

- `SetActive(bActive)` (tier-0 §4.2): store the arg; if `not bActive` → `ClearAnimationsOfType(0); (1); (5); (6)`. Apply the SP1-deferred inactive ctor default ONLY after confirming live bridge-load callers still `SetActive(1)` their officers (grep first; do not regress bridge load). Tests: deactivate clears queued interruptable records, leaves a `CAT_NON_INTERRUPTABLE`.
- **Full gate:** `grep -n "_current_anim\|\.request_turn\b\|\.is_busy(" engine/` for surviving external callers of the removed door (internal controller uses are fine). `scripts/check_tests.sh` — MUST be fully green (the 7 transitional failures resolved). Any other failure is an SP2 regression.
- **Live-verification checklist for Mark** (SP2 is player-visible; do NOT claim done from tests):
  1. Bridge idle gestures still play. 2. Turn-to-captain on crew-menu open turns officer + chair. 3. Hull hit → crew hit reactions. 4. E1M1 walk-on completes. 5. Scripted glance plays + returns to rest. 6. A direct `pChar.MoveTo(...)`/`TurnBack()` from a mission fires (new door). 7. **A multi-action mission cutscene (speak→turn→say) advances to completion — no hang** (this is the completion-plumbing acceptance check). 8. No officer freezes mid-animation.
  Record the live-pass result in the ledger before finishing the branch.
- Commit (if the gate needed a fix): `feat(character): SP2 t15 — SetActive faithfulness + gate green`.
