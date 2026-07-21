# CharacterClass SP1 — Owner Skeleton + State Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `CharacterClass`'s `set`-based state with the original engine's faithful `CS_*` flag **bitfield** (adding the currently-dead `SetFlags`/`ClearFlags`), disentangle the tooltip-status strings from the flags, seed the RE'd constructor defaults, and add named sub-component slots — a pure-substrate refactor with no player-visible change.

**Architecture:** `CharacterClass` becomes the owner/facade. State lives in three structured attributes — `_flags: int` (the `CS_*` bitfield), `_hidden: bool` (the not-stored `CS_HIDDEN`/`CS_VISIBLE` cull toggle, read every frame by the host-loop visibility pull), and `_status: dict` (tooltip display strings). Visibility stays a **pull** model: methods only mutate `_hidden`; the host loop culls. Later sub-projects (SP2 AnimationQueue, SP3 SpeakQueue+PhonemeMap, SP4 StatusMap+zoom+menu) plug into named slots this task creates.

**Tech Stack:** Python 3 (pytest); the App shim under `engine/appc/`. No C++ / native changes.

**Spec:** `docs/superpowers/specs/2026-07-21-characterclass-reimplementation-sp1-design.md`

## Global Constraints

- **Pure Python3, no C++.** Mirror the original's observable semantics, not its memory layout.
- **Evidence tier order:** the supplied `CharacterClass.md` (tier 0, recompiled + gameplay-tested) outranks all; exact `CS_*`/`CPT_*` values come from the sibling repo's `stbc_constants.csv` (tier 1, where tier 0 is silent).
- **Shared checkout:** stage commits with **explicit pathspecs only** — never `git add -A`/`.`. The tree carries another session's uncommitted `engine/appc/objects.py` and `engine/host_loop.py`; never stage those.
- **Test gate:** the authoritative check is `scripts/check_tests.sh` (pytest + ctest, diffed against `tests/known_failures.txt`). Per-task steps run focused pytest; run the full gate before the final commit.
- **No player-visible change in SP1** — do not claim in-game behavior works; verification is the gate + equivalence.
- **Visibility is a pull model** — `SetFlags`/`ClearFlags`/`SetHidden` only mutate `_hidden`; never push a renderer call (host loop reads `IsHidden()` at `host_loop.py:4759`/`:4787`).

## File Structure

- **Modify:** `engine/appc/characters.py` — constants block (`CS_*`, `CPT_*`), `__init__` (state attrs, ctor defaults, sub-component slots), the state methods (`SetFlags`/`ClearFlags`/`IsStateSet`/`SetStatus`/`ClearStatus`/`SetHidden`/`IsHidden`/`SetStanding`/`SetInitiative`/`Is*`), and `ProcessEvent`.
- **Modify:** `tests/unit/test_characters.py` — rewrite the 3 tests that encode the old conflated/ordinal behavior (`test_set_status_and_is_state_set`, `test_set_status_accepts_string_label`, `test_set_status_int_and_string_independent`, and the `CS_HIDDEN == 5` assertion in `test_app_exposes_character_constants`).
- **Create:** `tests/unit/test_character_state_flags.py` — the new faithful-model coverage (bit table, `SetFlags`/`ClearFlags` cull dispatch, `0x8`→`MenuDown`, status disentanglement, ctor defaults, sub-component slots).

---

## Task 1: Ground-truth constant values (`CS_*` bitfield, `CPT_*`)

**Files:**
- Modify: `engine/appc/characters.py:314-327` (`CS_*`), `:392-395` (`CPT_*`)
- Modify: `tests/unit/test_characters.py:542`
- Test: `tests/unit/test_character_state_flags.py` (new)

**Interfaces:**
- Produces: the `CharacterClass.CS_*` class attributes as real bit values and `CPT_*` as `-1/0/1/2`. Consumed by every later task.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_character_state_flags.py`:

```python
"""SP1 — faithful CS_* flag bitfield + ctor state model (CharacterClass.md)."""
from engine.appc.characters import CharacterClass


