# WC_* Modifier-Chord Keyboard Families Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the ~120 `WC_ALT_*/WC_CTRL_*/WC_CAPS_*` keyboard constants and wire a generic modifier-chord poller so the SDK's ALT/CTRL/Shift keyboard bindings (power presets, maneuvers, clear-target, intercept, debug cheats, tractor/cloak toggles) actually fire.

**Architecture:** Constants are modifier bands OR'd onto existing base codes in `engine/appc/input.py` (collision-free: base codes < 0x200). One new poller in `engine/host_loop.py` edge-detects modifier+key chords and feeds `g_kInputManager`, which emits BOTH `KS_KEYDOWN` and `KS_NORMAL` keyboard events per chord press (the SDK binds each chord under exactly one of those states). `KeyboardBinding` gains `GET_INT_EVENT` support and a destination resolver (our `ProcessEvent` has no parent-window bubbling, so keyboard events must be routed to the object that actually registered the handler). The two bespoke Alt+T/Alt+C bypass pollers are retired; their live-verified direct actions become chord overrides.

**Tech Stack:** Python (engine shim layer), pytest. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-07-16-wc-modifier-chords-design.md`

## Global Constraints

- Shared checkout: NEVER run `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`git add .`. Stage with explicit pathspecs only. Mutate-and-restore by `cp` backup, never by git.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Never use `hasattr`/`getattr(obj, name, default)` to probe engine `TGObject` subclasses for public methods — `TGObject.__getattr__` vends a truthy `_Stub`. Use `engine.core.ids.implements(obj, name)`. (`_underscore` names raise `AttributeError` normally, so `getattr(obj, "_handlers", None)` is safe.)
- Production behaviour outside dev mode must be SDK-faithful; the four debug chords (Shift+K/R/G, Ctrl+Q) are dev-gated per Mark's decision.
- Run the full gate `scripts/run_tests.sh` per task; `scripts/check_tests.sh` (pytest + ctest + ledger) before finishing.

---

### Task 1: WC modifier constant families

**Files:**
- Modify: `engine/appc/input.py` (constant table section, lines ~29–92)
- Test: `tests/unit/test_wc_modifier_constants.py` (create)

**Interfaces:**
- Produces: `App.WC_ALT_<X>` / `App.WC_CTRL_<X>` / `App.WC_CAPS_<X>` (and `KY_` mirrors) for X ∈ A–Z, 0–9, F1–F12, as ints. Module exports `MODIFIER_BANDS: dict[str, int]` and `MODIFIER_CHORDS: list[tuple[str, str, int]]` (`(modifier_name, base_name, chord_code)`) consumed by Task 5's poller.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_wc_modifier_constants.py`:

```python
"""WC_ALT_/WC_CTRL_/WC_CAPS_ modifier-chord constants.

Undefined WC_* names resolve through App.py's __getattr__ to a _NamedStub
whose int() is 0 — the collapse-onto-slot-0 bug class. hasattr(App, ...)
is therefore ALWAYS true; these tests check the input module directly and
assert int-ness on App.
"""
import re
from pathlib import Path

import App
import engine.appc.input as appc_input

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_BASES = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [chr(c) for c in range(ord("0"), ord("9") + 1)]
    + ["F%d" % n for n in range(1, 13)]
)


def _family_names():
    return ["WC_%s_%s" % (mod, base)
            for mod in ("ALT", "CTRL", "CAPS") for base in _BASES]


def test_all_family_constants_are_real_ints_on_App():
    for name in _family_names():
        val = getattr(App, name)
        assert isinstance(val, int), "%s is not an int (stub collapse!)" % name
        assert val != 0, "%s collapsed to 0" % name


def test_family_codes_distinct_and_disjoint_from_base_band():
    codes = [getattr(appc_input, n) for n in _family_names()]
    assert len(set(codes)) == len(codes), "duplicate chord codes"
    base_codes = {v for k, v in vars(appc_input).items()
                  if k.startswith("WC_") and isinstance(v, int) and v < 0x200}
    assert not (set(codes) & base_codes), "chord band collides with base band"


def test_every_wc_name_the_sdk_references_is_defined():
    sdk = _PROJECT_ROOT / "sdk" / "Build" / "scripts"
    src = ""
    for fname in ("KeyConfig.py", "DefaultKeyboardBinding.py"):
        src += (sdk / fname).read_text(errors="replace")
    referenced = set(re.findall(r"App\.(WC_[A-Za-z0-9_]+)", src))
    missing = sorted(n for n in referenced
                     if not isinstance(getattr(appc_input, n, None), int))
    assert missing == [], "SDK references undefined WC_ names: %s" % missing


def test_modifier_chords_export_shape():
    assert appc_input.MODIFIER_BANDS == {"ALT": 0x200, "CTRL": 0x400, "CAPS": 0x800}
    assert len(appc_input.MODIFIER_CHORDS) == 3 * len(_BASES)
    mod, base, code = appc_input.MODIFIER_CHORDS[0]
    assert code == appc_input.MODIFIER_BANDS[mod] | getattr(appc_input, "WC_" + base)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_wc_modifier_constants.py -v`
