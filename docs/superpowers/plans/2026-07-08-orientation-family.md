# In-Scene Orientation Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SDK in-scene orientation actions real — `AT_TURN`/`AT_TURN_BACK` (+`_NOW`) and `AT_GLANCE_*` turn a bridge character's body via the existing turn controller, and `AT_WATCH_ME`/`AT_STOP_WATCHING_ME`/`AT_LOOK_AT_ME`(`_NOW`) aim the captain's-eye bridge camera at the named character.

**Architecture:** Two independent mechanisms. **Family A (bones):** `CharacterAction` dispatch routes turns through a generalized `BridgeCharacterAnimController.request_turn_to` that reuses the crew-menu turn path's body+chair coupling (parameterized by the turn's target detail) and fires the action's deferred `Completed()` when the clip settles. **Family B (camera):** a new tiny `BridgeCameraWatchController` holds the currently-watched character; each bridge frame a precedence resolver feeds its head-centre to `_BridgeCamera.set_zoom_target`, above the crew-menu zoom and below any baked cutscene camera path. No native/renderer change.

**Tech Stack:** Python 3 (engine); pytest. (The gate still builds C++ and runs ctest, but this plan adds no native code.)

## Global Constraints

- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). A failure is "pre-existing" only if the ledger says so — never call a failure pre-existing by eyeball.
- **No native rebuild needed:** this plan touches only Python. Do not add C++/bindings. (If you find yourself editing `native/`, stop — the design is pure-Python by construction.)
- **Renderer access discipline:** the watch controller reads the renderer only through the `renderer` object passed to it (which wraps `engine/renderer.py`); it never imports `_dauntless_host`. `get_instance_head_center(iid)` is the existing wrapper (`engine/renderer.py:961`).
- **Best-effort / production-safe:** every dispatch branch collapses to an inline `Completed()` on any failure (no controller, no `CharacterClass` cast, unresolved clip) so a mission `TGSequence` can never stall. The speak/dialogue path (`_do_play`) is untouched. The crew-menu turn path stays behaviourally identical.
- **Rotation/units:** not exercised here (clip playback + camera look-at only); introduce no row-reads or unit conversions.

---

## Task 1: Generalize the turn controller — `request_turn_to` + `on_complete`

**Files:**
- Modify: `engine/bridge_character_anim.py` (`_Action` ~24-39, `submit` ~61-70, `request_turn`/`request_turn_back` ~77-84, `update` ~91-114, `_process_turn` ~145-214, `reset` ~86-89)
- Test: `tests/unit/test_bridge_character_anim_complete.py`