def test_cs_flags_are_real_bit_values():
    # Values extracted from stbc_constants.csv (tier 1; tier-0 doc gives the
    # bit MEANINGS in CharacterClass.md §3, not the public value table).
    assert CharacterClass.CS_IDLE == 0x0
    assert CharacterClass.CS_STANDING == 0x1
    assert CharacterClass.CS_GLANCING == 0x2
    assert CharacterClass.CS_TURNED == 0x4
    assert CharacterClass.CS_UI_DISABLED == 0x8
    assert CharacterClass.CS_HIDDEN == 0x10
    assert CharacterClass.CS_INITIATIVE == 0x20
    assert CharacterClass.CS_MIDDLE == 0x40
    assert CharacterClass.CS_SEATED == 0x80
    assert CharacterClass.CS_VISIBLE == 0x100
    assert CharacterClass.CS_CLEAR_GLANCE == 0x200
    assert CharacterClass.CS_CLEAR_TURNED == 0x400
    assert CharacterClass.CS_UI_ENABLED == 0x800
    assert CharacterClass.CS_STOP_INITIATIVE == 0xFD8


def test_cpt_phoneme_channels_are_corrected():
    assert CharacterClass.CPT_DEFAULT == -1
    assert CharacterClass.CPT_BLINK == 0
    assert CharacterClass.CPT_SPEAK == 1
    assert CharacterClass.CPT_EYEBROW == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v`
Expected: FAIL (current `CS_STANDING == 1` but `CS_TURNED == 3`, `CS_HIDDEN == 5`, `CPT_DEFAULT == 0`).

- [ ] **Step 3: Replace the `CS_*` block** at `engine/appc/characters.py:314-327` with:

```python
    # CS_* state flags — a BITFIELD (m_flags @ +0x80). Values from
    # stbc_constants.csv; bit meanings from CharacterClass.md §3. 0x10/0x100
    # are NOT stored — they toggle the model-cull (hidden) state.
    CS_IDLE             = 0x0
    CS_STANDING         = 0x1
    CS_GLANCING         = 0x2
    CS_TURNED           = 0x4
    CS_UI_DISABLED      = 0x8      # busy / menu-suppressed (MoveTo sets this)
    CS_HIDDEN           = 0x10     # not stored: hidden-state ON  (cull)
    CS_INITIATIVE       = 0x20
    CS_MIDDLE           = 0x40
    CS_SEATED           = 0x80
    CS_VISIBLE          = 0x100    # not stored: hidden-state OFF (show)
    CS_CLEAR_GLANCE     = 0x200
    CS_CLEAR_TURNED     = 0x400
    CS_UI_ENABLED       = 0x800
    CS_STOP_INITIATIVE  = 0xFD8    # composite clear-mask
```

- [ ] **Step 4: Replace the `CPT_*` block** at `engine/appc/characters.py:392-395` with:

```python
    # Phoneme-channel constants (values from stbc_constants.csv).
    CPT_DEFAULT = -1
    CPT_BLINK   = 0
    CPT_SPEAK   = 1
    CPT_EYEBROW = 2
```

- [ ] **Step 5: Update the stale ordinal assertion** at `tests/unit/test_characters.py:542`:

```python
    assert App.CharacterClass.CS_HIDDEN == 0x10
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_character_state_flags.py tests/unit/test_characters.py::test_app_exposes_character_constants tests/unit/test_bridge_event_constants.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_state_flags.py tests/unit/test_characters.py
git commit -m "feat(character): SP1 t1 — CS_* flag bit values + CPT_* corrections

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Replace the `set` state with the faithful bitfield model

This is the core atomic task: every consumer of `self._states` changes together. `SetFlags`/`ClearFlags` (currently silent `__getattr__` no-ops) become real; `IsStateSet` becomes flag-only; `SetStatus`/`ClearStatus` route strings to `_status`; `SetHidden`/`IsHidden` back onto `_hidden`; `ProcessEvent` is re-expressed.

**Files:**
- Modify: `engine/appc/characters.py` — `__init__` (`:435`), the state region (`:553-599`), `ProcessEvent` (`:603-629`)
- Modify: `tests/unit/test_characters.py:112-118, 477-491`
- Test: `tests/unit/test_character_state_flags.py`