Expected: FAIL — `WC_ALT_A is not an int (stub collapse!)` and `MODIFIER_BANDS` AttributeError.

- [ ] **Step 3: Implement the constant families**

In `engine/appc/input.py`, replace the "Intentionally absent" paragraph of the comment block (lines ~29–32) with:

```python
# The CTRL_/ALT_/CAPS_ modifier families are modifier BANDS OR'd onto the
# base code (base codes stay below 0x200, so the bands never collide with
# them or each other).  KeyConfig.MapScancodes registers WC_CAPS_<letter>
# with modifier=KY_SHIFT — CAPS_X means the *capital character* (Shift+X),
# NOT CapsLock state.  App.py's module __getattr__ WC_/KY_ fallback
# surfaces every name defined here.
```

Then, immediately after the `_SYNTH_NAMED` loop (after line ~91), add:

```python
# Modifier-chord families — see comment above.  MODIFIER_CHORDS feeds the
# host-loop chord poller: (modifier_name, base_name, chord_code).
MODIFIER_BANDS = {"ALT": 0x200, "CTRL": 0x400, "CAPS": 0x800}
MODIFIER_CHORDS: list = []
_MOD_BASE_NAMES = (
    [chr(_c) for _c in range(ord("A"), ord("Z") + 1)]
    + [chr(_c) for _c in range(ord("0"), ord("9") + 1)]
    + ["F%d" % _n for _n in range(1, 13)]
)
for _mod, _band in MODIFIER_BANDS.items():
    for _base in _MOD_BASE_NAMES:
        _code = _band | globals()["WC_" + _base]
        _def_key("%s_%s" % (_mod, _base), _code)
        MODIFIER_CHORDS.append((_mod, _base, _code))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_wc_modifier_constants.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run the input-adjacent suites, then commit**

Run: `uv run pytest tests/unit/test_tg_input_manager.py tests/unit/test_keyboard_binding.py tests/unit/test_wc_modifier_constants.py -v`
Expected: all PASS.

```bash
git add engine/appc/input.py tests/unit/test_wc_modifier_constants.py
git commit -m "feat(input): define WC_ALT/CTRL/CAPS modifier-chord constant families

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: TGInputManager chord emission (registration gate + dual-state)

**Files:**
- Modify: `engine/appc/input.py` (`TGInputManager`, lines ~99–138)
- Test: `tests/unit/test_tg_input_manager.py` (extend — read the file first and follow its existing fixture pattern)

**Interfaces:**
- Consumes: chord constants from Task 1.
- Produces: `TGInputManager.OnChordDown(wc_code)` — emits a `KS_KEYDOWN` **and** a `KS_NORMAL` `TGKeyboardEvent` for a chord code registered under `(wc_code, modifier)`; `TGInputManager._registered_codes: set[int]` maintained by `RegisterUnicodeKey`. `OnKeyUp(wc_code)` now also works for modifier-registered codes.

**Why:** `KeyConfig.py:194/286/411` registers chords as `RegisterUnicodeKey(App.WC_CAPS_A, App.KY_A, db, "A", App.KY_SHIFT)` — stored under the tuple key `(wc, modifier)`. `_emit`'s gate `if wc_code not in self._registered` only sees bare-int keys, so chord codes would be dropped. And the ALT/CTRL number chords are bound under `KS_NORMAL` (`DefaultKeyboardBinding.py:161-173`) while CTRL_D/T/I etc. use `KS_KEYDOWN` — emitting both states lets exactly one binding fire (BC's input manager produces a char event alongside keydown; decomp has no contrary evidence — searched `../STBC-Reverse-Engineering-1/docs/` for KS_NORMAL/TGInputManager, only RTTI catalog mentions).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_tg_input_manager.py` (adapt imports/fixtures to the file's existing style):

```python
def test_modifier_registered_chord_emits_keydown_and_normal(fresh_pipeline):
    mgr, _binding, event_manager = fresh_pipeline  # follow existing fixture
    import App
    mgr.RegisterUnicodeKey(App.WC_ALT_1, App.KY_1, None, "ALT-1", App.KY_ALT)
    seen = []
    orig_add = event_manager.AddEvent
    event_manager.AddEvent = lambda ev: seen.append(
        (ev.GetUnicodeKey(), ev.GetKeyState())) or orig_add(ev)
    mgr.OnChordDown(App.WC_ALT_1)
    from engine.appc.input import KS_KEYDOWN, KS_NORMAL
    assert (App.WC_ALT_1, KS_KEYDOWN) in seen
    assert (App.WC_ALT_1, KS_NORMAL) in seen


