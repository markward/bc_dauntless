# Bridge Crew Population Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the five bridge officers (Felix/Kiska/Saffi/Miguel/Brex) with real names + localization databases so crew speech resolves real voice/subtitle instead of the `"Aye, Captain."` fallback.

**Architecture:** Fix `CharacterClass.SetDatabase` to load a TGL path into a real DB object, then add a guarded crew-population step to our `LoadBridge.Load` shim that runs each officer's SDK `CreateCharacter` (which sets name + database) plus the bridge module's `ConfigureCharacters` — mirroring the SDK create→configure order so it extends into the full SDK bridge `Load` later. Per-officer try/except keeps one failure from aborting the rest.

**Tech Stack:** Python 3 (engine shims under `engine/`, root `LoadBridge.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-bridge-crew-population-design.md`

**Project constraints (read before running anything):**
- **NEVER run the full pytest suite** — it OOMs the machine (>100 GB RAM). Run only the focused files named in each task via `.venv/bin/python -m pytest <files>`.
- No synthetic desktop input. The live-build audio verification (after Task 3) is user-driven.

**Branch:** `feat/bridge-crew-population` (already created, stacked on `feat/crew-menu-ack-speech`).

---

### Task 1: `CharacterClass.SetDatabase` loads a TGL path string

The SDK calls `SetDatabase("data/TGL/Bridge Crew General.tgl")` (a path), but `acknowledge`/`emit` need a DB object with `HasString`/`GetFilename`. Make `SetDatabase` load a string path into a real DB; pass through non-strings unchanged.

**Files:**
- Modify: `engine/appc/characters.py` (the `SetDatabase` method, currently `def SetDatabase(self, db) -> None: self._database = db`)
- Test: `tests/unit/test_characters.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_characters.py`:

```python
def test_setdatabase_loads_path_string_into_db_object():
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase
    c = CharacterClass()
    c.SetDatabase("data/TGL/Bridge Menus.tgl")   # path string -> loaded DB
    db = c.GetDatabase()
    assert isinstance(db, TGLocalizationDatabase)
    # HasString is callable on the resolved DB (real method, not a stub).
    assert db.HasString("definitely-not-a-key") in (True, False)


def test_setdatabase_passes_through_db_object():
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase
    c = CharacterClass()
    real = TGLocalizationDatabase("x.tgl", strings={"k": "v"})
    c.SetDatabase(real)                            # object -> stored as-is
    assert c.GetDatabase() is real


def test_setdatabase_none_stays_none():
    from engine.appc.characters import CharacterClass
    c = CharacterClass()
    c.SetDatabase(None)
    assert c.GetDatabase() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_characters.py -k setdatabase -v`
Expected: FAIL — `test_setdatabase_loads_path_string_into_db_object` fails (a raw string `"data/TGL/..."` is stored, not a `TGLocalizationDatabase`).

- [ ] **Step 3: Implement the load in `engine/appc/characters.py`**

Replace `def SetDatabase(self, db) -> None:            self._database = db` with:

```python
    def SetDatabase(self, db) -> None:
        # SDK passes a TGL path string (e.g. "data/TGL/Bridge Crew General.tgl");
        # load it into a real localization DB so GetDatabase() callers
        # (acknowledge/emit) get HasString/GetFilename. A DB object (or any
        # non-string) is stored as-is. Best-effort: a load failure stores None.
        if isinstance(db, str):
            try:
                import App
                self._database = App.g_kLocalizationManager.Load(db)
            except Exception:
                self._database = None
        else:
            self._database = db
```

- [ ] **Step 4: Run tests to verify pass (new + existing character tests)**

Run: `.venv/bin/python -m pytest tests/unit/test_characters.py -v`
Expected: PASS (the existing tests that call `SetDatabase(TGLocalizationDatabase(...))` still pass — object pass-through is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_characters.py
git commit -m "feat(crew): CharacterClass.SetDatabase loads a TGL path string"
```

---

### Task 2: Crew-population step in `LoadBridge.Load` + reset wiring

Add a guarded `populate_bridge_crew` that runs each officer's SDK `CreateCharacter` (sets name + database) and then the bridge module's `ConfigureCharacters`. Call it from `Load`, gated on a live game, idempotent per bridge load, reset on mission swap.

**Files:**
- Modify: `LoadBridge.py` (add `populate_bridge_crew` + `_crew_populated` flag + `_reset_crew_populated`; call from `Load`)
- Modify: `engine/host_loop.py` (`reset_sdk_globals` — reset the crew flag alongside the menu flag)
- Test: `tests/unit/test_bridge_crew_population.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_crew_population.py`:

```python
"""LoadBridge.populate_bridge_crew creates the 5 GalaxyBridge officers with
real names + loaded localization DBs. Calls the helper directly (no game-state
guard) for determinism."""
import App
import LoadBridge
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase


def _fresh_bridge_set():
    # Mirror LoadBridge.Load's set creation enough for CreateCharacter:
    # a "bridge" set with the ambientlight1 the SDK CreateCharacter illuminates.
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    pSet.CreateAmbientLight(1.0, 1.0, 1.0, 1.0, "ambientlight1")
    return pSet


def test_populate_creates_five_named_officers_with_databases():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()

    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    expected = {
        "Tactical": "Felix", "Helm": "Kiska", "XO": "Saffi",
        "Science": "Miguel", "Engineer": "Brex",
    }
    for set_name, char_name in expected.items():
        obj = pSet.GetObject(set_name)
        assert isinstance(obj, CharacterClass), f"{set_name} not a CharacterClass"
        assert obj.GetCharacterName() == char_name
        # SetDatabase("...tgl") (Task 1) must have left a real DB object.
        assert isinstance(obj.GetDatabase(), TGLocalizationDatabase), \
            f"{char_name} has no loaded database"


def test_populate_is_idempotent():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")
    first = pSet.GetObject("Tactical")
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")   # second call
    assert pSet.GetObject("Tactical") is first              # same object, not recreated


def test_populate_unknown_bridge_is_noop():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "NoSuchBridge")   # must not raise
    assert pSet.GetObject("Tactical") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_bridge_crew_population.py -v`
Expected: FAIL — `AttributeError: module 'LoadBridge' has no attribute 'populate_bridge_crew'`.

- [ ] **Step 3: Add `populate_bridge_crew` + flag to `LoadBridge.py`**

Add near the top of `LoadBridge.py`, after the `_menus_created` definition:

```python
_crew_populated = False

# Per-bridge officer roster: (character module, set-object name). Mirrors the
# bridge config module's ConfigureCharacters mapping. Only GalaxyBridge for now;
# other bridges (and the full SDK bridge Load) extend this table.
_BRIDGE_CREW = {
    "GalaxyBridge": [
        ("Bridge.Characters.Felix",  "Tactical"),
        ("Bridge.Characters.Kiska",  "Helm"),
        ("Bridge.Characters.Saffi",  "XO"),
        ("Bridge.Characters.Miguel", "Science"),
        ("Bridge.Characters.Brex",   "Engineer"),
    ],
}


def _reset_crew_populated():
    """Mission-swap hook (reset_sdk_globals) and test reset."""
    global _crew_populated
    _crew_populated = False


def populate_bridge_crew(pBridgeSet, bridge_name):
    """Create + configure the bridge officers for `bridge_name`, mirroring the
    SDK create->configure order. Each officer's CreateCharacter sets its name
    and SetDatabase(...tgl); the bridge module's ConfigureCharacters layers on
    (animation) config. Per-officer and per-stage try/except so one failure
    can't abort the rest or block mission load. Idempotent via CreateCharacter's
    own existing-object guard + the _crew_populated latch."""
    global _crew_populated
    if _crew_populated:
        return
    roster = _BRIDGE_CREW.get(bridge_name)
    if roster is None:
        _logger.info("populate_bridge_crew: no roster for %s", bridge_name)
        return
    _crew_populated = True
    import importlib
    for mod_name, _set_name in roster:
        try:
            importlib.import_module(mod_name).CreateCharacter(pBridgeSet)
        except Exception:
            _logger.exception("CreateCharacter failed for %s", mod_name)
    # Bridge-specific configuration (animations etc.). Speech-critical data
    # (name + database) is already set by CreateCharacter; this is the faithful
    # extra and the seam the full SDK bridge Load will reuse.
    try:
        importlib.import_module("Bridge." + bridge_name).ConfigureCharacters(pBridgeSet)
    except Exception:
        _logger.exception("ConfigureCharacters failed for %s", bridge_name)
```

If `test_populate_creates_five_named_officers_with_databases` fails because an
officer's `CreateCharacter` raises **before** reaching `SetDatabase` (e.g. an
unshimmed Appc call), the per-officer guard will swallow it and that officer's
DB assertion fails. In that case: identify the raising call from the logged
traceback and add a minimal no-op stub for it (this is the spec's dependency
audit), then re-run. `App.g_kModelManager.LoadModel(...)` already resolves to a
no-op `_NamedStub`, so it is not expected to raise.

- [ ] **Step 4: Call it from `Load`**

In `LoadBridge.Load`, the function currently ends each branch with `CreateCharacterMenus()`. Populate the crew immediately before menus are created. In the `if existing:` branch and the new-set branch, change the `CreateCharacterMenus()` call site to:

In the `if existing:` branch:
```python
    if existing:
        populate_bridge_crew(existing, LAST_REQUESTED)
        CreateCharacterMenus()
        return existing
```

At the end of the new-set branch (after `CreateAmbientLight(...)` / before the final `CreateCharacterMenus()`):
```python
    populate_bridge_crew(pSet, LAST_REQUESTED)
    CreateCharacterMenus()
    return pSet
```

- [ ] **Step 5: Reset the flag on mission swap**

In `engine/host_loop.py`, find the `reset_sdk_globals` block that calls `_LB_reset._reset_menus_created()` (around line 1372):

```python
    try:
        import LoadBridge as _LB_reset
        _LB_reset._reset_menus_created()
    except Exception:
        pass
```

Add the crew-flag reset in the same block:

```python
    try:
        import LoadBridge as _LB_reset
        _LB_reset._reset_menus_created()
        _LB_reset._reset_crew_populated()
    except Exception:
        pass
```

- [ ] **Step 6: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/unit/test_bridge_crew_population.py -v`
Expected: PASS (3 tests). If an officer DB assertion fails, apply the dependency-audit stub described in Step 3 and re-run.

- [ ] **Step 7: Commit**

```bash
git add LoadBridge.py engine/host_loop.py tests/unit/test_bridge_crew_population.py
git commit -m "feat(crew): populate bridge officers in LoadBridge.Load (guarded)"
```

---

### Task 3: Integration — populated crew drives a real acknowledgement

Prove the end-to-end speech chain against a populated officer: `resolve_character` returns the real Felix, and `acknowledge` resolves a real `"FelixSir<N>"` line (deterministically, via a constructed DB on the populated officer) → subtitle with speaker `"Felix"`.

**Files:**
- Test: `tests/integration/test_bridge_crew_population.py` (create)

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_bridge_crew_population.py`:

```python
"""End-to-end: populated crew -> resolve_character -> acknowledge resolves a
real per-officer line (not the 'Aye, Captain.' fallback)."""
import App
import LoadBridge
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase
from engine.ui import crew_menu_hotkeys


def _fresh_bridge_set():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    pSet.CreateAmbientLight(1.0, 1.0, 1.0, 1.0, "ambientlight1")
    return pSet


def test_resolve_character_returns_populated_officer():
    LoadBridge._reset_crew_populated()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    char = crew_menu_hotkeys.resolve_character("Tactical")
    assert isinstance(char, CharacterClass)
    assert char.GetCharacterName() == "Felix"


def test_acknowledge_resolves_real_line_for_populated_officer(monkeypatch):
    # Distinct line text (not the "Aye, Captain." fallback) so the assertion
    # can only pass if the line was resolved from the populated officer's DB.
    LoadBridge._reset_crew_populated()
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    pSet = _fresh_bridge_set()
    LoadBridge.populate_bridge_crew(pSet, "GalaxyBridge")

    felix = crew_menu_hotkeys.resolve_character("Tactical")
    # Pin the ack line deterministically (rand -> "FelixSir1") and give Felix a
    # DB that has it, so the test does not depend on the game/ TGL being present.
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)
    felix.SetDatabase(TGLocalizationDatabase("crew.tgl", strings={"FelixSir1": "Phasers ready, sir."}))

    crew_speech.acknowledge(felix)

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap["speaker"] == "Felix"
    assert snap["speech"] == "Phasers ready, sir."   # real DB line, not the fallback
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/integration/test_bridge_crew_population.py -v`
Expected: 2 PASS. If `resolve_character` returns a character whose name is not "Felix", population didn't run — check Task 2.

- [ ] **Step 3: Run the full focused subset to confirm no regressions**

Run:
```bash
.venv/bin/python -m pytest \
  tests/unit/test_characters.py \
  tests/unit/test_bridge_crew_population.py \
  tests/unit/test_crew_ack.py \
  tests/unit/test_crew_menu_hotkeys.py \
  tests/unit/test_crew_menu_panel.py \
  tests/integration/test_bridge_crew_population.py \
  tests/integration/test_crew_menu_ack.py -v
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bridge_crew_population.py
git commit -m "test(crew): integration -- populated officer drives real acknowledgement"
```

---

### Milestone: live-build audio verification (user-driven — NOT a code task)

After Task 3 lands, **do not assume audio works** — the downstream path (Voice category gain, wav file resolution/decode) is unverified and untestable headless. The user rebuilds and runs the live game, opens the Tactical station menu (F2), and reports whether the officer's voice plays.

- **Audio plays:** the slice is complete end-to-end — proceed to finish the branch.
- **Subtitle shows the officer's real line but no audio:** the data layer works; the break is isolated to the audio backend (Voice category / file load / decode) — a separate debugging slice, not a rework of this one.
- **Still `"Aye, Captain."` fallback / wrong speaker:** the populated DB lacks the `"<Name>Sir<N>"` keys or the real game TGL didn't resolve — investigate the TGL path / contents before the audio layer.

(If you want a finer signal, add temporary `_logger.info` lines in `crew_speech.acknowledge` and `_play_voice` logging the resolved `line`/`wav`/`LoadSound` result, run once, then remove.)

---

## Self-Review notes

- **Spec coverage:** §1 population hook → Task 2; §2 `SetDatabase` loads TGL → Task 1; §3 dependency audit → folded into Task 2 Step 3 (the DB assertion forces it); §4 resolve/ack on real data → Task 3; verification-first → the explicit Milestone; reset wiring → Task 2 Step 5. All covered.
- **Type/name consistency:** `LoadBridge.populate_bridge_crew(pBridgeSet, bridge_name)`, `LoadBridge._reset_crew_populated()`, `_crew_populated`, `_BRIDGE_CREW` — used identically across Tasks 2–3 and host_loop. `SetDatabase`/`GetDatabase` object-vs-string behaviour consistent between Tasks 1 and 3.
- **Determinism:** Task 3 avoids depending on `game/`'s TGL by setting a constructed DB on the populated officer and pinning `_rand5`; the distinct-string test proves real DB resolution rather than the fallback.
- **YAGNI:** only `GalaxyBridge` is in `_BRIDGE_CREW`; other bridges + the full `CreateBridgeModel`/`PreloadAnimations` are the deferred option-3 build-up.