**Interfaces:**
- Consumes: `CharacterClass.CS_*` bit values (Task 1).
- Produces:
  - `self._flags: int`, `self._hidden: bool`, `self._status: dict` (state attributes).
  - `SetFlags(mask: int) -> None`, `ClearFlags(mask: int) -> None`, `IsStateSet(mask: int) -> int`.
  - `SetInitiative(on) -> None`, `IsInitiativeOn() -> int`.
  - `SetStatus(state) -> None` / `ClearStatus(state) -> None` route non-flag values to `_status`.
  - `GetStatusText(key=None)` helper returning the stored status string(s) (interim; SP4 replaces with the real widget StatusMap).

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_character_state_flags.py`:

```python
from engine.appc.characters import CharacterClass_Create


def test_setflags_clearflags_isstateset_roundtrip_on_stored_bit():
    c = CharacterClass_Create()
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
    c.SetFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 1
    # IsStateSet requires ALL bits of the mask set.
    c.SetFlags(CharacterClass.CS_INITIATIVE)
    assert c.IsStateSet(CharacterClass.CS_STANDING | CharacterClass.CS_INITIATIVE) == 1
    c.ClearFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
    assert c.IsStateSet(CharacterClass.CS_INITIATIVE) == 1


def test_hidden_bits_are_not_stored_in_flags():
    # CS_HIDDEN (0x10) / CS_VISIBLE (0x100) toggle the hidden-state, never the
    # flag word — so IsStateSet(CS_HIDDEN) is always 0 (CharacterClass.md §3).
    c = CharacterClass_Create()
    c.SetFlags(CharacterClass.CS_HIDDEN)
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 0
    assert c.IsHidden() == 1
    c.SetFlags(CharacterClass.CS_VISIBLE)
    assert c.IsHidden() == 0
    c.ClearFlags(CharacterClass.CS_HIDDEN)   # ClearFlags(0x10) -> show
    assert c.IsHidden() == 0
    c.ClearFlags(CharacterClass.CS_VISIBLE)  # ClearFlags(0x100) -> hide
    assert c.IsHidden() == 1


def test_setinitiative_toggles_flag():
    c = CharacterClass_Create()
    c.SetInitiative(1)
    assert c.IsInitiativeOn() == 1
    c.SetInitiative(0)
    assert c.IsInitiativeOn() == 0


def test_setstatus_string_is_separate_from_flags():
    # Character SetStatus takes a tooltip display string (SDK:
    # pMiguel.SetStatus(db.GetString("Waiting"))). It must NOT touch the flags.
    c = CharacterClass_Create()
    c.SetStatus("Waiting")
    assert c.GetStatusText() == "Waiting"
    assert c._flags == 0
    c.ClearStatus("Waiting")
    assert c.GetStatusText() in (None, "")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k "flags or hidden or initiative or status"`
Expected: FAIL (`SetFlags` is a silent no-op → `IsStateSet` stays 0; `GetStatusText`/`SetInitiative` absent).

- [ ] **Step 3: Swap the state attributes in `__init__`** — replace `engine/appc/characters.py:435` (`self._states: set = set()`) with:

```python
        self._flags: int = 0              # CS_* bitfield (m_flags @ +0x80)
        self._hidden: bool = False        # CS_HIDDEN/CS_VISIBLE cull toggle
        self._status: dict = {}           # tooltip display strings (SP4 -> StatusMap)