def test_unregistered_chord_is_dropped(fresh_pipeline):
    mgr, _binding, event_manager = fresh_pipeline
    import App
    seen = []
    orig_add = event_manager.AddEvent
    event_manager.AddEvent = lambda ev: seen.append(ev) or orig_add(ev)
    mgr.OnChordDown(App.WC_CTRL_Z)   # never registered
    assert seen == []


def test_keyup_works_for_modifier_registered_code(fresh_pipeline):
    mgr, _binding, event_manager = fresh_pipeline
    import App
    mgr.RegisterUnicodeKey(App.WC_CAPS_K, App.KY_K, None, "K", App.KY_SHIFT)
    seen = []
    orig_add = event_manager.AddEvent
    event_manager.AddEvent = lambda ev: seen.append(ev.GetKeyState()) or orig_add(ev)
    mgr.OnKeyUp(App.WC_CAPS_K)
    from engine.appc.input import KS_KEYUP
    assert seen == [KS_KEYUP]
```

If the file has no shared fixture, construct the pipeline the way its existing tests do (e.g. `TGEventManager()` + `TGInputManager(em)`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tg_input_manager.py -v -k "chord or modifier_registered"`
Expected: FAIL — `OnChordDown` missing / events dropped by the bare-key gate.

- [ ] **Step 3: Implement**

In `TGInputManager.__init__`, add:

```python
        # Every registered WC code, bare or modifier-variant — the _emit
        # gate.  The dict keys mix ints and (wc, modifier) tuples, so a
        # bare `wc in self._registered` misses chord codes.
        self._registered_codes: set[int] = set()
```

In `RegisterUnicodeKey`, add `self._registered_codes.add(int(wc_code))` (once, before the if/else).

Change `_emit`'s gate to:

```python
        if wc_code not in self._registered_codes:
            return
```

Add after `OnKeyUp`:

```python
    def OnChordDown(self, wc_code: int) -> None:
        """Modifier-chord press.  BC's input manager produces a character
        event (KS_NORMAL) alongside the keydown; the SDK binds each chord
        under exactly one state (KS_KEYDOWN for CTRL_D/T/I and the CAPS
        debug keys, KS_NORMAL for the ALT/CTRL number chords), so exactly
        one binding fires per press."""
        self._emit(int(wc_code), KS_KEYDOWN)
        self._emit(int(wc_code), KS_NORMAL)
```

- [ ] **Step 4: Run the file's full suite**

Run: `uv run pytest tests/unit/test_tg_input_manager.py -v`
Expected: all PASS (the `_registered_codes` gate must not break existing bare-key tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/input.py tests/unit/test_tg_input_manager.py
git commit -m "feat(input): chord-aware TGInputManager — dual-state OnChordDown, modifier registration gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: KeyboardBinding GET_INT_EVENT support

**Files:**
- Modify: `engine/appc/input.py` (`KeyboardBinding._build_event`, lines ~200–209)
- Test: `tests/unit/test_keyboard_binding.py` (extend, following its existing patterns)

**Interfaces:**
- Produces: keyboard bindings registered with `GET_INT_EVENT` deliver an `App._TGIntEvent` whose `GetInt()` returns the bound value. (SDK `EngineerMenuHandlers.ManagePower` reads `pEvent.GetInt()` for the preset index 0–7; `TacticalMenuHandlers.Maneuver` reads it for the order subtype 1–4.)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_keyboard_binding.py`:

```python
def test_int_event_binding_delivers_value(fresh_pipeline):
    import App
    from engine.appc.events import TGKeyboardEvent
    from engine.appc.input import KS_NORMAL, KeyboardBinding
    _mgr, binding, event_manager = fresh_pipeline
    captured = []
    orig_add = event_manager.AddEvent
    event_manager.AddEvent = lambda ev: captured.append(ev) or orig_add(ev)

    binding.BindKey(App.WC_ALT_3, KS_NORMAL, App.ET_MANAGE_POWER,
                    KeyboardBinding.GET_INT_EVENT, 2,
                    KeyboardBinding.KBT_SINGLE_KEY_TO_EVENT)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_ALT_3)
    evt.SetKeyState(KS_NORMAL)
    binding.OnKeyboardEvent(None, evt)

    out = [e for e in captured if e.GetEventType() == App.ET_MANAGE_POWER]
    assert len(out) == 1
    assert out[0].GetInt() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_keyboard_binding.py -v -k int_event`
Expected: FAIL — the built event is a plain `TGEvent` with no `GetInt` returning 2 (a `_Stub` would return truthy garbage, or AttributeError depending on class — either way not 2).

- [ ] **Step 3: Implement**

Replace `_build_event`:

```python
    def _build_event(self, event_type: int, flags: int, value) -> TGEvent:
        if flags == self.GET_BOOL_EVENT:
            ev = TGBoolEvent()
            ev.SetBool(value)
        elif flags == self.GET_INT_EVENT:
            # ManagePower/Maneuver read GetInt() for the preset/order index.
            import App  # deferred — _TGIntEvent lives in the App shim
            ev = App.TGIntEvent_Create()
            ev.SetInt(int(value))
        else:
            # GET_FLOAT_EVENT: no polled consumer yet (the impulse number
            # row isn't polled); add with its first real consumer.
            ev = TGEvent()
        ev.SetEventType(event_type)
        return ev
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_keyboard_binding.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/input.py tests/unit/test_keyboard_binding.py
git commit -m "feat(input): KeyboardBinding builds TGIntEvent for GET_INT_EVENT bindings

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Keyboard destination resolution

