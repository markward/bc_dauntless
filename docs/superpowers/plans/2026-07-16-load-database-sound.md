# LoadDatabaseSound* Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register TGL-database-keyed sounds so BC's per-line voice loader, shield-status callouts, and per-character order-confirmation preloads produce audible sound (and, for the lazy loader, subtitles) instead of silently bailing.

**Architecture:** A single core method on `TGSoundManager` resolves a TGL key to a wav filename via the database's existing `GetFilename`, then routes to the existing `LoadSoundInGroup`. Thin SDK-facing delegates on `Game`/`Mission`/`Episode`, a module-level `App.TGSound_Create`, and `TGSound.GetGroup`/`SetGroup` complete the SDK surface the shipped scripts touch. No native/C++ change.

**Tech Stack:** Python 3, pytest. Engine modules: `engine/audio/tg_sound.py`, `engine/core/game.py`, `engine/appc/localization.py` (read-only), root `App.py` shim.

## Global Constraints

- **SDK interface is the contract.** Be faithful to the *SDK Python surface*, not the RE'd binary internals (no hashing, NiNode, sound counters, 360/700 distances).
- **Faithful bail semantics:** a missing/blank TGL key registers **nothing** and returns `None`. The SDK's `if not GetSound(name): ... if not GetSound(name): return 0` gate depends on this — for `MissionLib.py:681` a bail correctly suppresses *both* voice and subtitle, matching BC.
- **Working in the worktree** at `.worktrees/load-database-sound` on branch `feat/load-database-sound`. Commits ARE allowed here (isolated branch); stage with explicit pathspecs only, never `git add -A`. Never run destructive git.
- **Test runner:** prefix pytest with `unset VIRTUAL_ENV;` and use `uv run pytest ...` (the worktree's own `.venv`; a stale `VIRTUAL_ENV` env var points at the main tree).
- **Test gate before merge:** `scripts/check_tests.sh` (pytest + ctest), not `run_tests.sh`.
- **Tests must be hermetic:** the conftest singleton persists `_sounds`/`_groups` across tests and is NOT auto-cleared. Tests below construct a fresh `TGSoundManager()` (not `.instance()`) where possible; the two cases that must exercise the singleton (`SetGroup`, which resolves `TGSoundManager.instance()`) use unique `LDBS_*` names to avoid cross-test leakage.

---

### Task 1: Core — `TGSoundManager.LoadDatabaseSoundInGroup` + `TGSound.GetGroup/SetGroup`

**Files:**
- Modify: `engine/audio/tg_sound.py` (add `_group` to `TGSound.__init__`, add `GetGroup`/`SetGroup` methods on `TGSound`, add `LoadDatabaseSoundInGroup` on `TGSoundManager`, stamp `_group` in `LoadSoundInGroup`)
- Test: `tests/unit/test_load_database_sound.py` (new)

**Interfaces:**
- Consumes: `TGLocalizationDatabase.GetFilename(key) -> str` (`engine/appc/localization.py:194`; `""` for missing key); `TGSoundManager.LoadSoundInGroup(path, name, group) -> TGSound` (existing; registers a real-but-unloaded `TGSound` when the wav file can't be read, never `None`); `TGSoundManager.GetSound(name) -> Optional[TGSound]`.
- Produces:
  - `TGSoundManager.LoadDatabaseSoundInGroup(db, name, group, flags=0) -> Optional[TGSound]` — resolves `db.GetFilename(name)`; returns `None` and registers nothing if `name` is falsy, `db` is `None`/has no `GetFilename`, or the resolved filename is not a non-empty `str`; otherwise returns `LoadSoundInGroup(filename, name, group)`. `flags` accepted and ignored.
  - `TGSound.GetGroup() -> str` (`""` when untagged), `TGSound.SetGroup(group) -> None` (moves the sound between the manager's group sets and updates the tag; `""` removes it).
  - `LoadSoundInGroup` now stamps `snd._group = group`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_load_database_sound.py`:

```python
"""TGSoundManager.LoadDatabaseSoundInGroup: TGL key -> wav resolve + register.

Hermetic: tests use a fresh TGSoundManager() (not .instance()) so the
conftest-persisted singleton state never leaks in or out. The one test that
must exercise the singleton (SetGroup resolves TGSoundManager.instance()) uses
a unique LDBS_* name. No audio backend in tests, so a real wav never loads —
LoadSoundInGroup's register-unloaded contract is what we assert against.
"""
from engine.audio.tg_sound import TGSoundManager, TGSound
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    # A real localization DB; `sounds` maps key -> wav filename, exactly what
    # GetFilename returns. Missing keys return "".
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_registers_under_sound_name_and_tags_group():
    mgr = TGSoundManager()
    db = _db({"Shields05": "sound/Test/Shields05.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "Shields05", "Bridge")
    # Registered under the SOUND NAME (the key), not the filename.
    assert mgr.GetSound("Shields05") is snd
    assert mgr.GetSound("sound/Test/Shields05.wav") is None
    # Group tag is set on the sound and in the manager's group set.
    assert snd.GetGroup() == "Bridge"
    assert "Shields05" in mgr._groups.get("Bridge", set())


def test_missing_key_returns_none_and_registers_nothing():
    mgr = TGSoundManager()
    db = _db({})  # key absent -> GetFilename returns ""
    assert mgr.LoadDatabaseSoundInGroup(db, "NoSuchKey", "Bridge") is None
    assert mgr.GetSound("NoSuchKey") is None


def test_none_db_returns_none():
    mgr = TGSoundManager()
    assert mgr.LoadDatabaseSoundInGroup(None, "AnyName", "Bridge") is None
    assert mgr.GetSound("AnyName") is None


def test_blank_name_returns_none():
    mgr = TGSoundManager()
    db = _db({"": "sound/empty.wav"})
    assert mgr.LoadDatabaseSoundInGroup(db, "", "Bridge") is None


def test_flags_arg_accepted_and_ignored():
    mgr = TGSoundManager()
    db = _db({"Line1": "sound/Line1.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "Line1", "LoadedOnDemand", TGSound.LS_STREAMED)
    assert mgr.GetSound("Line1") is snd


def test_setgroup_moves_between_group_sets():
    # SetGroup operates on TGSoundManager.instance(); load into it so the sound
    # and its SetGroup target the same manager. Unique name avoids cross-test
    # leakage in the persisted singleton.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_MoveMe": "sound/LDBS_MoveMe.wav"})
    snd = mgr.LoadDatabaseSoundInGroup(db, "LDBS_MoveMe", "")
    assert snd.GetGroup() == ""
    snd.SetGroup("Maelstrom.M1Basic")
    assert snd.GetGroup() == "Maelstrom.M1Basic"
    assert "LDBS_MoveMe" in mgr._groups.get("Maelstrom.M1Basic", set())
    assert "LDBS_MoveMe" not in mgr._groups.get("", set())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound.py -v`
Expected: FAIL — `AttributeError: 'TGSoundManager' object has no attribute 'LoadDatabaseSoundInGroup'` (and `GetGroup`/`SetGroup` missing on `TGSound`).

- [ ] **Step 3: Add `_group` to `TGSound.__init__`**

In `engine/audio/tg_sound.py`, in `TGSound.__init__` (after `self._region = None` near line 83), add:

```python
        self._group = ""     # group tag (GetGroup/SetGroup); "" == untagged
```

- [ ] **Step 4: Add `GetGroup`/`SetGroup` on `TGSound`**

In `engine/audio/tg_sound.py`, add these methods to `TGSound` (place them near `SetSingleShot`/`IsSingleShot`, around line 152):

```python
    def GetGroup(self) -> str:
        """Group tag for batch stop/unload; "" when untagged (falsy, which is
        what the SDK's `if not pSound.GetGroup():` reassignment gate needs)."""
        return self._group

    def SetGroup(self, group: str) -> None:
        """Move this sound to `group` in the owning manager's group sets and
        retag it. Setting "" just removes it from its current group. Mirrors
        Appc TGSound.SetGroup, used by MissionLib.PreloadMissionLine to file an
        untagged preloaded line under the mission's script group."""
        mgr = TGSoundManager.instance()
        old = self._group
        if old and old in mgr._groups:
            mgr._groups[old].discard(self._name)
        self._group = group or ""
        if self._group:
            mgr._groups.setdefault(self._group, set()).add(self._name)
```

- [ ] **Step 5: Stamp `_group` in `LoadSoundInGroup` and add `LoadDatabaseSoundInGroup`**

In `engine/audio/tg_sound.py`, in `LoadSoundInGroup` (around line 287), after `self._groups.setdefault(group, set()).add(name)` and before `return snd`, add:

```python
        snd._group = group
```

Then add the new method immediately after `LoadSoundInGroup` (before `DeleteAllSoundsInGroup`):

```python
    def LoadDatabaseSoundInGroup(self, db, name, group, flags: int = 0):
        """Resolve a TGL sound key to its wav filename via the database, then
        load+register it in `group`. Mirrors Appc Game.LoadDatabaseSoundInGroup.

        `db.GetFilename(name)` is the SDK-visible key->filename lookup (the same
        op App.TGSound_Create(db.GetFilename(k), k, ...) does by hand). A blank
        name, a db without GetFilename, or a missing key (GetFilename -> "")
        registers NOTHING and returns None — faithful to BC's bail gate, where a
        missing key means no voice AND no subtitle.

        `flags` (e.g. TGSound.LS_STREAMED) is accepted for signature parity and
        ignored: the backend decodes whole files up front, and these call sites
        never pass LS_3D.
        """
        if not name:
            return None
        get_filename = getattr(db, "GetFilename", None)
        if get_filename is None:
            return None
        filename = get_filename(name)
        if not isinstance(filename, str) or not filename:
            return None
        return self.LoadSoundInGroup(filename, name, group)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add engine/audio/tg_sound.py tests/unit/test_load_database_sound.py
git commit -m "feat(audio): TGSoundManager.LoadDatabaseSoundInGroup + TGSound group tag"
```

---

### Task 2: SDK delegates — `Game`/`Mission`/`Episode` + `App.TGSound_Create`

**Files:**
- Modify: `engine/core/game.py` (add `LoadDatabaseSoundInGroup` + `LoadDatabaseSound` on `Game`; add `LoadDatabaseSound` on `Mission` and `Episode`)
- Modify: `engine/audio/tg_sound.py` (add module-level `TGSound_Create`)
- Modify: `App.py` (export `TGSound_Create` from the `engine.audio.tg_sound` import block)
- Test: `tests/unit/test_load_database_sound_delegates.py` (new)

**Interfaces:**
- Consumes: `TGSoundManager.LoadDatabaseSoundInGroup(db, name, group, flags=0)` and `TGSoundManager.LoadSound(path, name, loadspec) -> Optional[TGSound]` (Task 1 / existing); `Mission.GetScript() -> str` (`engine/core/game.py:52`).
- Produces:
  - `Game.LoadDatabaseSoundInGroup(db, name, group, flags=0) -> Optional[TGSound]`
  - `Game.LoadDatabaseSound(db, name, flags=2) -> Optional[TGSound]` (group `""`)
  - `Mission.LoadDatabaseSound(db, name, flags=2) -> Optional[TGSound]` (group = `self.GetScript()`)
  - `Episode.LoadDatabaseSound(db, name, flags=2) -> Optional[TGSound]` (group `""`)
  - `App.TGSound_Create(filename, name, flags=0) -> Optional[TGSound]` (module function → `LoadSound`)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_load_database_sound_delegates.py`:

```python
"""SDK-facing delegates route to TGSoundManager and preserve bail semantics.

Delegates resolve TGSoundManager.instance(); tests use unique LDBS_* names to
stay hermetic against the conftest-persisted singleton.
"""
from engine.audio.tg_sound import TGSoundManager, TGSound, TGSound_Create
from engine.core.game import Game, Mission, Episode
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_game_load_database_sound_in_group_registers():
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_G1": "sound/LDBS_G1.wav"})
    snd = Game().LoadDatabaseSoundInGroup(db, "LDBS_G1", "Picard")
    assert mgr.GetSound("LDBS_G1") is snd
    assert snd.GetGroup() == "Picard"


def test_game_load_database_sound_in_group_missing_key_returns_none():
    db = _db({})
    assert Game().LoadDatabaseSoundInGroup(db, "LDBS_G_missing", "Picard") is None


def test_mission_load_database_sound_uses_script_group():
    mgr = TGSoundManager.instance()
    m = Mission()
    m.SetScript("Maelstrom.M1Basic")
    db = _db({"LDBS_M1": "sound/LDBS_M1.wav"})
    snd = m.LoadDatabaseSound(db, "LDBS_M1")
    assert mgr.GetSound("LDBS_M1") is snd
    assert snd.GetGroup() == "Maelstrom.M1Basic"


def test_episode_load_database_sound_registers():
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_E1": "sound/LDBS_E1.wav"})
    snd = Episode().LoadDatabaseSound(db, "LDBS_E1")
    assert mgr.GetSound("LDBS_E1") is snd


def test_tgsound_create_missing_backend_returns_none():
    # No audio backend in tests -> LoadSound returns None, nothing registered.
    assert TGSound_Create("sound/nope.wav", "LDBS_TSC_missing", 0) is None
    assert TGSoundManager.instance().GetSound("LDBS_TSC_missing") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound_delegates.py -v`
Expected: FAIL — `ImportError: cannot import name 'TGSound_Create'` (and the `Game`/`Mission`/`Episode` methods are `_Stub`/missing).

- [ ] **Step 3: Add `TGSound_Create` module function**

In `engine/audio/tg_sound.py`, after the `g_kSoundManager` singleton line (near line 327), add:

```python
def TGSound_Create(filename, name, flags: int = 0):
    """Module-level Appc App.TGSound_Create: load `filename` and register it
    under `name`. Its one SDK call site (MissionLib.PreloadMissionLine's
    no-script branch) is bail-gated on GetSound, so None-on-failure with
    nothing registered is correct. `flags` accepted for parity, ignored."""
    return TGSoundManager.instance().LoadSound(filename, name, flags)
```

- [ ] **Step 4: Export `TGSound_Create` from `App.py`**

In `App.py`, extend the `engine.audio.tg_sound` import block (lines 174–177) to include `TGSound_Create`:

```python
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, g_kSoundManager, TGSound_Create,
    TGSoundRegion, TGSoundRegion_GetRegion, TGSoundRegion_Create,
)
```

- [ ] **Step 5: Add the `Game` delegates**

In `engine/core/game.py`, in `class Game`, after `LoadSoundInGroup` (ends line 420), add:

```python
    def LoadDatabaseSoundInGroup(self, db, name, group, flags: int = 0):
        # Late import: engine.audio depends on the native extension which may
        # not be ready at game.py import time.
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadDatabaseSoundInGroup(
            db, name, group, flags)

    def LoadDatabaseSound(self, db, name, flags: int = 2):
        # ScriptObject.LoadDatabaseSound: same as the grouped form but the
        # group defaults to the object's own group string. Game has no stored
        # group, so "" (PreloadMissionLine reassigns "" sounds to the mission).
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadDatabaseSoundInGroup(
            db, name, "", flags)
```

- [ ] **Step 6: Add the `Mission` delegate**

In `engine/core/game.py`, in `class Mission`, after `GetPrecreatedShip` (ends line 90), add:

```python
    def LoadDatabaseSound(self, db, name, flags: int = 2):
        # ScriptObject.LoadDatabaseSound on a Mission tags the sound with the
        # mission's script group (MissionLib.PreloadMissionLine relies on
        # GetGroup() being the mission script so a swap unloads it).
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadDatabaseSoundInGroup(
            db, name, self.GetScript(), flags)
```

- [ ] **Step 7: Add the `Episode` delegate**

In `engine/core/game.py`, in `class Episode`, after `GetDatabase` (ends line 130), add:

```python
    def LoadDatabaseSound(self, db, name, flags: int = 2):
        # Episode has no script group of its own; "" is fine (PreloadMissionLine
        # reassigns untagged preloaded sounds to the mission script group).
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadDatabaseSoundInGroup(
            db, name, "", flags)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound_delegates.py -v`
Expected: PASS (5 tests).

- [ ] **Step 9: Commit**

```bash
git add engine/core/game.py engine/audio/tg_sound.py App.py tests/unit/test_load_database_sound_delegates.py
git commit -m "feat(audio): Game/Mission/Episode LoadDatabaseSound delegates + App.TGSound_Create"
```

---

### Task 3: SDK-shape integration test (the MissionLib.py:681 gate end-to-end)

**Files:**
- Test: `tests/unit/test_load_database_sound_sdk_shape.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1–2 via `App` (`Game`, `TGSoundManager`, `TGSoundAction_Create`) — asserts the real shipped call pattern works without touching the SDK tree.
- Produces: nothing (verification only).

- [ ] **Step 1: Write the test**

Create `tests/unit/test_load_database_sound_sdk_shape.py`:

```python
"""Reproduce the exact shipped SDK call patterns against our engine surface,
so a future contract drift on these methods fails a test rather than going
silently mute in-game.
"""
import App
from engine.audio.tg_sound import TGSoundManager, TGSound
from engine.appc.localization import TGLocalizationDatabase


def _db(sounds):
    return TGLocalizationDatabase("data/TGL/Test.tgl", sounds=sounds)


def test_missionlib_lazy_loader_gate_reaches_sound_action():
    # MissionLib.py:665-681 shape: GetSound miss -> LoadDatabaseSoundInGroup ->
    # GetSound now hits -> build a TGSoundAction on the name.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_Lazy": "sound/LDBS_Lazy.wav"})
    pcString = "LDBS_Lazy"

    assert mgr.GetSound(pcString) is None            # first gate: not loaded
    pGame = App.Game()
    pGame.LoadDatabaseSoundInGroup(db, pcString, "LoadedOnDemand", 0)
    assert mgr.GetSound(pcString) is not None         # second gate: now loaded

    pSound = App.TGSoundAction_Create(pcString, 0)
    assert pSound.GetName() == pcString               # sequence build proceeds


def test_preload_post_load_block_retags_untagged_sound():
    # MissionLib.PreloadMissionLine tail: after LoadDatabaseSound, the sound is
    # set single-shot and, if untagged, filed under the mission script group.
    mgr = TGSoundManager.instance()
    db = _db({"LDBS_Preload": "sound/LDBS_Preload.wav"})
    snd = App.Game().LoadDatabaseSound(db, "LDBS_Preload")  # Game -> group ""

    pSound = mgr.GetSound("LDBS_Preload")
    assert pSound is not None
    pSound.SetSingleShot(1)                            # no raise
    if not pSound.GetGroup():                          # exact SDK reassignment
        pSound.SetGroup("Maelstrom.M1Basic")
    assert pSound.GetGroup() == "Maelstrom.M1Basic"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound_sdk_shape.py -v`
Expected: PASS (2 tests). This is a GREEN-only verification task — Tasks 1–2 already implement the surface; this test guards the composed contract. If it fails, the fault is in Task 1/2 code, not the test.

- [ ] **Step 3: Run the full new-test set + a sound-adjacent regression sweep**

Run: `unset VIRTUAL_ENV; uv run pytest tests/unit/test_load_database_sound.py tests/unit/test_load_database_sound_delegates.py tests/unit/test_load_database_sound_sdk_shape.py tests/unit/test_tg_sound_duration.py tests/unit/test_actions.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_load_database_sound_sdk_shape.py
git commit -m "test(audio): SDK-shape gate for LoadDatabaseSound family"
```

---

### Task 4: Full gate + verification boundary

**Files:**
- None (verification + docs pointer only)

- [ ] **Step 1: Run the machine-checked gate**

Run: `scripts/check_tests.sh`
Expected: exits 0, or names only the 7 baselined headless-GL `FrameTest`s from `tests/known_failures.txt`. Any other failure is a regression introduced here — fix it before proceeding. (The worktree cloned `build/` from the main tree; if ctest complains about a stale/missing target, that is an environment issue, not a code regression — re-run pytest-only via `unset VIRTUAL_ENV; uv run pytest -q` and note the ctest gap for the merge step.)

- [ ] **Step 2: Record the verification boundary**

The heatmap entry (`Game | LoadDatabaseSoundInGroup | 6440 hits`) is expected to drop off the unimplemented table on the **next live `--developer` run** — that's telemetry-observed, not something these tests prove. The **audible** confirmation (bridge-officer voice lines + shield-status callouts + per-character order confirmations actually sounding, and the lazy loader's subtitles appearing) is **Mark's live check**. Do not claim the feature "works" before he has heard it — green tests cannot see asset paths or backend playback.

---

## Self-Review

**Spec coverage:**
- Core `LoadDatabaseSoundInGroup` with bail-on-missing-key → Task 1. ✓
- `flags` accepted/ignored → Task 1 Step 5 + test. ✓
- `Game.LoadDatabaseSoundInGroup` delegate → Task 2. ✓
- `LoadDatabaseSound` on `Game`/`Mission`/`Episode` (group = script where available) → Task 2. ✓
- `App.TGSound_Create` → Task 2. ✓
- `TGSound.GetGroup`/`SetGroup` + `LoadSoundInGroup` stamps `_group` → Task 1. ✓
- SDK-shape gate (MissionLib.py:681 + PreloadMissionLine tail) → Task 3. ✓
- Out-of-scope preload-walk gap → left untouched, noted in Task 4. ✓
- Suite gate → Task 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code.

**Type consistency:** `LoadDatabaseSoundInGroup(db, name, group, flags=0)` and `LoadDatabaseSound(db, name, flags=2)` used identically across Tasks 1–3; `GetGroup()`/`SetGroup()` names consistent; `TGSound_Create(filename, name, flags=0)` consistent. Delegates all resolve the manager via `TGSoundManager.instance()`, matching the existing `LoadSound`/`LoadSoundInGroup` neighbours and the singleton `SetGroup` uses.

**Hermeticity:** the persisted singleton is not auto-cleared between tests; new tests use a fresh `TGSoundManager()` or unique `LDBS_*` names.