```

- [ ] **Step 4: Replace the state-method region** `engine/appc/characters.py:553-599` (from `def _coerce_state` through `IsUIDisabled`) with:

```python
    # ── State flags: the faithful CS_* bitfield (CharacterClass.md §4.3) ─────
    def SetFlags(self, mask) -> None:
        mask = int(mask)
        if mask == 0:
            return
        if mask == self.CS_HIDDEN:        # 0x10 — not stored; hide (pull model)
            self._hidden = True
            return
        if mask == self.CS_VISIBLE:       # 0x100 — not stored; show
            self._hidden = False
            return
        self._flags |= mask
        # BC menu suppression: becoming busy (0x8) drops an open menu.
        if (self._flags & self.CS_UI_DISABLED) and self.IsMenuUp():
            self.MenuDown()

    def ClearFlags(self, mask) -> None:
        mask = int(mask)
        if mask == 0:
            return
        if mask == self.CS_HIDDEN:        # ClearFlags(0x10) -> show
            self._hidden = False
            return
        if mask == self.CS_VISIBLE:       # ClearFlags(0x100) -> hide
            self._hidden = True
            return
        self._flags &= ~mask

    def IsStateSet(self, mask) -> int:
        mask = int(mask)
        return 1 if (self._flags & mask) == mask else 0

    # ── Tooltip status strings — SEPARATE from the flag bitfield ────────────
    # SDK calls SetStatus with a localized display string
    # (pMiguel.SetStatus(db.GetString("Waiting"))). Stored under a single
    # interim key; SP4 replaces this with the real keys-0..5 StatusMap widgets.
    def SetStatus(self, state, *args) -> None:
        self._status["text"] = state

    def ClearStatus(self, state=None, *args) -> None:
        self._status.pop("text", None)

    def GetStatusText(self, key="text"):
        return self._status.get(key)

    # ── Visibility (pull model): mutate _hidden; host loop culls per-frame ──
    def SetHidden(self, hidden=1) -> None:
        self._hidden = bool(hidden)
    def IsHidden(self) -> int:                    return 1 if self._hidden else 0

    def SetStanding(self, value=None) -> None:
        if value is None:
            self.SetFlags(self.CS_STANDING)
        else:
            self._data["StandingMode"] = int(value)
    def IsStanding(self) -> int:                  return self.IsStateSet(self.CS_STANDING)

    def SetInitiative(self, on=1) -> None:
        if on:
            self.SetFlags(self.CS_INITIATIVE)
        else:
            self.ClearFlags(self.CS_INITIATIVE)
    def IsInitiativeOn(self) -> int:              return self.IsStateSet(self.CS_INITIATIVE)

    def IsTurned(self) -> int:                    return self.IsStateSet(self.CS_TURNED)
    def IsGlancing(self) -> int:                  return self.IsStateSet(self.CS_GLANCING)
    def IsUIDisabled(self) -> int:                return self.IsStateSet(self.CS_UI_DISABLED)
```

> Note: `SetInitiative`/`IsInitiativeOn` here supersede the `__getattr__`/`_data`
> fallbacks for those names. Delete the now-shadowed `IsInitiativeOn` at the old
> line (`engine/appc/characters.py:724-725`) so there is one definition.

- [ ] **Step 5: Re-express `ProcessEvent`** — in `engine/appc/characters.py:603-629`, the `ET_CHARACTER_ANIMATION_DONE` branch keeps identical observable behavior but on the new model. Replace the branch body (`if state == self.CS_HIDDEN: ...` through the `elif self.CS_SEATED`) with:

```python
            if state == self.CS_HIDDEN:
                self.SetHidden(1)
            elif state == self.CS_STANDING:
                self.SetHidden(0)
                self.SetStanding()
            elif state == self.CS_SEATED:
                self.SetHidden(0)
                self.ClearFlags(self.CS_STANDING)
            return
```

> This preserves the turbolift-hide (officer hides after walking off) and the
> standing/seated reveals; only `ClearStatus(CS_STANDING)` → `ClearFlags(CS_STANDING)`
> changes, because standing is now a flag, not a status string.

- [ ] **Step 6: Rewrite the coupled tests in `tests/unit/test_characters.py`.** Replace `test_set_status_and_is_state_set` (`:112-118`):

```python
def test_set_flags_and_is_state_set():
    c = CharacterClass_Create()
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
    c.SetFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 1
    c.ClearFlags(CharacterClass.CS_STANDING)
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 0
```

Replace `test_set_status_accepts_string_label` (`:477-483`):

```python
def test_set_status_accepts_string_label():
    """Bridge handlers call SetStatus(db.GetString("Waiting")) — a display string."""
    c = CharacterClass_Create()
    c.SetStatus("Waiting")
    assert c.GetStatusText() == "Waiting"
    c.ClearStatus("Waiting")
    assert c.GetStatusText() is None
```

Replace `test_set_status_int_and_string_independent` (`:486-491`):

```python
def test_status_string_does_not_touch_flags():
    c = CharacterClass_Create()
    c.SetFlags(CharacterClass.CS_STANDING)
    c.SetStatus("Waiting")
    assert c.IsStateSet(CharacterClass.CS_STANDING) == 1
    assert c.GetStatusText() == "Waiting"