**Interfaces:**
- Consumes: existing `capture_registered_clip(character, suffix)`, `capture_chair_clip(character, suffix)`, `_body_turns_officer`, `submit`, `_node_ctrl`.
- Produces:
  - `BridgeCharacterAnimController.submit(character, clips, priority, hold=False, on_complete=None)` — `on_complete` (a 0-arg callable or `None`) fires exactly once when the action's last clip ends.
  - `BridgeCharacterAnimController.request_turn_to(character, detail, *, back=False, hold=True, now=False, on_complete=None)` — queued; drained in `update`. Turns `character` toward `detail` (suffix `"Turn"+detail`) or reverses (`"Back"+detail`), reusing body+chair coupling. Fires `on_complete` once: via the body `_Action` on settle/hold, or **inline** when chair-driven / `now` / nothing resolves.
  - `request_turn`/`request_turn_back(character)` unchanged externally (now delegate to `request_turn_to(character, "Captain", …)`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_character_anim_complete.py`:

```python
from engine.bridge_character_anim import BridgeCharacterAnimController
from engine.appc import bridge_placement


class _FakeRenderer:
    def __init__(self, clip_dur=1.0):
        self._next = 10
        self._dur = clip_dur
        self.gestures = []
        self.idled = []
        self.restored = []
    def load_instance_clip(self, iid, path):
        self._next += 1
        return self._next
    def play_instance_gesture(self, iid, ci):
        self.gestures.append((iid, ci))
    def play_instance_idle(self, iid, ci):
        self.idled.append((iid, ci))
    def restore_rest_pose(self, iid):
        self.restored.append(iid)
    def load_animation_clips(self, path):
        # Non-empty + a rotation track => _body_turns_officer -> body-driven.
        return [{"duration": self._dur,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _EmptyBodyRenderer(_FakeRenderer):
    def load_animation_clips(self, path):
        return []                       # empty clip => chair-driven officer


class _Char:
    def __init__(self, iid=77, name="Picard", loc="DBGuest"):
        self._render_instance = iid
        self._name = name
        self._location = loc
    def GetCharacterName(self):
        return self._name
    def GetLocation(self):
        return self._location
    def IsHidden(self):
        return 0


def _patch_clips(monkeypatch, chair=None):
    import engine.bridge_character_anim as m
    monkeypatch.setattr(m, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": suffix + ".nif"})
    monkeypatch.setattr(m, "capture_chair_clip", lambda ch, suffix: chair)


def test_submit_on_complete_fires_once_on_settle(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.submit(ch, [("clip.nif", 0.0)], priority=1,
                on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # start clip 0
    ctrl.update(2.0, renderer=r)        # elapsed >= dur -> settle
    assert fired == [True]
    ctrl.update(0.1, renderer=r)        # no double-fire (action popped)
    assert fired == [True]


def test_submit_without_on_complete_is_unchanged(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    ctrl.submit(ch, [("clip.nif", 0.0)], priority=1)   # no on_complete
    ctrl.update(0.0, renderer=r)
    ctrl.update(2.0, renderer=r)                        # settles, returns to rest
    assert r.restored == [77]                           # menu-path behaviour intact


def test_request_turn_to_body_driven_defers_then_completes(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # drain -> submit body clip (hold=True)
    assert fired == []                  # deferred
    ctrl.update(2.0, renderer=r)        # hold-point reached
    assert fired == [True]


def test_request_turn_to_chair_driven_completes_inline(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _EmptyBodyRenderer()            # empty body clip => chair-driven
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # no body _Action -> inline completion
    assert fired == [True]


def test_request_turn_to_now_completes_inline(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", now=True,
                         on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # now -> inline, does not wait for settle
    assert fired == [True]


def test_request_turn_back_delegates(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    ctrl.request_turn_back(ch)          # menu path, no on_complete
    ctrl.update(0.0, renderer=r)        # must not raise; drains cleanly
    ctrl.update(2.0, renderer=r)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_bridge_character_anim_complete.py -v
```
Expected: FAIL — `request_turn_to` does not exist / `submit` has no `on_complete`.

- [ ] **Step 3: Add `on_complete` to `_Action` and `submit`**

In `engine/bridge_character_anim.py`, update `_Action.__slots__`/`__init__`:

```python
class _Action:
    __slots__ = ("iid", "clips", "priority", "index", "elapsed", "started",
                 "cur_duration", "hold", "on_complete")

    def __init__(self, iid, clips, priority, hold=False, on_complete=None):
        self.iid = iid
        self.clips = clips          # [(nif_path, sdk_duration), ...]
        self.priority = priority
        self.index = -1             # current clip; -1 = not yet started
        self.elapsed = 0.0
        self.started = False
        self.cur_duration = 0.0     # effective hold for the current clip
        self.hold = hold
        self.on_complete = on_complete   # fired once when the last clip ends
```

Update `submit`:

```python
    def submit(self, character, clips, priority, hold=False,
               on_complete=None) -> None:
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clips:
            return
        if character.IsHidden():
            return
        cur = self._active.get(iid)
        if cur is not None and priority <= cur.priority:
            return                  # don't preempt equal/higher priority
        self._active[iid] = _Action(iid, list(clips), priority, hold, on_complete)
```

- [ ] **Step 4: Fire `on_complete` in `update`**

Replace the `else` branch inside `update`'s per-action loop (the "last clip ended" case, ~107-112):

```python
            else:
                if not act.hold:
                    self._return_to_default(renderer, iid)
                # hold=True leaves the native renderer holding the last frame
                # (the turned-to-captain pose) until the reverse turn replaces it.
                if act.on_complete is not None:
                    try:
                        act.on_complete()
                    except Exception:
                        pass
                done.append(iid)
```

- [ ] **Step 5: Add `_pending_turns` richer entries + `request_turn_to`, refactor the menu callers**

Replace `request_turn` / `request_turn_back` (~77-84) and the pending-drain in `update` (~92-95):

```python
    def request_turn(self, character) -> None:
        """Queue a turn-to-captain (drained on the next update, which has the
        renderer). Called from CharacterClass.MenuUp via the registry."""
        self.request_turn_to(character, "Captain", back=False, hold=True)

    def request_turn_back(self, character) -> None:
        """Queue a turn-back-to-normal (CharacterClass.MenuDown)."""
        self.request_turn_to(character, "Captain", back=True, hold=True)

    def request_turn_to(self, character, detail, *, back=False, hold=True,
                        now=False, on_complete=None) -> None:
        """Queue a body turn toward `detail` (SDK AT_TURN / AT_TURN_BACK). Suffix
        is "Turn"+detail (or "Back"+detail); reuses the menu turn's body+chair
        coupling. on_complete fires once when the turn settles/holds, or inline
        when chair-driven / now / unresolved."""
        self._pending_turns.append(
            (character, str(detail), bool(back), bool(hold), bool(now),
             on_complete))
```

Update the drain at the top of `update`:

```python
        if self._pending_turns:
            pending, self._pending_turns = self._pending_turns, []
            for entry in pending:
                self._process_turn(renderer, *entry)
```

- [ ] **Step 6: Generalize `_process_turn`**

Replace `_process_turn` (~145-214) with the parameterized version (suffix from `detail`, single-fire `on_complete`):

```python
    def _process_turn(self, renderer, character, detail, back, hold, now,
                      on_complete) -> None:
        """Turn `character` toward `detail` (body clip + chair). Suffix
        "Turn"+detail forward, "Back"+detail reverse. Fires on_complete exactly
        once — via the submitted body _Action for a body-driven, non-`now` turn,
        else inline (chair-driven / now / unresolved) so completion is
        guaranteed."""
        turn_suffix = "Turn" + detail
        back_suffix = "Back" + detail

        def _fire_inline():
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    pass

        iid = getattr(character, "_render_instance", None)
        if iid is None:
            _fire_inline()
            return
        # A turn must always take effect: evict any in-flight transient so the
        # new turn is never dropped by submit's equal-priority guard.
        self._active.pop(iid, None)
        # Body-driven vs chair-driven is decided from the FORWARD body clip
        # (BC's per-station asymmetry): Helm rotates Bip01 ~72deg (body-driven);
        # Tactical's clip is EMPTY (chair-driven). Compute once, use for both
        # directions.
        chair_driven = not self._body_turns_officer(
            renderer, capture_registered_clip(character, turn_suffix))
        # The body _Action carries on_complete only for a body-driven, non-`now`
        # turn; every other path fires inline below (avoids double-fire).
        action_cb = None if now else on_complete
        body_submitted = False
        if not back:
            move = capture_registered_clip(character, turn_suffix)
            if move and not chair_driven:
                self.submit(character,
                            [(self._resolve(move["clip_nif"]), 0.0)],
                            priority=_TURN, hold=hold, on_complete=action_cb)
                body_submitted = True
        else:
            # Turn back: restore normal breathing as the default, then play the
            # reverse turn, which returns to that idle on completion.
            idle = capture_registered_clip(character, "Breathe")
            if idle:
                idx = renderer.load_instance_clip(
                    iid, self._resolve(idle["clip_nif"]))
                if idx is not None and idx >= 0:
                    self.set_idle(iid, idx)
            move = capture_registered_clip(character, back_suffix)
            if move and not chair_driven:
                self.submit(character,
                            [(self._resolve(move["clip_nif"]), 0.0)],
                            priority=_TURN, hold=False, on_complete=action_cb)
                body_submitted = True
        # Chair half: rotate the seat (always) + couple the officer only when
        # chair-driven. Standing officers have no chair action -> no-op.
        node_ctrl = getattr(self, "_node_ctrl", None)
        if node_ctrl is not None:
            chair = capture_chair_clip(character, turn_suffix if not back
                                       else back_suffix)
            if not back:
                node_ctrl.turn_chair(character, chair, renderer=renderer,
                                     couple=chair_driven)
            else:
                node_ctrl.unturn_chair(character, chair, renderer=renderer)
        # Guarantee completion: body-driven non-`now` turns complete when the
        # _Action settles; everything else completes now.
        if now or not body_submitted:
            _fire_inline()
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/unit/test_bridge_character_anim_complete.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 8: Run the existing bridge-anim / menu-turn regressions**

```bash
uv run pytest tests/unit -k "bridge_character_anim or menu_turn or turn_captain or bridge_node" -v 2>&1 | tail -25
```
Expected: PASS (menu turn-to-captain behaviour preserved by the delegation).

- [ ] **Step 9: Commit**

```bash
git add engine/bridge_character_anim.py tests/unit/test_bridge_character_anim_complete.py
git commit -m "feat(orientation): generalize turn controller (request_turn_to + on_complete)"
```

---

## Task 2: `CharacterAction` dispatch — `AT_TURN` family

**Files:**
- Modify: `engine/appc/ai.py` (`CharacterAction.Play` ~1191-1221; add `_queue_turn`)
- Test: `tests/unit/test_character_action_turn.py`

**Interfaces:**
- Consumes: `bridge_character_anim.get_controller()`, `BridgeCharacterAnimController.request_turn_to` (Task 1), `characters.CharacterClass_Cast`.
- Produces: `CharacterAction.Play()` behaviour — `AT_TURN`/`AT_TURN_NOW` and `AT_TURN_BACK`/`AT_TURN_BACK_NOW` queue a turn. Non-`NOW` defers `Completed()` to the controller; `_NOW` completes inline. `cc._last_turn_detail` records the last forward turn so bare `AT_TURN_BACK` reverses it (default `"Captain"`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_action_turn.py`:

```python
from engine.appc.ai import CharacterAction
import engine.bridge_character_anim as bca


class _Char:
    def __init__(self, name="Picard"):
        self._name = name
    def GetCharacterName(self):
        return self._name


class _RecordingTurnController:
    def __init__(self):
        self.calls = []
    def request_turn_to(self, character, detail, *, back=False, hold=True,
                        now=False, on_complete=None):
        self.calls.append(dict(character=character, detail=detail, back=back,
                               now=now, on_complete=on_complete))


def _patch(monkeypatch, ctrl):
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)


def test_at_turn_queues_and_defers(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is True                     # deferred
    assert len(ctrl.calls) == 1
    c = ctrl.calls[0]
    assert (c["detail"], c["back"], c["now"]) == ("Captain", False, False)
    assert ch._last_turn_detail == "Captain"
    c["on_complete"]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_turn_now_completes_inline(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_TURN_NOW, "C1")
    act.Play()
    assert act.IsPlaying() is False                    # _NOW: inline
    assert ctrl.calls[0]["now"] is True
    assert ctrl.calls[0]["on_complete"] is None        # completion not deferred


def test_at_turn_back_reverses_last_detail(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_TURN, "Science").Play()
    back = CharacterAction(ch, CharacterAction.AT_TURN_BACK)  # bare
    back.Play()
    assert ctrl.calls[1]["detail"] == "Science"
    assert ctrl.calls[1]["back"] is True


def test_at_turn_back_defaults_to_captain(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_TURN_BACK).Play()  # no prior turn
    assert ctrl.calls[0]["detail"] == "Captain"


def test_at_turn_completes_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bca, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is False                    # never stalls
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_character_action_turn.py -v
```
Expected: FAIL — `AT_TURN` currently falls through to the inline no-op (no `request_turn_to` call; `_last_turn_detail` unset).

- [ ] **Step 3: Add the dispatch branch + `_queue_turn`**

In `engine/appc/ai.py`, inside `Play()`, add before the `# Speak types` fallthrough (after the `AT_WATCH_ME`/`AT_STOP_WATCHING_ME` block ~1218):

```python
        if at in (self.AT_TURN, self.AT_TURN_NOW,
                  self.AT_TURN_BACK, self.AT_TURN_BACK_NOW):
            self._queue_turn(
                back=at in (self.AT_TURN_BACK, self.AT_TURN_BACK_NOW),
                now=at in (self.AT_TURN_NOW, self.AT_TURN_BACK_NOW))
            return
```

Add the helper next to `_queue_move`:

```python
    def _queue_turn(self, *, back: bool, now: bool) -> None:
        # Turn (AT_TURN/AT_TURN_BACK, + _NOW). Non-`now` completes when the turn
        # controller settles (deferred, faithful to BC); `now` completes inline.
        # Best-effort: Play() must never raise — any failure completes inline so
        # the mission TGSequence advances instead of stalling.
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None:
                self.Completed()
                return
            if back:
                detail = getattr(cc, "_last_turn_detail", None) or "Captain"
                try:
                    cc._last_turn_detail = None
                except Exception:
                    pass
            else:
                detail = str(self._detail) if self._detail is not None else "Captain"
                try:
                    cc._last_turn_detail = detail
                except Exception:
                    pass
            if now:
                ctrl.request_turn_to(cc, detail, back=back, now=True,
                                     on_complete=None)
                self.Completed()
            else:
                ctrl.request_turn_to(cc, detail, back=back, now=False,
                                     on_complete=self.Completed)
        except Exception:
            self.Completed()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_character_action_turn.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_turn.py
git commit -m "feat(orientation): CharacterAction AT_TURN/AT_TURN_BACK(+_NOW) dispatch"
```

---

## Task 3: `AT_GLANCE_AT` / `AT_GLANCE_AWAY` (best-effort)

**Files:**
- Modify: `engine/bridge_character_anim.py` (add `request_glance` + `_pending_glances`)
- Modify: `engine/appc/ai.py` (`Play` glance branch; add `_queue_glance`)
- Test: `tests/unit/test_character_action_glance.py`

**Interfaces:**
- Consumes: `capture_registered_clip(character, "Glance"+detail)`, `submit` (Task 1).
- Produces: `BridgeCharacterAnimController.request_glance(character, detail, on_complete=None)` — queued; on drain, resolves `"Glance"+detail` and submits it as a React-band transient with `on_complete`, or fires `on_complete` inline if unresolved. `CharacterAction.Play()` dispatches `AT_GLANCE_AT`/`AT_GLANCE_AWAY` through it.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_action_glance.py`:

```python
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_anim as bca


class _Char:
    def __init__(self):
        self._render_instance = 55
    def GetCharacterName(self):
        return "Liu"
    def IsHidden(self):
        return 0


class _RecordingGlanceController:
    def __init__(self):
        self.calls = []
    def request_glance(self, character, detail, on_complete=None):
        self.calls.append((detail, on_complete))


def test_at_glance_at_queues(monkeypatch):
    ch = _Char()
    ctrl = _RecordingGlanceController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AT, "Left")
    act.Play()
    assert ctrl.calls[0][0] == "Left"
    assert act.IsPlaying() is True
    ctrl.calls[0][1]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_glance_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bca, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AWAY)
    act.Play()
    assert act.IsPlaying() is False


def test_request_glance_inline_when_unresolved(monkeypatch):
    import engine.bridge_character_anim as m
    monkeypatch.setattr(m, "capture_registered_clip", lambda ch, suffix: None)
    ctrl = bca.BridgeCharacterAnimController()

    class _R:  # renderer unused on the unresolved path
        pass
    ch = _Char()
    fired = []
    ctrl.request_glance(ch, "Left", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=_R())
    assert fired == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_character_action_glance.py -v
```
Expected: FAIL — no glance dispatch / `request_glance`.

- [ ] **Step 3: Add `request_glance` + `_pending_glances` to the controller**

In `engine/bridge_character_anim.py` `__init__`, add the queue next to `_pending_turns`:

```python
        self._pending_glances = []  # [(character, detail, on_complete), ...]
```

In `reset`, clear it:

```python
    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
        self._pending_turns = []
        self._pending_glances = []
```

Add the drain at the top of `update`, right after the `_pending_turns` drain:

```python
        if self._pending_glances:
            pending, self._pending_glances = self._pending_glances, []
            for character, detail, on_complete in pending:
                self._process_glance(renderer, character, detail, on_complete)
```

Add the methods (after `request_turn_to`):

```python
    def request_glance(self, character, detail, on_complete=None) -> None:
        """Queue a quick head/upper-body glance (SDK AT_GLANCE_AT/AWAY). Resolves
        "Glance"+detail; a graceful inline no-op if unregistered (niche action)."""
        self._pending_glances.append((character, str(detail), on_complete))

    def _process_glance(self, renderer, character, detail, on_complete) -> None:
        clip = capture_registered_clip(character, "Glance" + detail)
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clip:
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    pass
            return
        self.submit(character, [(self._resolve(clip["clip_nif"]), 0.0)],
                    priority=_REACTION, on_complete=on_complete)
```

- [ ] **Step 4: Add the glance dispatch in `ai.py`**

In `Play()`, after the `AT_TURN` block:

```python
        if at in (self.AT_GLANCE_AT, self.AT_GLANCE_AWAY):
            self._queue_glance()
            return
```

Add the helper after `_queue_turn`:

```python
    def _queue_glance(self) -> None:
        # Quick glance (AT_GLANCE_AT/AWAY). Best-effort: completes inline on any
        # failure so the sequence never stalls. Detail "Away" when bare.
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_anim
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_character_anim.get_controller()
            if cc is None or ctrl is None:
                self.Completed()
                return
            detail = str(self._detail) if self._detail is not None else "Away"
            ctrl.request_glance(cc, detail, on_complete=self.Completed)
        except Exception:
            self.Completed()
```

- [ ] **Step 5: Run tests + the anim regressions**

```bash
uv run pytest tests/unit/test_character_action_glance.py tests/unit/test_bridge_character_anim_complete.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/bridge_character_anim.py engine/appc/ai.py tests/unit/test_character_action_glance.py
git commit -m "feat(orientation): AT_GLANCE_AT/AWAY best-effort dispatch"
```

---

## Task 4: `BridgeCameraWatchController` (new)

**Files:**
- Create: `engine/bridge_camera_watch.py`
- Test: `tests/unit/test_bridge_camera_watch.py`

**Interfaces:**
- Produces:
  - `BridgeCameraWatchController()` with `watch(character, snap=False)`, `clear()`, `is_watching() -> bool`, `resolve_target_world(renderer) -> tuple|None`, `consume_snap() -> bool`, `reset()`.
  - module singletons `get_controller()`, `set_controller(ctrl)`, `clear_controller()`.
- Consumes: `renderer.get_instance_head_center(iid)` (via the passed renderer).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_camera_watch.py`:

```python
from engine.bridge_camera_watch import BridgeCameraWatchController


class _R:
    def __init__(self, center=(1.0, 2.0, 3.0)):
        self._c = center
        self.asked = []
    def get_instance_head_center(self, iid):
        self.asked.append(iid)
        return self._c


class _Char:
    def __init__(self, iid=42):
        self._render_instance = iid


def test_watch_resolves_head_center():
    ctrl = BridgeCameraWatchController()
    r = _R((5.0, 6.0, 7.0))
    ch = _Char(iid=42)
    ctrl.watch(ch)
    assert ctrl.is_watching() is True
    assert ctrl.resolve_target_world(r) == (5.0, 6.0, 7.0)
    assert r.asked == [42]


def test_clear_stops_watching():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char())
    ctrl.clear()
    assert ctrl.is_watching() is False
    assert ctrl.resolve_target_world(_R()) is None


def test_unrealized_character_resolves_none():
    ctrl = BridgeCameraWatchController()
    ch = _Char(iid=None)
    ctrl.watch(ch)
    assert ctrl.resolve_target_world(_R()) is None      # no instance yet


def test_snap_consumed_once():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char(), snap=True)
    assert ctrl.consume_snap() is True
    assert ctrl.consume_snap() is False                 # one-shot


def test_watch_supersedes_target():
    ctrl = BridgeCameraWatchController()
    a, b = _Char(1), _Char(2)
    ctrl.watch(a)
    ctrl.watch(b)
    r = _R()
    ctrl.resolve_target_world(r)
    assert r.asked == [2]                               # latest wins


def test_reset_clears():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char(), snap=True)
    ctrl.reset()
    assert ctrl.is_watching() is False
    assert ctrl.consume_snap() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_bridge_camera_watch.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'engine.bridge_camera_watch'`).

- [ ] **Step 3: Implement the controller**

`engine/bridge_camera_watch.py`:

```python
# engine/bridge_camera_watch.py
"""BridgeCameraWatchController — the AT_WATCH_ME / AT_LOOK_AT_ME camera-framing
target.

BC's AT_WATCH_ME / AT_STOP_WATCHING_ME / AT_LOOK_AT_ME(_NOW) do NOT turn the
character — they aim the first-person captain's-eye bridge camera AT the named
character ("watch ME" = the camera watches me). This controller holds the
currently-watched CharacterClass; the host resolves its head-centre each bridge
frame and feeds it to the bridge camera's look-at spring (above the crew-menu
zoom, below a baked cutscene camera path).
"""


class BridgeCameraWatchController:
    def __init__(self):
        self._watched = None
        self._snap_pending = False

    def watch(self, character, snap=False) -> None:
        """Frame `character` (AT_WATCH_ME / AT_LOOK_AT_ME). snap=True (AT_..._NOW)
        jumps the camera instead of easing. Supersedes any prior target."""
        self._watched = character
        if snap:
            self._snap_pending = True

    def clear(self) -> None:
        """Stop framing (AT_STOP_WATCHING_ME)."""
        self._watched = None
        self._snap_pending = False

    def is_watching(self) -> bool:
        return self._watched is not None

    def resolve_target_world(self, renderer):
        """World-space head-centre of the watched character, or None (nothing
        watched / not yet realized / no renderer)."""
        ch = self._watched
        if ch is None:
            return None
        iid = getattr(ch, "_render_instance", None)
        if iid is None:
            return None
        try:
            c = renderer.get_instance_head_center(iid)
        except Exception:
            return None
        if not c:
            return None
        return (c[0], c[1], c[2])

    def consume_snap(self) -> bool:
        """Return True once after a snap (AT_..._NOW) set; then reset."""
        s = self._snap_pending
        self._snap_pending = False
        return s

    def reset(self) -> None:
        self._watched = None
        self._snap_pending = False


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_bridge_camera_watch.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_camera_watch.py tests/unit/test_bridge_camera_watch.py
git commit -m "feat(orientation): BridgeCameraWatchController (watch/look camera target)"
```

---

## Task 5: `_BridgeCamera` snap + `_resolve_bridge_focus_world`

**Files:**
- Modify: `engine/host_loop.py` (`_BridgeCamera.set_zoom_target` ~2196; add module-level `_resolve_bridge_focus_world` near `_active_zoom_officer_world` ~2291)
- Test: `tests/unit/test_bridge_focus_resolver.py`

**Interfaces:**
- Consumes: `_active_zoom_officer_world(crew_menu_panel, r)` (existing), `BridgeCameraWatchController.resolve_target_world`.
- Produces:
  - `_BridgeCamera.set_zoom_target(world_xyz, dt, snap=False)` — `snap=True` with a non-None target jumps `_zoom_t` to 1.0 immediately (AT_LOOK_AT_ME_NOW); otherwise the existing ease.
  - `_resolve_bridge_focus_world(watch_ctrl, crew_menu_panel, r) -> tuple|None` — the watched character's head-centre if one is set, else the crew-menu zoom target, else None (free-look).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_focus_resolver.py`:

```python
import engine.host_loop as HL


class _WatchCtrl:
    def __init__(self, target):
        self._t = target
    def resolve_target_world(self, r):
        return self._t


def test_watch_target_wins(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world",
                        lambda panel, r: (9.0, 9.0, 9.0))
    got = HL._resolve_bridge_focus_world(_WatchCtrl((1.0, 2.0, 3.0)), None, None)
    assert got == (1.0, 2.0, 3.0)                       # watch over menu-zoom


def test_menu_zoom_when_no_watch(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world",
                        lambda panel, r: (4.0, 5.0, 6.0))
    got = HL._resolve_bridge_focus_world(_WatchCtrl(None), None, None)
    assert got == (4.0, 5.0, 6.0)


def test_none_when_neither(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world", lambda panel, r: None)
    assert HL._resolve_bridge_focus_world(_WatchCtrl(None), None, None) is None
    assert HL._resolve_bridge_focus_world(None, None, None) is None   # no ctrl


def test_set_zoom_target_snap_jumps_to_one():
    cam = HL._BridgeCamera()
    cam.set_zoom_target((1.0, 2.0, 3.0), 0.016, snap=True)
    assert cam._zoom_t == 1.0
    assert cam._zoom_active is True
    assert cam._zoom_target_world == (1.0, 2.0, 3.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_bridge_focus_resolver.py -v
```
Expected: FAIL — `_resolve_bridge_focus_world` missing; `set_zoom_target` has no `snap`.

- [ ] **Step 3: Add `snap` to `set_zoom_target`**

In `engine/host_loop.py`, update `_BridgeCamera.set_zoom_target` (~2196). Add the `snap` param and an early snap path; keep the existing ease body otherwise:

```python
    def set_zoom_target(self, world_xyz, dt: float, snap: bool = False) -> None:
        """Select (world_xyz != None) or deselect (None) an officer to zoom
        onto; advance the ease by dt at rate 1/zoom_time, clamped to [0, 1].
        snap=True jumps straight to fully-framed (AT_LOOK_AT_ME_NOW).
        Mouse-look is suspended whenever a zoom is in progress (see apply)."""
        self._zoom_active = world_xyz is not None
        if world_xyz is not None:
            self._zoom_target_world = world_xyz
            if snap:
                self._zoom_t = 1.0        # AT_LOOK_AT_ME_NOW: jump, don't ease
                return
        step = dt / max(_BRIDGE_ZOOM_TIME, 1e-6)
        if self._zoom_active:
            self._zoom_t = min(1.0, self._zoom_t + step)
        else:
            self._zoom_t = max(0.0, self._zoom_t - step)
            if self._zoom_t == 0.0:
                self._zoom_target_world = None
```

(This is the current body verbatim with only the `snap` param + early-return added; `_BRIDGE_ZOOM_TIME`, `_zoom_t`, `_zoom_active`, `_zoom_target_world` are the real names — preserve them.)

- [ ] **Step 4: Add the focus resolver**

After `_active_zoom_officer_world` (~2316), add:

```python
def _resolve_bridge_focus_world(watch_ctrl, crew_menu_panel, r):
    """The world point the captain's-eye camera should frame this bridge frame,
    or None (free-look). Precedence: an AT_WATCH_ME / AT_LOOK_AT_ME target (the
    watched character's head-centre) over the crew-menu zoom-to-officer. A baked
    cutscene camera path is handled separately (set_anim_pose) and outranks both."""
    if watch_ctrl is not None:
        w = watch_ctrl.resolve_target_world(r)
        if w is not None:
            return w
    return _active_zoom_officer_world(crew_menu_panel, r)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_bridge_focus_resolver.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_focus_resolver.py
git commit -m "feat(orientation): bridge camera snap + watch/menu focus resolver"
```

---

## Task 6: `CharacterAction` dispatch — camera-framing family

**Files:**
- Modify: `engine/appc/ai.py` (`Play` `AT_WATCH_ME`/`AT_STOP_WATCHING_ME` branch ~1212-1218; replace `_set_watch` ~1244-1254)
- Test: `tests/unit/test_character_action_watch.py`

**Interfaces:**
- Consumes: `bridge_camera_watch.get_controller()`, `BridgeCameraWatchController.watch`/`clear`, `characters.CharacterClass_Cast`.
- Produces: `CharacterAction.Play()` — `AT_WATCH_ME`/`AT_LOOK_AT_ME` set the watch target (ease); `AT_LOOK_AT_ME_NOW` sets it with snap; `AT_STOP_WATCHING_ME` clears it. All complete inline. The old `CS_TURNED` mapping is removed.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_action_watch.py`:

```python
from engine.appc.ai import CharacterAction
import engine.bridge_camera_watch as bcw


class _Char:
    def GetCharacterName(self):
        return "Picard"


class _RecordingWatch:
    def __init__(self):
        self.watched = []
        self.cleared = 0
    def watch(self, character, snap=False):
        self.watched.append((character, snap))
    def clear(self):
        self.cleared += 1


def _patch(monkeypatch, ctrl):
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)


def test_watch_me_sets_target_and_completes(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert ctrl.watched == [(ch, False)]
    assert act.IsPlaying() is False                     # inline


def test_look_at_me_now_snaps(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_LOOK_AT_ME_NOW).Play()
    assert ctrl.watched == [(ch, True)]


def test_look_at_me_eases(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_LOOK_AT_ME).Play()
    assert ctrl.watched == [(ch, False)]


def test_stop_watching_clears(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_STOP_WATCHING_ME)
    act.Play()
    assert ctrl.cleared == 1
    assert act.IsPlaying() is False


def test_watch_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bcw, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert act.IsPlaying() is False                     # never stalls
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_character_action_watch.py -v
```
Expected: FAIL — `AT_LOOK_AT_ME*` are no-ops; `AT_WATCH_ME` calls `SetStatus`, not the watch controller.

- [ ] **Step 3: Replace the dispatch branch + `_set_watch`**

In `engine/appc/ai.py` `Play()`, replace the `AT_WATCH_ME`/`AT_STOP_WATCHING_ME` block (~1212-1218):

```python
        # Camera framing (AT_WATCH_ME / AT_LOOK_AT_ME[_NOW]) aims the captain's-eye
        # bridge camera AT this character; AT_STOP_WATCHING_ME releases it. All
        # complete inline — the camera eases underneath while the scene proceeds.
        if at in (self.AT_WATCH_ME, self.AT_LOOK_AT_ME, self.AT_LOOK_AT_ME_NOW):
            self._set_camera_watch(snap=(at == self.AT_LOOK_AT_ME_NOW))
            self.Completed()
            return
        if at == self.AT_STOP_WATCHING_ME:
            self._clear_camera_watch()
            self.Completed()
            return
```

Replace `_set_watch` (~1244-1254) with:

```python
    def _set_camera_watch(self, *, snap: bool) -> None:
        # Frame this character with the captain's-eye camera (AT_WATCH_ME /
        # AT_LOOK_AT_ME[_NOW]). Best-effort: never raises out of Play().
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_camera_watch
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            ctrl = bridge_camera_watch.get_controller()
            if cc is not None and ctrl is not None:
                ctrl.watch(cc, snap=snap)
        except Exception:
            pass

    def _clear_camera_watch(self) -> None:
        from engine import bridge_camera_watch
        try:
            ctrl = bridge_camera_watch.get_controller()
            if ctrl is not None:
                ctrl.clear()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_character_action_watch.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Grep for other `_set_watch` / `CS_TURNED` callers (make sure nothing else depended on it)**

```bash
grep -rn "_set_watch\|CS_TURNED" engine/ tests/
```
Expected: no remaining references in `engine/appc/ai.py` to `_set_watch`; if a test asserted the old `CS_TURNED` behaviour, update it to the camera-watch behaviour (the mapping was the placeholder bug this task fixes).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_watch.py
git commit -m "feat(orientation): AT_WATCH_ME/LOOK_AT_ME(_NOW)/STOP camera framing dispatch"
```

---

## Task 7: Host wiring — construct, reset, and drive the watch target

**Files:**
- Modify: `engine/host_loop.py` (construct watch ctrl ~4943; reset ~5721; camera call site ~6150)
- Test: `tests/unit/test_watch_ctrl_wiring.py`

**Interfaces:**
- Consumes: `BridgeCameraWatchController` (Task 4), `_resolve_bridge_focus_world` + `set_zoom_target(..., snap=)` (Task 5).
- Produces: the watch controller is constructed, registered as the module singleton, reset on mission swap, and its target drives `bridge_camera.set_zoom_target` each bridge frame (with snap for `_NOW`).

- [ ] **Step 1: Write the failing test (singleton lifecycle)**

Wiring inside the giant per-frame loop is not unit-testable, but the construct/reset/singleton contract is. `tests/unit/test_watch_ctrl_wiring.py`:

```python
import inspect
import engine.host_loop as HL
import engine.bridge_camera_watch as bcw


def test_host_loop_constructs_and_wires_watch_controller():
    src = inspect.getsource(HL)
    # Constructed + registered as the singleton alongside the walk controller.
    assert "BridgeCameraWatchController(" in src
    assert "set_watch_ctrl(" in src or "set_controller" in src
    # Reset on mission swap (next to walk_ctrl.reset()).
    assert "watch_ctrl.reset()" in src
    # Drives the camera via the focus resolver (not the raw menu-zoom call).
    assert "_resolve_bridge_focus_world(" in src


def test_watch_singleton_roundtrip():
    ctrl = bcw.BridgeCameraWatchController()
    bcw.set_controller(ctrl)
    assert bcw.get_controller() is ctrl
    bcw.clear_controller()
    assert bcw.get_controller() is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_watch_ctrl_wiring.py -v
```
Expected: FAIL (`BridgeCameraWatchController(` / `_resolve_bridge_focus_world(` / `watch_ctrl.reset()` not yet in `host_loop.py`).

- [ ] **Step 3: Construct + register the watch controller**

In `engine/host_loop.py`, immediately after `set_walk_ctrl(walk_ctrl)` (~4943):

```python
        from engine.bridge_camera_watch import (
            BridgeCameraWatchController, set_controller as set_watch_ctrl,
        )
        watch_ctrl = BridgeCameraWatchController()
        set_watch_ctrl(watch_ctrl)
```

- [ ] **Step 4: Reset on mission swap**

After `walk_ctrl.reset()` (~5721):

```python
                    watch_ctrl.reset()
```

- [ ] **Step 5: Drive the camera from the focus resolver**

Replace the `set_zoom_target` call (~6150-6152):

```python
                        _focus = _resolve_bridge_focus_world(
                            watch_ctrl, crew_menu_panel, r)
                        bridge_camera.set_zoom_target(
                            _focus, _player_dt,
                            snap=watch_ctrl.consume_snap())
```

- [ ] **Step 6: Run the wiring test + full gate**

```bash
uv run pytest tests/unit/test_watch_ctrl_wiring.py -v
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: wiring test PASS; gate green (no new `tests/known_failures.txt` entries).

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_watch_ctrl_wiring.py
git commit -m "feat(orientation): wire watch controller into the bridge camera focus"
```

---

## Task 8: End-to-end headless integration + gate

**Files:**
- Test: `tests/unit/test_orientation_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7. No new production code expected — if a gap shows up, fix it in the owning module (not the test).

- [ ] **Step 1: Write the integration test**

`tests/unit/test_orientation_integration.py`:

```python
"""End-to-end (headless): a turn dispatch flows through the real
BridgeCharacterAnimController to a deferred completion, and a watch dispatch
flows through the real BridgeCameraWatchController to a resolved camera target."""
from engine.appc.ai import CharacterAction
from engine.bridge_character_anim import BridgeCharacterAnimController
import engine.bridge_character_anim as bca
from engine.bridge_camera_watch import BridgeCameraWatchController
import engine.bridge_camera_watch as bcw


class _AnimRenderer:
    def __init__(self):
        self._n = 0
    def load_instance_clip(self, iid, path):
        self._n += 1
        return self._n
    def play_instance_gesture(self, iid, ci):
        pass
    def play_instance_idle(self, iid, ci):
        pass
    def restore_rest_pose(self, iid):
        pass
    def load_animation_clips(self, path):
        return [{"duration": 1.0,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _Char:
    def __init__(self):
        self._render_instance = 88
    def GetCharacterName(self):
        return "Picard"
    def GetLocation(self):
        return "DBGuest"
    def IsHidden(self):
        return 0


def test_turn_dispatch_to_deferred_completion(monkeypatch):
    monkeypatch.setattr(bca, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": suffix + ".nif"})
    monkeypatch.setattr(bca, "capture_chair_clip", lambda ch, suffix: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    ctrl = BridgeCharacterAnimController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    r = _AnimRenderer()
    ch = _Char()

    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is True                 # deferred to the controller
    ctrl.update(0.0, renderer=r)                    # drain -> submit body clip
    assert act.IsPlaying() is True
    ctrl.update(2.0, renderer=r)                    # settle -> Completed()
    assert act.IsPlaying() is False


def test_watch_dispatch_to_camera_target(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    ctrl = BridgeCameraWatchController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    ch = _Char()

    CharacterAction(ch, CharacterAction.AT_WATCH_ME).Play()

    class _R:
        def get_instance_head_center(self, iid):
            return (iid + 0.0, 0.0, 0.0)
    assert ctrl.resolve_target_world(_R()) == (88.0, 0.0, 0.0)

    CharacterAction(ch, CharacterAction.AT_STOP_WATCHING_ME).Play()
    assert ctrl.resolve_target_world(_R()) is None
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/unit/test_orientation_integration.py -v
```
Expected: PASS (2 tests). If either fails, the primitive is not uniform across dispatch→controller — fix in the owning module.

- [ ] **Step 3: Run the full gate**

```bash
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: gate green.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_orientation_integration.py
git commit -m "test(orientation): end-to-end turn + watch dispatch integration"
```

---

## Task 9: GUI verification (manual, final sign-off)

**Files:** none (manual; the render/camera path cannot be asserted headlessly, consistent with prior bridge-character sign-offs).

- [ ] **Step 1: Launch E1M1 and observe the opening + intro**

```bash
./build/dauntless
```
Load E1M1 (dev mission picker if not the default boot). Watch the opening briefing and the crew-intro beats.

- [ ] **Step 2: Verify Family A (turns)**

- On `AT_TURN "Captain"` a seated/standing officer turns to face the captain; on the trailing `AT_TURN_BACK` they return. Seated officers' **chairs** rotate with them (Tactical is chair-driven — confirm it still turns).
- No stuck-facing-captain officer after a turn/back pair; the mission dialogue keeps pace with the turns (deferred completion advancing the sequence).

- [ ] **Step 3: Verify Family B (camera framing)**

- On `AT_WATCH_ME` / `AT_LOOK_AT_ME` the captain's-eye camera holds on the named character as they speak; on `AT_LOOK_AT_ME_NOW` it snaps.
- A baked walk-on **dolly** still overrides the watch framing (baked path outranks watch).
- After the mission, crew-menu zoom-to-officer still works (watch cleared → menu-zoom resumes).

- [ ] **Step 4: Record the result**

Update the memory `project_e1m1_character_walkon.md` (or a new `project_orientation_family.md`) with the merge state and GUI findings. Note that `AT_WATCH_ME` is camera framing (not the `CS_TURNED` head-track the old follow-up list imagined).

- [ ] **Step 5: Finish the branch**

Use `superpowers:finishing-a-development-branch` to decide merge/PR. Carry the remaining follow-ups forward (SP-A robustness bugs, SP-B other-mission sweep, SP-D lift-door ownership, SP-E `AT_MENU_UP`/`DOWN` — which now wire cleanly onto `request_turn_to`).

---

## Self-Review

**Spec coverage:**
- Family A dispatch (`AT_TURN`/`_NOW`/`AT_TURN_BACK`/`_NOW`) → Task 2. ✓
- Family A glance (`AT_GLANCE_AT`/`AWAY`, best-effort) → Task 3. ✓
- Generalized `request_turn_to` + `on_complete` (reuse body+chair coupling) → Task 1. ✓
- `_last_turn_detail` reverse for bare `AT_TURN_BACK` → Task 2. ✓
- Family B watch controller → Task 4. ✓
- Camera snap + focus precedence resolver → Task 5. ✓
- Family B dispatch (`AT_WATCH_ME`/`STOP`/`LOOK_AT_ME`/`_NOW`), remove `CS_TURNED` → Task 6. ✓
- Host wiring (construct/reset/drive) with baked-path > watch > menu-zoom > free-look → Tasks 5, 7. ✓
- Best-effort inline completion everywhere → Tasks 2, 3, 6 (dispatch), 1 (controller). ✓
- Testing (dispatch, controller, resolver, integration, gate, GUI) → Tasks 1-9. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The one soft spot (glance registered key) is handled as an explicit graceful no-op, not a placeholder.

**Type consistency:**
- `request_turn_to(character, detail, *, back, hold, now, on_complete)` — identical in Task 1 (def), Task 2 (call), Task 8 (integration).
- `submit(character, clips, priority, hold=False, on_complete=None)` — Task 1 def; used by `_process_turn`/`_process_glance` (Tasks 1, 3).
- `request_glance(character, detail, on_complete=None)` — Task 3 def + call.
- `watch(character, snap=False)` / `clear()` / `resolve_target_world(renderer)` / `consume_snap()` — Task 4 def; Task 6 dispatch; Tasks 5, 7 host use.
- `set_zoom_target(world_xyz, dt, snap=False)` — Task 5 def; Task 7 call.
- `_resolve_bridge_focus_world(watch_ctrl, crew_menu_panel, r)` — Task 5 def; Task 7 call.
- `cc._last_turn_detail` — written/read consistently in Task 2; default `"Captain"`.