**Files:**
- Modify: `engine/appc/input.py` (`KeyboardBinding.OnKeyboardEvent`, lines ~189–198)
- Test: `tests/unit/test_keyboard_binding.py` (extend)

**Interfaces:**
- Consumes: `engine.core.ids.implements`, `App.TopWindow_GetTopWindow()`.
- Produces: keyboard-bound events are delivered to the first of [default destination (TCW), TCW's tactical menu, TopWindow] that registered an instance handler for the event type; falls back to the default destination unchanged.

**Why:** `TGEventManager.AddEvent` (`engine/appc/events.py:481-490`) delivers a destination event straight to `dest.ProcessEvent` — there is no parent-window bubbling. But the SDK registers `ManagePower` on **TopWindow** (`EngineerMenuHandlers.py:145`) and `Maneuver` on the **tactical menu** (`TacticalMenuHandlers.py:397`), while `host_loop` sets the binding's default destination to the **TCW** (`host_loop.py:169,2771`). In BC these bubble up the window chain; this resolver reproduces that narrowly for the keyboard path only.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_keyboard_binding.py`:

```python
_resolver_hits = []


def _resolver_probe(pObject, pEvent):
    _resolver_hits.append((pObject, pEvent.GetInt()))


def test_keyboard_event_routes_to_object_with_handler(fresh_pipeline, monkeypatch):
    import App
    from engine.appc.events import TGEventHandlerObject, TGKeyboardEvent
    from engine.appc.input import KS_NORMAL, KeyboardBinding
    _mgr, binding, _em = fresh_pipeline
    del _resolver_hits[:]

    tcw = TGEventHandlerObject()          # no handler for ET_MANAGE_POWER
    top = TGEventHandlerObject()
    top.AddPythonFuncHandlerForInstance(
        App.ET_MANAGE_POWER, __name__ + "._resolver_probe")
    binding.SetDefaultDestination(tcw)
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: top)

    binding.BindKey(App.WC_ALT_1, KS_NORMAL, App.ET_MANAGE_POWER,
                    KeyboardBinding.GET_INT_EVENT, 0,
                    KeyboardBinding.KBT_SINGLE_KEY_TO_EVENT)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_ALT_1)
    evt.SetKeyState(KS_NORMAL)
    binding.OnKeyboardEvent(None, evt)

    assert _resolver_hits == [(top, 0)], \
        "ET_MANAGE_POWER must route to the object that registered the handler"


def test_keyboard_event_prefers_default_destination_when_it_handles(fresh_pipeline, monkeypatch):
    import App
    from engine.appc.events import TGEventHandlerObject, TGKeyboardEvent
    from engine.appc.input import KeyboardBinding
    from engine.appc.input import KS_KEYDOWN
    _mgr, binding, _em = fresh_pipeline
    del _resolver_hits[:]

    tcw = TGEventHandlerObject()
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CLEAR_TARGET, __name__ + "._resolver_probe")
    top = TGEventHandlerObject()
    top.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_CLEAR_TARGET, __name__ + "._resolver_probe")
    binding.SetDefaultDestination(tcw)
    monkeypatch.setattr(App, "TopWindow_GetTopWindow", lambda: top)

    binding.BindKey(App.WC_CTRL_T, KS_KEYDOWN, App.ET_INPUT_CLEAR_TARGET)
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(App.WC_CTRL_T)
    evt.SetKeyState(KS_KEYDOWN)
    binding.OnKeyboardEvent(None, evt)

    assert [obj for obj, _ in _resolver_hits] == [tcw], \
        "default destination wins when it has a handler"
```

(`GetInt()` on a plain `TGEvent` in the second test: bind with no value → plain `TGEvent`; if `GetInt` is missing on it, change the probe to record only `pObject`. Keep the probe minimal and adjust to what compiles — the routing assertion is the point.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_keyboard_binding.py -v -k routes`
Expected: FAIL — event went to `tcw` (no handler) and `_resolver_hits` stayed empty.

- [ ] **Step 3: Implement**

In `KeyboardBinding`, replace the destination assignment in `OnKeyboardEvent`:

```python
    def OnKeyboardEvent(self, _obj, evt: TGKeyboardEvent) -> None:
        key = (evt.GetUnicodeKey(), evt.GetKeyState())
        binding = self._bindings.get(key)
        if binding is None:
            return
        event_type, flags, value = binding
        out = self._build_event(event_type, flags, value)
        dest = self._resolve_destination(event_type)
        if dest is not None:
            out.SetDestination(dest)
        self._event_manager.AddEvent(out)

    def _resolve_destination(self, event_type: int):
        """BC bubbles keyboard-bound events up the window chain; our
        ProcessEvent dispatches on one object only.  Scan the known
        keyboard consumers — default destination (TCW), its tactical
        menu, TopWindow — for the first that actually registered an
        instance handler for this event type.  Fall back to the default
        destination (today's behaviour) when none did."""
        from engine.core import ids
        candidates = []
        tcw = self._default_destination
        if tcw is not None:
            candidates.append(tcw)
            if ids.implements(tcw, "GetTacticalMenu"):
                menu = tcw.GetTacticalMenu()
                if menu is not None:
                    candidates.append(menu)
        import App  # deferred: input is imported during App bootstrap
        top = App.TopWindow_GetTopWindow()
        if top is not None:
            candidates.append(top)
        for cand in candidates:
            handlers = getattr(cand, "_handlers", None)
            if isinstance(handlers, dict) and handlers.get(int(event_type)):
                return cand
        return tcw
```

Note: `getattr(cand, "_handlers", None)` is safe — underscore names raise real `AttributeError` (never `_Stub`).

- [ ] **Step 4: Run the file's full suite**

Run: `uv run pytest tests/unit/test_keyboard_binding.py tests/unit/test_tg_input_manager.py -v`
Expected: all PASS (existing destination tests must still pass via the fallback).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/input.py tests/unit/test_keyboard_binding.py
git commit -m "feat(input): route keyboard-bound events to the window that registered the handler

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Generic modifier-chord poller (with dev gating and toggle overrides)

**Files:**
- Modify: `engine/host_loop.py` (new functions next to `_poll_key_table`, lines ~255–330)
- Test: `tests/integration/test_modifier_chord_poller.py` (create)

**Interfaces:**
- Consumes: `engine.appc.input.MODIFIER_CHORDS` (Task 1), `TGInputManager.OnChordDown` (Task 2), `engine.dev_mode.is_enabled`, `App.ToggleTractorFromInput` / `App.ToggleCloakFromInput`, `host_io.key_state`.
- Produces: `_poll_modifier_chords(host)` — call once per sim tick; module state `_chord_prev: dict` (reset in tests); helper `_modifier_state(host) -> tuple[bool, bool, bool]` (alt, ctrl, shift) reused by Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_modifier_chord_poller.py`:

```python
"""_poll_modifier_chords: modifier+key chords → g_kInputManager.OnChordDown.

Drives the poller with a fake host.keys namespace and a patched
host_io.key_state, per the established poller-test pattern (patch host_io,
never the native module).
"""
from types import SimpleNamespace
from unittest.mock import patch

import App
import engine.host_loop as host_loop


def _fake_keys():
    ns = SimpleNamespace()
    # GLFW codes are arbitrary ints for the test — internal consistency only.
    ns.KEY_LEFT_ALT, ns.KEY_RIGHT_ALT = 342, 346
    ns.KEY_LEFT_CONTROL, ns.KEY_RIGHT_CONTROL = 341, 345
    ns.KEY_LEFT_SHIFT, ns.KEY_RIGHT_SHIFT = 340, 344
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        setattr(ns, "KEY_" + ch, 65 + i)
    for d in range(10):
        setattr(ns, "KEY_%d" % d, 48 + d)
    for f in range(1, 13):
        setattr(ns, "KEY_F%d" % f, 289 + f)
    return ns


class _KeyState:
    def __init__(self):
        self.down = set()

    def __call__(self, code):
        return 1 if code in self.down else 0


def setup_function(_fn):
    host_loop._chord_prev.clear()


def test_alt_number_chord_emits_on_rising_edge_only():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(("down", wc))), \
         patch.object(App.g_kInputManager, "OnKeyUp",
                      side_effect=lambda wc: calls.append(("up", wc))):
        ks.down = {keys.KEY_LEFT_ALT, keys.KEY_1}
        host_loop._poll_modifier_chords(host)
        host_loop._poll_modifier_chords(host)      # held: no repeat
        ks.down = {keys.KEY_LEFT_ALT}
        host_loop._poll_modifier_chords(host)      # released: keyup
    assert calls == [("down", App.WC_ALT_1), ("up", App.WC_ALT_1)]


def test_no_modifier_no_emission():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(wc)):
        ks.down = {keys.KEY_1}
        host_loop._poll_modifier_chords(host)
    assert calls == []


def test_debug_chords_gated_behind_dev_mode():
    import engine.dev_mode as dev_mode
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    calls = []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: calls.append(wc)):
        ks.down = {keys.KEY_LEFT_SHIFT, keys.KEY_G}     # Shift+G god mode
        with patch.object(dev_mode, "is_enabled", return_value=False):
            host_loop._poll_modifier_chords(host)
        assert calls == [], "debug chord must not emit outside --developer"
        host_loop._chord_prev.clear()
        with patch.object(dev_mode, "is_enabled", return_value=True):
            host_loop._poll_modifier_chords(host)
        assert calls == [App.WC_CAPS_G]


def test_alt_t_and_alt_c_drive_direct_toggles_not_events():
    keys = _fake_keys()
    host = SimpleNamespace(keys=keys)
    ks = _KeyState()
    chord_calls, tractor_calls = [], []
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnChordDown",
                      side_effect=lambda wc: chord_calls.append(wc)), \
         patch.object(App, "ToggleTractorFromInput",
                      side_effect=lambda: tractor_calls.append(1)):
        ks.down = {keys.KEY_LEFT_ALT, keys.KEY_T}
        host_loop._poll_modifier_chords(host)
        host_loop._poll_modifier_chords(host)      # held: one toggle only
    assert tractor_calls == [1]
    assert App.WC_ALT_T not in chord_calls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_modifier_chord_poller.py -v`
Expected: FAIL — `host_loop` has no `_chord_prev` / `_poll_modifier_chords`.

- [ ] **Step 3: Implement the poller**

In `engine/host_loop.py`, after `_poll_key_table` (~line 276), add:

```python
# Previous-frame chord levels, keyed by WC chord code. Module-level so
# tests can reset it (mirrors _fn_key_prev).
_chord_prev: dict = {}


def _modifier_state(host):
    """(alt, ctrl, shift) held-state off the raw host key levels.  Safe on
    a stale binary whose keys submodule predates the modifier exports."""
    keys = getattr(host, "keys", None) if host is not None else None
    if keys is None or not hasattr(keys, "KEY_LEFT_ALT"):
        return (False, False, False)

    def _held(*names):
        return any(
            bool(host_io.key_state(getattr(keys, n)))
            for n in names if hasattr(keys, n)
        )

    return (
        _held("KEY_LEFT_ALT", "KEY_RIGHT_ALT"),
        _held("KEY_LEFT_CONTROL", "KEY_RIGHT_CONTROL"),
        _held("KEY_LEFT_SHIFT", "KEY_RIGHT_SHIFT"),
    )


def _dev_gated_chords():
    """SDK binds these debug cheats unconditionally (retail BC shipped them
    live); dauntless keeps production cheat-free per the dev_combat_cheats
    convention — Mark's call, 2026-07-16 spec."""
    import App  # deferred: module-top import reorders sound-manager init
    return {App.WC_CAPS_K, App.WC_CAPS_R, App.WC_CAPS_G, App.WC_CTRL_Q}


def _chord_overrides():
    """Chords that drive a live-verified direct action instead of the WC
    event pipeline: the SDK ToggleTractorBeam chain (window handler
    resolution + CallNextHandler + event re-fire) does not reliably reach
    the TacWeaponsCtrl in our engine — see App.ToggleTractorFromInput."""
    import App  # deferred: module-top import reorders sound-manager init
    return {
        App.WC_ALT_T: App.ToggleTractorFromInput,
        App.WC_ALT_C: App.ToggleCloakFromInput,
    }


def _poll_modifier_chords(host) -> None:
    """Edge-detect every modifier+key chord the SDK can bind (ALT/CTRL/
    Shift × letters, digits, F-keys) and feed rising edges to
    g_kInputManager.OnChordDown (KS_KEYDOWN + KS_NORMAL — the SDK binds
    each chord under exactly one state) and falling edges to OnKeyUp.
    CAPS_ chords are Shift+key: KeyConfig registers them with KY_SHIFT.
    Replaces the bespoke _poll_tractor_toggle/_poll_cloak_toggle pair."""
    keys = getattr(host, "keys", None) if host is not None else None
    if keys is None or not hasattr(keys, "KEY_LEFT_ALT"):
        return
    alt, ctrl, shift = _modifier_state(host)
    if not (alt or ctrl or shift) and not _chord_prev:
        return
    import App  # deferred: module-top import reorders sound-manager init
    import engine.dev_mode as dev_mode
    from engine.appc.input import MODIFIER_CHORDS
    mod_held = {"ALT": alt, "CTRL": ctrl, "CAPS": shift}
    gated = _dev_gated_chords()
    overrides = _chord_overrides()
    for mod, base_name, wc in MODIFIER_CHORDS:
        glfw_key = getattr(keys, "KEY_" + base_name, None)
        if glfw_key is None:
            continue
        down = mod_held[mod] and bool(host_io.key_state(glfw_key))
        was_down = _chord_prev.get(wc, False)
        if down and not was_down:
            if wc in gated and not dev_mode.is_enabled():
                pass
            elif wc in overrides:
                overrides[wc]()
            else:
                App.g_kInputManager.OnChordDown(wc)
        elif was_down and not down:
            if wc not in overrides and (
                    wc not in gated or dev_mode.is_enabled()):
                App.g_kInputManager.OnKeyUp(wc)
        if down:
            _chord_prev[wc] = True
        else:
            _chord_prev.pop(wc, None)
```

(`_chord_prev` stores only held chords so the no-modifier early-out stays correct.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_modifier_chord_poller.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/integration/test_modifier_chord_poller.py
git commit -m "feat(host): generic modifier-chord poller — ALT/CTRL/Shift chords feed the WC pipeline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Base-key suppression while ALT/CTRL held

**Files:**
- Modify: `engine/host_loop.py` (`_poll_key_table` ~line 261, `_poll_function_keys` ~278, `_poll_fire_keys` ~301)
- Test: `tests/integration/test_modifier_chord_poller.py` (extend)

**Interfaces:**
- Consumes: `_modifier_state` (Task 5).
- Produces: `_poll_key_table(keymap, suppress=False)` — while `suppress` is true every polled key reads as UP (emitting falling edges for held keys). `_poll_function_keys`/`_poll_fire_keys` pass `suppress = alt or ctrl`.

**Why:** Alt+F must not also fire phasers (WC_F → ET_INPUT_FIRE_PRIMARY). Treating base keys as released while ALT/CTRL is held both suppresses the base binding and cleanly ends an in-progress fire hold. Shift is NOT a suppressor — raw-VK keydown semantics (`WC_F` keydown fires with or without Shift in BC).

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_modifier_chord_poller.py`:

```python
def test_base_keys_suppressed_while_alt_held():
    keys = _fake_keys()
    ks = _KeyState()
    downs, ups = [], []
    keymap = ((keys.KEY_F, 0x46),)   # WC_F = 0x46
    with patch.object(host_loop.host_io, "key_state", ks), \
         patch.object(App.g_kInputManager, "OnKeyDown",
                      side_effect=lambda wc: downs.append(wc)), \
         patch.object(App.g_kInputManager, "OnKeyUp",
                      side_effect=lambda wc: ups.append(wc)):
        host_loop._fn_key_prev.clear()
        ks.down = {keys.KEY_F}
        host_loop._poll_key_table(keymap)                  # plain F: fires
        assert downs == [0x46]
        ks.down = {keys.KEY_F, keys.KEY_LEFT_ALT}
        host_loop._poll_key_table(keymap, suppress=True)   # Alt held: released
        assert ups == [0x46]
        host_loop._poll_key_table(keymap, suppress=True)   # stays quiet
        assert downs == [0x46]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_modifier_chord_poller.py -v -k suppressed`
Expected: FAIL — `_poll_key_table` has no `suppress` parameter.

- [ ] **Step 3: Implement**

Change `_poll_key_table`'s signature and level read:

```python
def _poll_key_table(keymap, suppress: bool = False) -> None:
```

…docstring addition: `While `suppress` is true (ALT/CTRL held) every key in
the table reads as UP: the chord poller owns modified keys, and a held base
key (e.g. fire) gets a clean falling edge.` …and the level read becomes:

```python
        down = (not suppress) and bool(host_io.key_state(glfw_key))
```

In `_poll_function_keys` and `_poll_fire_keys`, replace `del host` with:

```python
    alt, ctrl, _shift = _modifier_state(host)
    suppress = alt or ctrl
```

and pass `suppress=suppress` to their `_poll_key_table` calls. Update their docstrings' "`host` is unused" sentence accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_modifier_chord_poller.py tests/integration/test_bridge_menu_hotkeys.py tests/integration/test_fire_primary_continuous.py -v`
Expected: all PASS (existing hotkey/fire tests exercise `_poll_key_table` callers — they must survive the signature change).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/integration/test_modifier_chord_poller.py
git commit -m "feat(host): suppress base-key bindings while ALT/CTRL held

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Wire the call site, retire bypass pollers, add ET_INPUT_SELF_DESTRUCT

**Files:**
- Modify: `engine/host_loop.py` (sim block ~line 6438-6439; delete `_poll_tractor_toggle`/`_poll_cloak_toggle` + `_tractor_toggle_prev`/`_cloak_toggle_prev`, lines ~327–387)
- Modify: `App.py` (`ET_INPUT_*` constants block ~line 967)
- Modify: any test referencing the deleted pollers (find with the grep in Step 1)
- Test: `tests/integration/test_modifier_chord_poller.py` (extend)

**Interfaces:**
- Consumes: `_poll_modifier_chords` (Task 5).
- Produces: `App.ET_INPUT_SELF_DESTRUCT` as a real int; the sim block calls `_poll_modifier_chords(_h)` where the two bypass pollers used to run.

- [ ] **Step 1: Find every reference to the bypass pollers**

Run: `grep -rn "_poll_tractor_toggle\|_poll_cloak_toggle\|_tractor_toggle_prev\|_cloak_toggle_prev" engine/ tests/`
Expected: the two definitions + two call sites in `engine/host_loop.py`, plus any tests. Every test hit MUST be updated in this task (never orphan tests): re-point poller-level tests at `_poll_modifier_chords` with the same behavioural assertions (Alt+T rising edge → `ToggleTractorFromInput`, exactly once per press) — Task 5's `test_alt_t_and_alt_c_drive_direct_toggles_not_events` already covers this shape; handler-level tests (e.g. `tests/integration/test_tractor_toggle_wiring.py`'s `App._tac_weapons_beam_toggled` tests) are unaffected.

- [ ] **Step 2: Write the failing constant test**

Add to `tests/unit/test_wc_modifier_constants.py`:

```python
def test_chord_target_event_constants_are_real_ints():
    import App
    for name in (
        "ET_MANAGE_POWER", "ET_MANEUVER", "ET_INPUT_SELF_DESTRUCT",
        "ET_INPUT_CLEAR_TARGET", "ET_INPUT_INTERCEPT",
        "ET_INPUT_DEBUG_KILL_TARGET", "ET_INPUT_DEBUG_QUICK_REPAIR",
        "ET_INPUT_DEBUG_GOD_MODE", "ET_INPUT_DEBUG_LOAD_QUANTUMS",
        "ET_OTHER_BEAM_TOGGLE_CLICKED", "ET_OTHER_CLOAK_TOGGLE_CLICKED",
    ):
        assert isinstance(getattr(App, name), int), name
```

Run: `uv run pytest tests/unit/test_wc_modifier_constants.py -v -k event_constants`
Expected: FAIL on `ET_INPUT_SELF_DESTRUCT` (a `_NamedStub`, not an int).

- [ ] **Step 3: Add the constant**

Pick the next unused value adjacent to the other `ET_INPUT_*` constants — verify with `grep -n "= 1041" App.py` (empty output ⇒ free; otherwise walk forward to the first free value). Then in `App.py` near line 967 add, keeping the block's alignment:

```python
ET_INPUT_SELF_DESTRUCT          = 1041
```

Note: the SDK's handler for it is commented out in the shipped SDK
(`TacticalInterfaceHandlers.py:97`) — retail BC's CTRL+D posted an event
nobody consumed. Defining the constant is SDK-faithful; no handler work.

- [ ] **Step 4: Swap the sim-block call site**

In `engine/host_loop.py` sim block (~line 6438), replace:

```python
                _poll_tractor_toggle(_h)
                _poll_cloak_toggle(_h)
```

with:

```python
                _poll_modifier_chords(_h)
```

Delete `_poll_tractor_toggle`, `_poll_cloak_toggle`, `_tractor_toggle_prev`, `_cloak_toggle_prev` entirely, and update the tests found in Step 1.

- [ ] **Step 5: Run the full pytest suite**

Run: `scripts/run_tests.sh`
Expected: PASS (or only failures already in `tests/known_failures.txt` — verify by name, never by eyeball).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py App.py tests/unit/test_wc_modifier_constants.py tests/integration/test_modifier_chord_poller.py
# plus any updated test files found in Step 1, staged EXPLICITLY by path
git commit -m "feat(host): retire tractor/cloak bypass pollers for the unified chord poller; add ET_INPUT_SELF_DESTRUCT

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Full gate + live-verification handoff

**Files:**
- None modified (verification only; heatmap marking happens AFTER live verification with Mark).

- [ ] **Step 1: Run the machine-checked gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 — builds C++, runs pytest + ctest, diffs failures against `tests/known_failures.txt`. Any failure NOT in the ledger is a regression from this work: fix it before proceeding.

- [ ] **Step 2: Prepare the live-verification checklist for Mark**

Do NOT mark heatmap rows resolved yet. Report to Mark that the branch is ready for a live run (`./build/dauntless`, in-mission):

1. ALT+1–8 → power presets change (weapons/engines/sensors/shields ±)
2. CTRL+1–4 → maneuver orders fire
3. CTRL+T → target cleared; CTRL+I → intercept
4. Alt+T / Alt+C → tractor/cloak toggles (no regression)
5. F (fire) while holding ALT → does NOT fire
6. Shift+G/K/R, Ctrl+Q → work under `--developer` ONLY
7. After the run: regenerate the heatmap (`tools/stub_heatmap.py`) and confirm the WC_* rows and `input.py:123/179` coercion entries stop accruing; then set `markedResolvedOn` on the WC_* rows and commit.

Green tests cannot see real input or asset paths — done means Mark has seen it run.