```

- [ ] **Step 7: Run the full character suite to verify no regression**

Run: `uv run pytest tests/unit/test_character_state_flags.py tests/unit/test_characters.py -v`
Expected: PASS (including the unchanged `test_set_hidden_*` and `test_set_standing_*`).

- [ ] **Step 8: Run the broader bridge/character tests** (ProcessEvent + state consumers)

Run: `uv run pytest tests/unit/ -k "character or bridge or menu" -q`
Expected: PASS. If a failure names `ProcessEvent`/turbolift/hidden, fix on the new model before proceeding.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_characters.py tests/unit/test_character_state_flags.py
git commit -m "feat(character): SP1 t2 — faithful CS_* bitfield; SetFlags/ClearFlags; status split

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `0x8` busy → `MenuDown` coupling (behavioral test)

Task 2 wired the coupling inside `SetFlags`; this task proves it end-to-end and pins it against regression.

**Files:**
- Test: `tests/unit/test_character_state_flags.py`

**Interfaces:**
- Consumes: `SetFlags` (Task 2), `MenuUp`/`MenuDown`/`IsMenuUp` (existing, `engine/appc/characters.py:731,766,727`).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_character_state_flags.py`:

```python
def test_setflags_busy_bit_drops_open_menu(monkeypatch):
    # CharacterClass.md §4.3: SetFlags, after setting bits, if 0x8 is now set
    # and the menu is up, calls MenuDown(). MoveTo relies on this.
    c = CharacterClass_Create()
    calls = {"down": 0}
    monkeypatch.setattr(c, "IsMenuUp", lambda *a: 1)
    monkeypatch.setattr(c, "MenuDown", lambda *a: calls.__setitem__("down", calls["down"] + 1))
    c.SetFlags(CharacterClass.CS_UI_DISABLED)
    assert calls["down"] == 1


def test_setflags_busy_bit_no_menu_no_drop(monkeypatch):
    c = CharacterClass_Create()
    calls = {"down": 0}
    monkeypatch.setattr(c, "IsMenuUp", lambda *a: 0)
    monkeypatch.setattr(c, "MenuDown", lambda *a: calls.__setitem__("down", calls["down"] + 1))
    c.SetFlags(CharacterClass.CS_UI_DISABLED)
    assert calls["down"] == 0
```

- [ ] **Step 2: Run to verify pass** (Task 2 already implemented the coupling)

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k busy`
Expected: PASS. If FAIL, the coupling in `SetFlags` (Task 2 Step 4) is wrong — fix there.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_character_state_flags.py
git commit -m "test(character): SP1 t3 — pin SetFlags 0x8-busy -> MenuDown coupling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Faithful constructor defaults (safe subset)

Seed the RE'd ctor defaults so a fresh character reports BC's values via the existing getters. Uses the `_data` bag (single source of truth for the existing `Get*` accessors), **not** parallel attributes. `IsActive`/`SetActive` is deliberately **excluded** (deferred to SP2 with the anim-clear behavior).

**Files:**
- Modify: `engine/appc/characters.py` `__init__` (after `:439`, `self._data: dict = {}`)
- Test: `tests/unit/test_character_state_flags.py`

**Interfaces:**
- Consumes: `CharacterClass` gender/size/audio/blink constants (existing).
- Produces: `_data` seeded with `Gender`, `Size`, `AudioMode`, `BlinkStages`, `RandomAnimationEnabled` defaults; `GetGender()`/`GetSize()`/`GetAudioMode()`/`UsesAnimatedSpeaking` etc. return them on a fresh character.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_character_state_flags.py`:

```python
def test_constructor_defaults_match_re():
    # CharacterClass.md §4.1 ctor + stbc_constants.csv field names (tier 1).
    c = CharacterClass_Create()
    assert c.GetGender() == CharacterClass.FEMALE          # +0x7C ctor = 1
    assert c.GetSize() == CharacterClass.SMALL             # +0x78 ctor = 0
    assert c.GetAudioMode() == CharacterClass.CAM_VOCAL    # +0x84 ctor = 2
    assert c.GetBlinkChance() == 0.1                       # +0xB8 ctor = 0.1f
    assert c.IsRandomAnimationEnabled() == 1               # +0x13C ctor = 1


def test_flags_start_clear():
    c = CharacterClass_Create()
    assert c._flags == 0
    assert c.IsHidden() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k "constructor_defaults or flags_start"`
Expected: FAIL (`GetGender()`/`GetSize()`/`GetAudioMode()` return `None` via the data-bag; no defaults seeded).

