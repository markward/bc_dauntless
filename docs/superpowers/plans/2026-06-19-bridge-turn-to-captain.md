# Bridge Turn-to-Captain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selecting a bridge officer's station turns them to face the captain (breathing-turned, idle gestures suppressed); deselecting turns them back to normal breathing — driven through the SDK `MenuUp()`/`MenuDown()` seam.

**Architecture:** The CEF crew menu calls the resolved officer's `MenuUp()`/`MenuDown()`. Those set the `IsMenuUp()` flag and queue a turn request on `BridgeCharacterAnimController`; the controller's per-tick pump (which has the renderer) captures the SDK `<location>TurnCaptain`/`BackCaptain`/`BreatheTurned` clips, swaps the default idle via `set_idle`, and submits the turn as a transient. The `IdleGestureScheduler` skips menu-up officers. Reuses the layered sampler, `set_idle`, transient queue, and capture-by-key pattern from breathing.

**Tech Stack:** Python (`engine/`, pytest). No native changes (the E-bridge root-translation fallback is deferred until GUI shows it's needed).

## Global Constraints

- SDK-driven: trigger is the `CharacterClass.MenuUp()`/`MenuDown()` seam (not a bespoke CEF hook); clip choices come entirely from the registered `<location>TurnCaptain`/`BackCaptain`/`BreatheTurned` animations.
- `MenuUp`/`MenuDown` are headless (no renderer): they only set the flag + queue a controller request via the `engine.bridge_character_anim.get_controller()` registry. Renderer work happens in the controller pump.
- Best-effort: a missing clip / absent controller degrades gracefully (no crash, no freeze). Headless tests run without a controller or renderer.
- Reuse `capture_breathing`'s resolution shape — generalize it, do not duplicate.
- Python tests: `uv run pytest <path> -v`. TDD: failing test first.
- Do NOT launch the GUI (the user verifies the visual).

---

### Task 1: Generalize capture into `capture_registered_clip`

**Files:**
- Modify: `engine/appc/bridge_placement.py` (add `capture_registered_clip`; refactor `capture_breathing` to call it)
- Test: `tests/unit/test_bridge_registered_clip.py` (new)

**Interfaces:**
- Produces: `capture_registered_clip(character, suffix) -> {"clip_nif": str} | None` — resolves the `_animations` entry keyed `str(location)+suffix` → SDK builder → last action's clip name → `path_for`.
- `capture_breathing(character)` becomes `capture_registered_clip(character, "Breathe")` (unchanged public behavior).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_registered_clip.py`:

```python
import App
from engine.appc.bridge_placement import capture_registered_clip, capture_breathing


def _char(location, *anim_entries):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    for e in anim_entries:
        c.AddAnimation(*e)
    return c


def test_resolves_turn_captain_suffix():
    c = _char("DBEngineer",
              ("DBEngineerTurnCaptain", "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain"))
    assert capture_registered_clip(c, "TurnCaptain") == {"clip_nif": "data/animations/db_face_capt_e.nif"}


def test_resolves_breathe_turned_suffix():
    c = _char("DBEngineer",
              ("DBEngineerBreatheTurned", "Bridge.Characters.CommonAnimations.BreathingTurned"))
    assert capture_registered_clip(c, "BreatheTurned") == {"clip_nif": "data/animations/breathing.NIF"}


def test_unregistered_suffix_returns_none():
    c = _char("DBEngineer")
    assert capture_registered_clip(c, "TurnCaptain") is None


def test_no_location_returns_none():
    c = _char(None, ("DBEngineerTurnCaptain", "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain"))
    assert capture_registered_clip(c, "TurnCaptain") is None


def test_capture_breathing_still_works():
    c = _char("DBEngineer",
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    assert capture_breathing(c) == {"clip_nif": "data/animations/standing_console.NIF"}
```

(If `path_for` returns different exact strings for `db_face_capt_e`/`breathing`, run once and pin the actual values — the resolution logic is what's under test.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_registered_clip.py -v`
Expected: FAIL — `capture_registered_clip` not defined.

- [ ] **Step 3: Refactor `capture_breathing` → `capture_registered_clip`**

In `engine/appc/bridge_placement.py`, replace the `capture_breathing` function with the generalized helper plus a thin wrapper:

```python
def capture_registered_clip(character, suffix):
    """Resolve the officer's SDK-registered "<location>"+suffix animation to its
    clip NIF, or None. The registered entry's module path is called as the SDK
    builder; the last action's clip name resolves to a NIF via path_for. Used
    for the layered idle/turn clips (suffix "Breathe", "BreatheTurned",
    "TurnCaptain", "BackCaptain"). Returns {"clip_nif": <data-root-relative
    path>} or None (no location / no <location>+suffix registration /
    unresolvable).
    """
    import importlib
    import App

    location = character.GetLocation()
    if not location:
        return None
    key = str(location) + suffix
    module_path = None
    for entry in getattr(character, "_animations", []):
        if entry and len(entry) >= 2 and str(entry[0]) == key:
            module_path = entry[1]
            break
    if not module_path:
        return None

    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return None
    if seq is None or seq.GetNumActions() == 0:
        return None
    action = seq.GetAction(seq.GetNumActions() - 1)
    clip_name = getattr(action, "_clip", "") or getattr(action, "name", "")
    if not clip_name:
        return None

    clip_nif = App.g_kAnimationManager.path_for(clip_name)
    if not clip_nif:
        _logger.warning("capture_registered_clip: no path for %r (key %r)", clip_name, key)
        return None
    return {"clip_nif": clip_nif}


def capture_breathing(character):
    """The officer's looping breathe idle clip (SDK "<location>Breathe"), or None."""
    return capture_registered_clip(character, "Breathe")
```

- [ ] **Step 4: Run to verify pass (pin paths if needed)**

Run: `uv run pytest tests/unit/test_bridge_registered_clip.py tests/unit/test_bridge_breathing_capture.py -v`
Expected: PASS (new tests + the existing breathing-capture tests, which still call `capture_breathing`). If a path assertion mismatches, pin the real `path_for` value and re-run.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_bridge_registered_clip.py
git commit -m "refactor(bridge): generalize capture into capture_registered_clip"
```

---

### Task 2: Controller turn requests + asset resolver

**Files:**
- Modify: `engine/bridge_character_anim.py` (`request_turn`/`request_turn_back`, pending queue, `_process_turn`, `asset_resolver`)
- Test: `tests/unit/test_bridge_character_anim.py` (turn-request behavior)

**Interfaces:**
- Produces: `BridgeCharacterAnimController(asset_resolver=None)`; `request_turn(character)`; `request_turn_back(character)`. The pending queue is drained in `update(...)`: open → `set_idle(BreatheTurned idx)` + `submit(TurnCaptain, priority=_TURN)`; back → `set_idle(Breathe idx)` + `submit(BackCaptain, priority=_TURN)`. `_TURN = 1`.
- Consumes: `capture_registered_clip` (Task 1), `renderer.load_instance_clip`, existing `submit`/`set_idle`/`_start_clip`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bridge_character_anim.py` (the `_FakeRenderer` already records `loaded`, `played`, `idled`, `restored`):

```python
def test_request_turn_swaps_idle_and_submits_turn(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()      # identity asset_resolver
    r = _FakeRenderer()
    ch = _Char(11)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    # BreatheTurned became the default idle; the TurnCaptain transient is playing.
    bt_idx = r.loaded[(11, "BreatheTurned.nif")]
    tc_idx = r.loaded[(11, "TurnCaptain.nif")]
    assert ctrl._idle_clips[11] == bt_idx
    assert r.played[-1] == (11, tc_idx)


def test_request_turn_back_restores_normal_breathe(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(12)
    ctrl.request_turn_back(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    breathe_idx = r.loaded[(12, "Breathe.nif")]
    back_idx = r.loaded[(12, "BackCaptain.nif")]
    assert ctrl._idle_clips[12] == breathe_idx
    assert r.played[-1] == (12, back_idx)


def test_request_turn_missing_clips_is_graceful(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip", lambda ch, suffix: None)
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(13)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)     # no crash; nothing submitted
    assert 13 not in ctrl._idle_clips
    assert r.played == []


def test_asset_resolver_applied(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController(asset_resolver=lambda p: "/abs/" + p)
    r = _FakeRenderer()
    ch = _Char(14)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert (14, "/abs/BreatheTurned.nif") in r.loaded
    assert (14, "/abs/TurnCaptain.nif") in r.loaded
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: FAIL — `request_turn` not defined / `asset_resolver` not accepted.

- [ ] **Step 3: Implement turn handling**

In `engine/bridge_character_anim.py`:

Add the import at the top (after the existing imports):

```python
from engine.appc.bridge_placement import capture_registered_clip
```

Add the priority constant near `_IDLE`/`_REACTION`:

```python
_TURN = 1       # turn-to-captain preempts idle (0); same band as reactions
```

Extend `__init__`:

```python
    def __init__(self, asset_resolver=None):
        self._active = {}           # iid -> _Action
        self._dur_cache = {}        # nif_path -> real clip duration (s)
        self._idle_clips = {}       # iid -> looping breathe clip index
        self._pending_turns = []    # [(character, turn_bool), ...]
        self._resolve = asset_resolver or (lambda p: p)
```

Add the request methods (next to `set_idle`):

```python
    def request_turn(self, character) -> None:
        """Queue a turn-to-captain (drained on the next update, which has the
        renderer). Called from CharacterClass.MenuUp via the registry."""
        self._pending_turns.append((character, True))

    def request_turn_back(self, character) -> None:
        """Queue a turn-back-to-normal (CharacterClass.MenuDown)."""
        self._pending_turns.append((character, False))
```

Clear the queue in `reset`:

```python
    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
        self._pending_turns = []
```

Drain the queue at the START of `update` (before the `_active` loop):

```python
    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        if self._pending_turns:
            pending, self._pending_turns = self._pending_turns, []
            for character, turn in pending:
                self._process_turn(renderer, character, turn)
        done = []
        for iid, act in self._active.items():
            # ... unchanged ...
```

Add `_process_turn` (next to `_return_to_default`):

```python
    def _process_turn(self, renderer, character, turn) -> None:
        """Swap the default idle (BreatheTurned <-> Breathe) and play the
        turn/back transient. Best-effort: a missing clip skips that half."""
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            return
        idle_suffix = "BreatheTurned" if turn else "Breathe"
        move_suffix = "TurnCaptain" if turn else "BackCaptain"
        idle = capture_registered_clip(character, idle_suffix)
        if idle and hasattr(renderer, "load_instance_clip"):
            idx = renderer.load_instance_clip(iid, self._resolve(idle["clip_nif"]))
            if idx is not None and idx >= 0:
                self.set_idle(iid, idx)
        move = capture_registered_clip(character, move_suffix)
        if move:
            self.submit(character, [(self._resolve(move["clip_nif"]), 0.0)], priority=_TURN)
```

- [ ] **Step 4: Run to verify pass (and no regression)**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: PASS — the four new tests plus all pre-existing controller/breathing tests (the default `asset_resolver` is identity, so existing behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_character_anim.py tests/unit/test_bridge_character_anim.py
git commit -m "feat(bridge): controller turn-to-captain requests (swap idle + transient)"
```

---

### Task 3: `MenuUp`/`MenuDown` drive the turn via the seam

**Files:**
- Modify: `engine/appc/characters.py` (`MenuUp`/`MenuDown` notify the controller + return value)
- Test: `tests/unit/test_menu_up_down.py` (new)

**Interfaces:**
- Produces: `CharacterClass.MenuUp()` sets the flag, notifies `get_controller().request_turn(self)`, returns `1`; `MenuDown()` clears the flag, notifies `request_turn_back(self)`. Both no-op cleanly when no controller is registered.
- Consumes: `engine.bridge_character_anim.get_controller`, `request_turn`/`request_turn_back` (Task 2).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_menu_up_down.py`:

```python
import App
from engine.bridge_character_anim import (
    BridgeCharacterAnimController, set_controller, clear_controller,
)


def _char():
    c = App.CharacterClass_Create("b.nif", "h.nif")
    c.SetCharacterName("Test")
    return c


def test_menu_up_sets_flag_returns_truthy_and_requests_turn():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        ret = c.MenuUp()
        assert ret                                  # truthy (SDK checks it)
        assert c.IsMenuUp() == 1
        assert ctrl._pending_turns == [(c, True)]
    finally:
        clear_controller()


def test_menu_down_clears_flag_and_requests_turn_back():
    ctrl = BridgeCharacterAnimController()
    set_controller(ctrl)
    try:
        c = _char()
        c.MenuUp()
        c.MenuDown()
        assert c.IsMenuUp() == 0
        assert ctrl._pending_turns[-1] == (c, False)
    finally:
        clear_controller()


def test_menu_up_no_controller_is_safe():
    clear_controller()
    c = _char()
    assert c.MenuUp()                               # still truthy, no crash
    assert c.IsMenuUp() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_menu_up_down.py -v`
Expected: FAIL — `MenuUp` returns None and does not notify the controller.

- [ ] **Step 3: Implement the notify + return**

In `engine/appc/characters.py`, replace the `MenuUp`/`MenuDown` stubs (lines ~557-558):

```python
    def MenuUp(self, *args) -> int:
        # SDK seam (BridgeHandlers: `if (pCharacter.MenuUp()): ...`). Set the
        # state flag and ask the character-anim controller to turn this officer
        # toward the captain (deferred — the controller pump has the renderer).
        self._data["MenuUp"] = True
        self._notify_menu(turn=True)
        return 1

    def MenuDown(self, *args) -> None:
        self._data["MenuUp"] = False
        self._notify_menu(turn=False)

    def _notify_menu(self, turn) -> None:
        try:
            from engine.bridge_character_anim import get_controller
            ctrl = get_controller()
            if ctrl is None:
                return
            if turn:
                ctrl.request_turn(self)
            else:
                ctrl.request_turn_back(self)
        except Exception:
            pass
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_menu_up_down.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_menu_up_down.py
git commit -m "feat(bridge): MenuUp/MenuDown drive turn-to-captain via the controller seam"
```

---

### Task 4: Suppress idle gestures while a menu is up

**Files:**
- Modify: `engine/bridge_idle_gestures.py` (`IdleGestureScheduler.update` skips `IsMenuUp()` officers)
- Test: `tests/unit/test_bridge_idle_gestures.py` (suppression)

**Interfaces:**
- Consumes: `character.IsMenuUp()` (returns 1 while a menu is up).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_bridge_idle_gestures.py` (reuses the file's `_Controller`, `_Char`, and the `_builder_returns_one_clip` monkeypatch helper):

```python
def test_menu_up_officer_is_suppressed(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.Foo",)])
    ch._menu_up = True                       # IsMenuUp() -> 1 (see _Char below)
    sched.update(1.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []              # suppressed while menu is up
```

In the same file, give the test `_Char` an `IsMenuUp` reading an optional flag (add to its class, defaulting off so existing tests are unaffected):

```python
    def IsMenuUp(self):
        return 1 if getattr(self, "_menu_up", False) else 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_idle_gestures.py -v`
Expected: FAIL — the menu-up officer still gets a gesture submitted.

- [ ] **Step 3: Add the suppression guard**

In `engine/bridge_idle_gestures.py`, in `IdleGestureScheduler.update`, add the guard alongside the existing hidden/unrealised skips (the loop over `characters`):

```python
            if ch.IsHidden():
                continue
            if ch.IsMenuUp():
                continue                     # attending the captain — no idle
```

(Place the `IsMenuUp()` check next to the existing `IsHidden()` check; match the surrounding structure exactly.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_bridge_idle_gestures.py -v`
Expected: PASS (new test + all pre-existing idle-gesture tests; their `_Char` has `_menu_up` off → `IsMenuUp()` 0 → unaffected).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_idle_gestures.py tests/unit/test_bridge_idle_gestures.py
git commit -m "feat(bridge): suppress idle gestures for a menu-up officer"
```

---

### Task 5: Crew-menu wiring + host_loop asset resolver

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` (`toggle_menu` / `close_open_menu` drive `MenuUp`/`MenuDown`)
- Modify: `engine/host_loop.py` (construct the controller with the game-asset resolver)
- Test: `tests/unit/test_crew_menu_turn.py` (new)

**Interfaces:**
- Consumes: `crew_menu_hotkeys.resolve_character(label)`, the resolved officer's `MenuUp()`/`MenuDown()` (Task 3).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_crew_menu_turn.py`. It drives the panel's open/close transitions and asserts `MenuUp`/`MenuDown` fire on the right officers via a stubbed `resolve_character`:

```python
from engine.ui import crew_menu_panel as cmp_mod
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.appc.characters import STMenu


class _Officer:
    def __init__(self, name):
        self.name = name
        self.up = False
    def MenuUp(self):
        self.up = True; return 1
    def MenuDown(self):
        self.up = False


def _menu(label, wid):
    m = STMenu()
    m.SetLabel(label)
    m._test_wid = wid                      # ensure_widget_id stub key
    m.SetEnabled(1) if hasattr(m, "SetEnabled") else None
    return m


def test_open_turns_officer_close_turns_back(monkeypatch):
    officers = {"Helm": _Officer("Helm")}
    monkeypatch.setattr(cmp_mod.crew_menu_hotkeys, "resolve_character",
                        lambda label: officers.get(label))
    panel = CrewMenuPanel.__new__(CrewMenuPanel)   # bypass heavy __init__
    panel._open_menu_id = None
    panel._expanded_ids = set()
    # Make the panel's id + label resolution deterministic for the test:
    monkeypatch.setattr(panel, "_menu_officer",
                        lambda: officers.get("Helm") if panel._open_menu_id == 1 else None,
                        raising=False)

    helm = _menu("Helm", 1)
    monkeypatch.setattr(cmp_mod, "ensure_widget_id", lambda m: m._test_wid)

    panel.toggle_menu(helm)                # open
    assert officers["Helm"].up is True
    panel.toggle_menu(helm)                # close (toggle same)
    assert officers["Helm"].up is False
```

(If `CrewMenuPanel`/`STMenu` construction differs, adapt the fixture to the real constructors — the assertion that matters is: opening calls `MenuUp` on the resolved officer, closing calls `MenuDown`. Read `crew_menu_panel.py` and mirror its real `toggle_menu` surface.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_crew_menu_turn.py -v`
Expected: FAIL — `toggle_menu` does not call `MenuUp`/`MenuDown`.

- [ ] **Step 3: Drive `MenuUp`/`MenuDown` from the panel**

In `engine/ui/crew_menu_panel.py`, add a helper to resolve the open menu's officer and a turn-reconciler, and call them from `toggle_menu` and `close_open_menu`:

```python
    def _menu_officer(self):
        """The CharacterClass owning the currently-open top-level menu, or None."""
        label = self.open_menu_label()
        if label is None:
            return None
        try:
            from engine.ui import crew_menu_hotkeys
            return crew_menu_hotkeys.resolve_character(label)
        except Exception:
            return None

    @staticmethod
    def _reconcile_turn(old, new):
        """Turn the officer losing focus back, and the one gaining focus toward
        the captain. old/new are CharacterClass or None; identical -> no-op."""
        if old is new:
            return
        if old is not None:
            try: old.MenuDown()
            except Exception: pass
        if new is not None:
            try: new.MenuUp()
            except Exception: pass
```

In `toggle_menu`, capture the officer before and after the id change and reconcile:

```python
    def toggle_menu(self, menu) -> None:
        if not isinstance(menu, STMenu) or not menu.IsEnabled():
            return
        wid = ensure_widget_id(menu)
        old_officer = self._menu_officer()
        opening = self._open_menu_id != wid
        self._open_menu_id = None if self._open_menu_id == wid else wid
        self._expanded_ids.clear()
        self._reconcile_turn(old_officer, self._menu_officer())
        if opening:
            self._acknowledge(menu)
```

In `close_open_menu`, turn the current officer back before clearing:

```python
    def close_open_menu(self) -> bool:
        if self._open_menu_id is None:
            return False
        officer = self._menu_officer()
        self._open_menu_id = None
        self._expanded_ids.clear()
        if officer is not None:
            try: officer.MenuDown()
            except Exception: pass
        return True
```

(`invalidate` already clears `_open_menu_id` on mission swap; officers are re-realised, so no `MenuDown` is needed there.)

- [ ] **Step 4: Wire the game-asset resolver into the controller**

In `engine/host_loop.py`, where `BridgeCharacterAnimController()` is constructed (the breathing wiring, ~line 2923), pass the game-asset resolver so the controller's turn loads resolve to absolute paths. Define a module-level helper (mirroring `_place_one_character`'s local `_abs`) near the top-level constants and use it both there and at the controller construction:

```python
def _game_asset_path(p):
    return str(PROJECT_ROOT / "game" / p) if p else None
```

Change the controller construction to:

```python
        char_anim = BridgeCharacterAnimController(asset_resolver=_game_asset_path)
```

(Optionally refactor `_place_one_character`'s local `_abs` to `_game_asset_path` for consistency — same behavior.)

- [ ] **Step 5: Run the focused tests + host smoke**

Run: `uv run pytest tests/unit/test_crew_menu_turn.py tests/unit/test_bridge_character_anim.py tests/unit/test_menu_up_down.py tests/host/test_host_loop_unit.py -q`
Expected: PASS.

- [ ] **Step 6: Full-suite regression + GUI note**

Run: `./scripts/run_tests.sh`
Expected: all pass (the C++ `FrameTest.PhaserHeatGlow…` failure is the known pre-existing offscreen-GL artifact, not run by `run_tests.sh`). Report that the user should GUI-verify: selecting a station turns the officer to face the captain + breathes-turned + no idle look-arounds; deselecting turns them back + resumes breathing; switching officers turns the old one back. **Flag the E-bridge root-motion risk** (eb_face_capt_e/s carry root rotation+translation) for the user to watch — if an E-bridge officer slides when turning, that's the deferred native-fallback case. Do NOT launch the GUI yourself.

- [ ] **Step 7: Commit**

```bash
git add engine/ui/crew_menu_panel.py engine/host_loop.py tests/unit/test_crew_menu_turn.py
git commit -m "feat(bridge): crew menu drives MenuUp/MenuDown; controller gets game-asset resolver"
```

---

## Self-Review

**Spec coverage:**
- `capture_registered_clip` (generalized, refactors `capture_breathing`) → Task 1 ✓
- `MenuUp`/`MenuDown` seam drives turn + sets flag + returns truthy → Task 3 ✓
- Controller `request_turn`/`request_turn_back` → `set_idle(BreatheTurned/Breathe)` + `submit(TurnCaptain/BackCaptain)` → Task 2 ✓
- Idle suppression via `IsMenuUp()` → Task 4 ✓
- Crew-menu drives `MenuUp`/`MenuDown` across open/close/switch → Task 5 ✓
- Deferred renderer work in the controller pump (asset resolver) → Task 2 (param) + Task 5 (wired) ✓
- Best-effort / missing-clip graceful → Task 2 `_process_turn`, Task 3 no-controller path ✓
- E-bridge root-motion risk → flagged for GUI (Task 5 Step 6); native fallback deferred ✓
- Tests: capture suffixes (T1), controller turn requests (T2), MenuUp/MenuDown (T3), suppression (T4), crew-menu wiring (T5) ✓

**Type consistency:** `capture_registered_clip(character, suffix)->{"clip_nif"}|None`, `request_turn(character)`, `request_turn_back(character)`, `BridgeCharacterAnimController(asset_resolver=None)`, `_TURN=1`, `MenuUp()->int truthy`, `_menu_officer()`, `_reconcile_turn(old,new)` — names/signatures match across tasks.

**Open confirmations (resolve during implementation, not blockers):** exact `path_for` strings for `db_face_capt_e`/`breathing`/`standing_console` (T1 Step 1 note); the real `CrewMenuPanel`/`STMenu` test-fixture surface (T5 Step 1 note — mirror the actual `toggle_menu`); whether `PROJECT_ROOT` is already imported at host_loop top (it is — used by `_place_one_character`'s `_abs`).