- [ ] **Step 3: Seed defaults in `__init__`** — immediately after `self._data: dict = {}` (`engine/appc/characters.py:439`), add:

```python
        # RE'd constructor defaults (CharacterClass.md §4.1; field names from
        # stbc_constants.csv). Seeded into the data-bag so the existing Get*
        # accessors report BC's defaults on a fresh character. NOTE: Active is
        # intentionally NOT seeded here — SetActive/IsActive faithfulness
        # (arg-honoring + clear-interruptable-anims + inactive default) is
        # coupled to SP2's animation queue and lands there.
        self._data.setdefault("Gender", self.FEMALE)
        self._data.setdefault("Size", self.SMALL)
        self._data.setdefault("AudioMode", self.CAM_VOCAL)
        self._data.setdefault("BlinkStages", -1)
        self._data.setdefault("RandomAnimationEnabled", True)
```

> `GetBlinkChance` already defaults to `0.1` (`engine/appc/characters.py:700-701`);
> `IsRandomAnimationEnabled` already reads `RandomAnimationEnabled` defaulting True
> (`:720-721`) — the seed makes it explicit and survives a later default change.

- [ ] **Step 4: Run to verify pass, and confirm the data-bag round-trip still works**

Run: `uv run pytest tests/unit/test_character_state_flags.py tests/unit/test_characters.py::test_unknown_setter_round_trips_via_data_bag -v -k "constructor_defaults or flags_start or round_trips"`
Expected: PASS (seeding via `setdefault` leaves explicit `SetGender(...)` round-trips intact).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_state_flags.py
git commit -m "feat(character): SP1 t4 — seed RE'd constructor defaults (Active deferred to SP2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Owner skeleton — named sub-component slots

Add the named slots the later sub-projects plug into, so SP2–SP4 attach without re-shaping the class. Pure additive scaffolding.

**Files:**
- Modify: `engine/appc/characters.py` `__init__` (near `:437`, the `_current_anim` line)
- Test: `tests/unit/test_character_state_flags.py`

**Interfaces:**
- Produces: `self._anim_queue`, `self._speak_queue`, `self._position_zoom`, `self._menu_state` slots (all `None` in SP1). `_current_anim` and `_phonemes` remain the interim state used until SP2/SP3.

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_character_state_flags.py`:

```python
def test_owner_has_named_subcomponent_slots():
    # SP1 backbone: the owner exposes named slots the later SPs fill
    # (SP2 anim queue, SP3 speak queue/phonemes, SP4 zoom/menu-state).
    c = CharacterClass_Create()
    for slot in ("_anim_queue", "_speak_queue", "_position_zoom", "_menu_state"):
        assert slot in c.__dict__, slot
        assert c.__dict__[slot] is None
```

> Use `c.__dict__` (not `getattr`) — `CharacterClass.__getattr__` would otherwise
> synthesize a value for a missing underscore-name. (Underscore names already
> raise `AttributeError` via `__getattr__`, but `__dict__` is the unambiguous check.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k subcomponent`
Expected: FAIL (slots absent from `__dict__`).

- [ ] **Step 3: Add the slots in `__init__`** — after the `self._current_anim: tuple | None = None` line (`engine/appc/characters.py:437`), add:

```python
        # ── Owner sub-component slots (filled by later sub-projects) ────────
        # SP1 leaves them None; the interim _current_anim/_phonemes above stay
        # the working state until SP2/SP3 replace them.
        self._anim_queue = None       # SP2: CAT_* AnimationQueue
        self._speak_queue = None      # SP3: SpeakQueue (wraps crew_speech)
        self._position_zoom = None    # SP4: PositionZoomTable
        self._menu_state = None       # SP4: MenuState (formalizes _menu)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k subcomponent`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_state_flags.py
git commit -m "feat(character): SP1 t5 — named owner sub-component slots for SP2-SP4

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Lifecycle statics — coverage audit

The statics (`Create`/`CreateNull`/`Cast`/`GetObject`/`GetObjectStrict`) already work; SP1 §5.6 asks only to confirm and cover the semantics that lack tests (the `CreateNull` null-marker and `GetObjectStrict` strictness). No production change unless a test fails.

**Files:**
- Test: `tests/unit/test_character_state_flags.py`
- (Modify `engine/appc/characters.py` only if a test reveals a real gap.)

**Interfaces:**
- Consumes: `CharacterClass_Create`, `CharacterClass_CreateNull`, `CharacterClass_Cast`, `CharacterClass_GetObjectStrict` (existing, `engine/appc/characters.py:839-989`).

- [ ] **Step 1: Write the tests** — append to `tests/unit/test_character_state_flags.py`:

```python
from engine.appc.characters import (
    CharacterClass_CreateNull, CharacterClass_Cast, CharacterClass_GetObjectStrict,
)
from engine.appc.objects import ObjectClass


def test_create_null_is_marked_null():
    n = CharacterClass_CreateNull()
    assert n._is_null is True


def test_cast_rejects_non_character():
    assert CharacterClass_Cast(ObjectClass()) is None
    c = CharacterClass_Create()
    assert CharacterClass_Cast(c) is c


def test_get_object_strict_returns_none_without_a_character():
    # Strict lookup does NOT auto-vivify (unlike CharacterClass_GetObject).
    assert CharacterClass_GetObjectStrict(None, "Nobody") is None
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/unit/test_character_state_flags.py -v -k "create_null or cast_rejects or get_object_strict"`
Expected: PASS (these behaviors already exist). If any FAIL, that is a real SP1 gap — fix the static in `engine/appc/characters.py`, keeping the docstring contract.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_character_state_flags.py
git commit -m "test(character): SP1 t6 — cover lifecycle static semantics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full gate + equivalence sweep

Prove no regression across both suites before declaring SP1 done.

**Files:** none (verification only).

- [ ] **Step 1: Run the authoritative gate**

Run: `scripts/check_tests.sh`
Expected: exits 0, or names only the 7 baselined headless-GL `FrameTest`s from `tests/known_failures.txt`. Any other named failure is an SP1 regression — fix it (most likely a `self._states` consumer this plan missed; grep `engine/` and `tests/` for `_states` and reconcile).

- [ ] **Step 2: Confirm no stray `_states` references remain**

Run: `grep -rn "_states" engine/appc/characters.py`
Expected: no matches (the attribute is gone; all consumers moved to `_flags`/`_hidden`/`_status`).

- [ ] **Step 3: Final commit only if Step 1 required a fix** (otherwise nothing to commit)

```bash
git add engine/appc/characters.py
git commit -m "fix(character): SP1 t7 — reconcile remaining state consumer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §5.1 constants → Task 1. ✅
- §5.2 bitfield + `SetFlags`/`ClearFlags`/`IsStateSet` + derived predicates + pull-model visibility → Task 2 (+ Task 3 for the `0x8`→`MenuDown` pin). ✅
- §5.3 status disentanglement + `ProcessEvent` preservation → Task 2 (Steps 4–6). ✅
- §5.4 owner sub-component slots → Task 5. ✅
- §5.5 constructor faithfulness → Task 4 (with `IsActive` deliberately deferred to SP2, per the plan's risk note; spec §5.5 flagged the flip as needing verification — deferral honors that). ✅
- §5.6 lifecycle statics → Task 6. ✅
- §6 verification → Task 7 (gate) + per-task focused runs. ✅
- Out of scope (`MorphBody`/`GetHeadHeight`, literal layout) → untouched. ✅

**Placeholder scan:** No TBD/TODO. Task 4 Step 1 contains a self-correcting first draft (`GetFlags_forTest`) explicitly replaced by the following corrected block — the corrected block is the one to use; the implementer keeps only `assert c._flags == 0`.

**Type consistency:** `_flags: int`, `_hidden: bool`, `_status: dict` are introduced in Task 2 Step 3 and used consistently thereafter (Tasks 3–7). `SetFlags`/`ClearFlags`/`IsStateSet`/`SetInitiative`/`IsInitiativeOn`/`GetStatusText` signatures match between definition (Task 2) and use (Tasks 3–6). Constants from Task 1 are referenced by value name (`CS_*`/`CPT_*`) everywhere.

**Deviations from spec (intentional, noted inline):**
1. `IsActive` default flip deferred to SP2 (risk + coupling to `SetActive` anim-clear).
2. Ctor defaults seeded into `_data` via `setdefault` rather than parallel attributes (single source of truth for existing `Get*`).
