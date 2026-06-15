# SDK-Driven Bridge Officer Placement (Step 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each SDK-populated bridge officer posed at its station by capturing its placement clip from the SDK's own `CommonAnimations.SetPosition`, then feeding the kept SP1/SP2 skinned renderer.

**Architecture:** Two `engine/appc/` recording surfaces (`g_kAnimationManager` + `TGAnimPosition_Create`) let the host run the real SDK `SetPosition(char)` and read back the clip it selects — no invented location→clip table. A headless `capture_placement` helper returns `{clip_nif, hidden, sample_at_start}`; a host function `_place_bridge_officers` enumerates every `CharacterClass` in the `"bridge"` set and calls the kept `assemble_officer`/`create_bridge_instance`/`set_world_transform`/`set_instance_animation` bindings.

**Tech Stack:** Python 3 (engine + host), pytest (focused subsets only — **never** the full suite; it OOMs the host). No C++/CMake/shader change → no `dauntless` rebuild.

---

## ⚠️ Constraints for every task

- **NEVER run the full pytest suite** (`uv run pytest` with no path) — it uses >100 GB RAM and freezes macOS. Run only the exact focused test files named in each task.
- Work on branch `sdk-driven-bridge-officers-step4` (already created in the main checkout — not a worktree).
- Keep `engine/appc/` headless: no `import _dauntless_host` and no `from engine import renderer` in any `engine/appc/` module.
- Do **not** modify `compose_officer_model` or the SP1/SP2 skinning/pose pipeline.

---

## File Structure

- **Create** `engine/appc/animation_manager.py` — `AnimationManager` recording `name → path` for `LoadAnimation`; registered as `App.g_kAnimationManager`.
- **Modify** `engine/appc/actions.py` — add `TGAnimPosition` action class + `TGAnimPosition_Create` recording factory.
- **Modify** `App.py` — register `g_kAnimationManager` and import/expose `TGAnimPosition`, `TGAnimPosition_Create`.
- **Create** `engine/appc/bridge_placement.py` — `capture_placement(character)` runs SDK `SetPosition` under the recorders and returns the placement dict.
- **Modify** `engine/renderer.py` — add `assemble_officer` + `set_instance_animation` pass-through wrappers.
- **Modify** `engine/host_loop.py` — add `OFFICER_TRANSFORM` constant + `_place_bridge_officers(controller, r)`; call it from `_after_mission_loaded`; refresh the `officer_instances` comment.
- **Create** `tests/unit/test_bridge_placement_capture.py`
- **Create** `tests/unit/test_place_bridge_officers.py`
- **Create** `tests/integration/test_officer_placement_sdk.py`

---

## Task 1: AnimationManager recording surface

**Files:**
- Create: `engine/appc/animation_manager.py`
- Modify: `App.py:575-576` (register `g_kAnimationManager` next to `g_kModelManager`)
- Test: `tests/unit/test_animation_manager.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_animation_manager.py`:

```python
from engine.appc.animation_manager import AnimationManager


def test_load_animation_records_name_to_path():
    m = AnimationManager()
    m.LoadAnimation("data/animations/db_stand_t_l.nif", "db_stand_t_l")
    assert m.path_for("db_stand_t_l") == "data/animations/db_stand_t_l.nif"


def test_path_for_unknown_name_returns_none():
    m = AnimationManager()
    assert m.path_for("nope") is None


def test_reload_same_name_overwrites():
    m = AnimationManager()
    m.LoadAnimation("a.nif", "x")
    m.LoadAnimation("b.nif", "x")
    assert m.path_for("x") == "b.nif"


def test_app_exposes_singleton():
    import App
    assert hasattr(App, "g_kAnimationManager")
    App.g_kAnimationManager.LoadAnimation("data/animations/foo.nif", "foo")
    assert App.g_kAnimationManager.path_for("foo") == "data/animations/foo.nif"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_animation_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.animation_manager` (and the `App` test fails on missing attribute).

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/animation_manager.py`:

```python
"""AnimationManager — App.g_kAnimationManager.

Real (no longer a loud stub), mirroring engine/appc/bridge_set.py::ModelManager:
our renderer loads animation NIFs lazily host-side, so the faithful equivalent
of the SDK's g_kAnimationManager.LoadAnimation is to remember the file path the
SDK registers under each animation NAME. The host reads it back with path_for
when it captures an officer's placement clip (see engine/appc/bridge_placement).

Loads nothing into the renderer itself; pure name -> path bookkeeping.
"""


class AnimationManager:
    def __init__(self) -> None:
        self._paths: dict[str, str] = {}   # animation name -> NIF path

    def LoadAnimation(self, path, name) -> None:
        # SDK call shape: kAM.LoadAnimation("data/animations/db_stand_t_l.nif",
        # "db_stand_t_l"). Record name -> path; re-load of a name overwrites.
        self._paths[str(name)] = str(path)

    def path_for(self, name) -> "str | None":
        return self._paths.get(str(name))
```

- [ ] **Step 4: Register the singleton in App.py**

In `App.py`, add `AnimationManager` to the `bridge_set`-adjacent imports is **not** correct — it lives in its own module. Add a dedicated import near the other `engine.appc` manager imports (after line 133's `lod_models` import is fine), e.g.:

```python
from engine.appc.animation_manager import AnimationManager
```

Then, next to `g_kModelManager = ModelManager()` (currently `App.py:576`), add:

```python
g_kAnimationManager = AnimationManager()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_animation_manager.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/animation_manager.py App.py tests/unit/test_animation_manager.py
git commit -m "feat(bridge): AnimationManager recording surface (g_kAnimationManager)"
```

---

## Task 2: TGAnimPosition recording action + factory

**Files:**
- Modify: `engine/appc/actions.py` (add class + factory near `TGAnimAction`, ~line 411-416)
- Modify: `App.py:103-118` (add `TGAnimPosition, TGAnimPosition_Create` to the `actions` import block)
- Test: `tests/unit/test_tganim_position.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tganim_position.py`:

```python
from engine.appc.actions import (
    TGAnimPosition, TGAnimPosition_Create, TGSequence_Create,
)


def test_factory_records_clip_name():
    node = object()  # SDK passes an anim node; the action only keeps the name
    act = TGAnimPosition_Create(node, "db_stand_t_l")
    assert isinstance(act, TGAnimPosition)
    assert act.name == "db_stand_t_l"


def test_appended_action_is_readable_off_the_sequence():
    seq = TGSequence_Create()
    seq.AppendAction(TGAnimPosition_Create(None, "db_StoL1_S"))
    last = seq.GetAction(seq.GetNumActions() - 1)
    assert last.name == "db_StoL1_S"


def test_app_exposes_factory():
    import App
    act = App.TGAnimPosition_Create(None, "EB_stand_s_s")
    assert act.name == "EB_stand_s_s"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tganim_position.py -v`
Expected: FAIL — `ImportError: cannot import name 'TGAnimPosition'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/actions.py`, immediately after the existing `TGAnimAction` block (the `class TGAnimAction(TGAction): ... def TGAnimAction_Create(*args): return TGAnimAction()` at ~line 411-416), add:

```python
class TGAnimPosition(TGAction):
    """Placement action created by Bridge.Characters.CommonAnimations.SetPosition.

    The SDK builds these via App.TGAnimPosition_Create(animNode, clipName) and
    appends them to a TGSequence to move a character's anim node to the position
    baked into the named clip's keyframes. Headless we never play it — we only
    record the clip NAME so the host can resolve it to a NIF path via
    g_kAnimationManager.path_for and feed it to the skinned renderer.
    """
    def __init__(self, name: str = ""):
        super().__init__()
        self.name = str(name)


def TGAnimPosition_Create(anim_node=None, name: str = "") -> TGAnimPosition:
    # SDK call shape: App.TGAnimPosition_Create(pAnimNode, "db_stand_t_l").
    # The anim node is irrelevant headless; keep only the clip name.
    return TGAnimPosition(name)
```

- [ ] **Step 4: Export from App.py**

In `App.py`, inside the `from engine.appc.actions import (...)` block (currently lines 103-118), add `TGAnimPosition, TGAnimPosition_Create,` to the imported names (e.g. on the line with `TGAnimAction, TGAnimAction_Create,`):

```python
    TGAnimAction, TGAnimAction_Create,
    TGAnimPosition, TGAnimPosition_Create,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tganim_position.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/actions.py App.py tests/unit/test_tganim_position.py
git commit -m "feat(bridge): TGAnimPosition recording action + factory"
```

---

## Task 3: capture_placement helper

**Files:**
- Create: `engine/appc/bridge_placement.py`
- Test: `tests/unit/test_bridge_placement_capture.py`

This runs the real SDK `Bridge.Characters.CommonAnimations.SetPosition(char)`. It depends on Task 1 (`g_kAnimationManager`) and Task 2 (`TGAnimPosition_Create`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_placement_capture.py`:

```python
import App
from engine.appc.bridge_placement import capture_placement


def _char(location):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    return c


def test_in_place_stand_clip_tactical():
    p = capture_placement(_char("DBTactical"))
    assert p["clip_nif"] == "data/animations/db_stand_t_l.nif"
    assert p["hidden"] is False
    assert p["sample_at_start"] is False


def test_helm_and_commander_stand_clips():
    assert capture_placement(_char("DBHelm"))["clip_nif"] == "data/animations/db_stand_h_m.nif"
    assert capture_placement(_char("DBCommander"))["clip_nif"] == "data/animations/db_stand_c_m.nif"


def test_movement_clip_science_samples_at_start():
    p = capture_placement(_char("DBScience"))
    assert p["clip_nif"] == "data/animations/db_StoL1_S.nif"
    assert p["sample_at_start"] is True


def test_movement_clip_engineer_samples_at_start():
    p = capture_placement(_char("DBEngineer"))
    assert p["clip_nif"] == "data/animations/db_EtoL1_s.nif"
    assert p["sample_at_start"] is True


def test_ebridge_science_stand_clip_does_not_sample_at_start():
    # EBridge Science uses an in-place stand clip, NOT a movement clip — the
    # heuristic must key off the clip name, not the station role.
    p = capture_placement(_char("EBScience"))
    assert p["clip_nif"] == "data/animations/EB_stand_s_s.nif"
    assert p["sample_at_start"] is False


def test_l1_moving_location_is_hidden():
    p = capture_placement(_char("DBL1M"))
    assert p is not None
    assert p["hidden"] is True


def test_empty_location_returns_none():
    assert capture_placement(_char("")) is None


def test_unset_location_returns_none():
    assert capture_placement(_char(None)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_placement_capture.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.bridge_placement`.

- [ ] **Step 3: Write minimal implementation**

Create `engine/appc/bridge_placement.py`:

```python
"""capture_placement — read an officer's station placement from the SDK.

The SDK's authoritative station-placement logic is
Bridge/Characters/CommonAnimations.py::SetPosition(pCharacter): a switch on
pCharacter.GetLocation() that, for the matched branch, does

    kAM.LoadAnimation("data/animations/db_stand_t_l.nif", "db_stand_t_l")
    pSequence.AppendAction(App.TGAnimPosition_Create(pAnimNode, "db_stand_t_l"))

and, for the "moving-to-L1" branches, also calls pCharacter.SetHidden(1).

SetPosition is never called from SDK Python — the original C++ engine invokes it
post-load. We invoke the same SDK function to CAPTURE the clip it selects (no
invented location->clip table), the same recording pattern step 3 used for
g_kModelManager.LoadModel -> env_for. The selected clip name is read back from
the TGSequence SetPosition returns; its NIF path comes from
App.g_kAnimationManager.path_for.

Headless: imports SDK Python only (no renderer). SDK is importable via
conftest._SDKFinder (tests) / tools.mission_harness.setup_sdk (live).
"""
import logging

_logger = logging.getLogger(__name__)

# Clip-name fragments whose station end is frame 0: the move-FROM-station clips
# (Science "Station to L1", Engineer "Engineer to L1", and the generic L1
# transitions). Matching clips must be held at frame 0 (sample_at_start=True) so
# the officer reads as standing at the console rather than mid-walk to L1.
# In-place "stand"/"seated" clips contain none of these and play-and-hold.
# Keyed off the SDK's own clip names, not the station role (EBridge Science uses
# an in-place EB_stand_s_s, so it correctly maps to False).
_FRAME0_FRAGMENTS = ("stol1", "etol1", "l1to")


def _samples_at_start(clip_name: str) -> bool:
    low = clip_name.lower()
    return any(frag in low for frag in _FRAME0_FRAGMENTS)


def capture_placement(character):
    """Return the officer's station placement, or None when unplaceable.

    {"clip_nif": <data-root-relative path>, "hidden": bool,
     "sample_at_start": bool}, or None if the character has no location or no
    matching SetPosition branch (nothing to place).
    """
    import App
    import Bridge.Characters.CommonAnimations as _CommonAnim

    seq = _CommonAnim.SetPosition(character)
    # The matched branch appends exactly one TGAnimPosition; an unmatched /
    # empty location appends none.
    if seq is None or seq.GetNumActions() == 0:
        return None
    action = seq.GetAction(seq.GetNumActions() - 1)
    clip_name = getattr(action, "name", "")
    if not clip_name:
        return None

    clip_nif = App.g_kAnimationManager.path_for(clip_name)
    if not clip_nif:
        _logger.warning("capture_placement: no path recorded for clip %r", clip_name)
        return None

    hidden = bool(character.IsHidden())
    return {
        "clip_nif": clip_nif,
        "hidden": hidden,
        "sample_at_start": _samples_at_start(clip_name),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_placement_capture.py -v`
Expected: PASS (8 tests).

If a test errors on `import Bridge.Characters.CommonAnimations`, the SDK path isn't wired in the test process — confirm `tests/conftest.py::_SDKFinder` is active (it is for the existing `tests/integration/test_sdk_bridge_load.py`); run from the repo root so conftest loads.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_bridge_placement_capture.py
git commit -m "feat(bridge): capture_placement reads station clip from SDK SetPosition"
```

---

## Task 4: renderer wrappers for assemble_officer + set_instance_animation

**Files:**
- Modify: `engine/renderer.py` (add two pass-throughs in the bridge-view section, after `create_bridge_instance` at ~line 279)

No unit test: `engine/renderer.py` imports `_dauntless_host` at module top, which is unavailable headless, so it cannot be imported in a focused unit test. These are trivial pass-throughs over already-tested C++ bindings (`assemble_officer`, `set_instance_animation`); they are exercised by the live run and by Task 6's host wiring (which injects a fake renderer in tests). The host calls them as `r.assemble_officer(...)` / `r.set_instance_animation(...)`; without these wrappers those attributes don't exist on the `engine.renderer` module and the live call would `AttributeError`.

- [ ] **Step 1: Add the wrappers**

In `engine/renderer.py`, after the `create_bridge_instance` wrapper (currently ending at line 279), add:

```python
def assemble_officer(body_nif: str, head_nif: str,
                     body_tex=None, head_tex=None,
                     placement_nif=None, sample_at_start: bool = False) -> int:
    """SP3: compose a bridge officer from a body NIF + head NIF (head grafted
    onto the body's 'Bip01 Head' bone), overriding the body/head Base textures,
    and load placement_nif's clip into the composed model's animations[0].
    Returns a ModelHandle. The caller plays the clip via set_instance_animation.
    """
    return _h.assemble_officer(body_nif, head_nif, body_tex, head_tex,
                               placement_nif, sample_at_start)


def set_instance_animation(iid: InstanceId, clip_index: int,
                           loop: bool = False,
                           sample_at_start: bool = False) -> None:
    """SP2: play model.animations[clip_index] on this instance through the GPU
    bone palette. loop=False plays once and holds the last frame;
    sample_at_start holds frame 0 instead (for move-from-station clips)."""
    _h.set_instance_animation(iid, clip_index, loop, sample_at_start)
```

- [ ] **Step 2: Verify the module still imports under the live interpreter (optional sanity)**

This cannot run in the headless test venv. Verification happens in Task 7 (live). If you have a built `_dauntless_host`, you may run `python -c "import engine.renderer"` to confirm no syntax error; otherwise skip.

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(bridge): renderer wrappers for assemble_officer + set_instance_animation"
```

---

## Task 5: _place_bridge_officers host function + wiring

**Files:**
- Modify: `engine/host_loop.py` — add `OFFICER_TRANSFORM` constant; add `_place_bridge_officers(controller, r)` next to `_realize_bridge_model` (~line 2003-2047); call it from `_after_mission_loaded` (~line 2197); refresh the `officer_instances` comment (~line 1752-1758).
- Test: `tests/unit/test_place_bridge_officers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_place_bridge_officers.py`:

```python
import App
from engine.host_loop import _place_bridge_officers, OFFICER_TRANSFORM


class FakeRenderer:
    def __init__(self):
        self.calls = []          # ordered (op, args) log
        self._next_iid = 100
        self.destroyed = []

    def assemble_officer(self, body, head, body_tex, head_tex, placement, sample):
        self.calls.append(("assemble", body, head, body_tex, head_tex, placement, sample))
        return ("model", body)

    def create_bridge_instance(self, model):
        self.calls.append(("create", model))
        iid = self._next_iid
        self._next_iid += 1
        return iid

    def set_world_transform(self, iid, mat4):
        self.calls.append(("xform", iid, tuple(mat4)))

    def set_instance_animation(self, iid, clip_index, loop, sample_at_start):
        self.calls.append(("anim", iid, clip_index, loop, sample_at_start))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class FakeController:
    def __init__(self):
        self.officer_instances = []


def _bridge_with(*characters):
    """Build a fresh 'bridge' set holding the given configured characters."""
    App.g_kSetManager._sets.pop("bridge", None)
    s = App.BridgeSet_Create()                  # registers loud-stub BridgeSet_Create
    App.g_kSetManager.AddSet(s, "bridge")
    for name, loc in characters:
        c = App.CharacterClass_Create(
            "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
            "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
        )
        c.ReplaceBodyAndHead(
            "data/Models/Characters/Bodies/Low/BodyMaleM/FedGold_body.tga",
            "data/Models/Characters/Heads/Low/HeadFelix/felix_head.tga",
        )
        c.SetCharacterName(name)
        c.SetLocation(loc)
        s.AddObjectToSet(c, name)
    return s


def test_places_each_officer_in_order():
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)

    ops = [c[0] for c in r.calls]
    assert ops == ["assemble", "create", "xform", "anim"]
    assemble = r.calls[0]
    assert assemble[1].endswith("BodyMaleL/BodyMaleL.nif")
    assert assemble[5].endswith("db_stand_t_l.nif")        # placement clip
    assert assemble[6] is False                            # sample_at_start
    assert r.calls[2][2] == tuple(OFFICER_TRANSFORM)       # xform matrix
    assert r.calls[3] == ("anim", 100, 0, False, False)    # iid, clip0, no loop
    assert ctrl.officer_instances == [100]


def test_movement_officer_samples_at_start():
    _bridge_with(("Science", "DBScience"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls[0][6] is True                           # assemble sample_at_start
    assert r.calls[3][4] is True                           # anim sample_at_start


def test_hidden_officer_skipped():
    _bridge_with(("Mover", "DBL1M"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls == []
    assert ctrl.officer_instances == []


def test_no_location_skipped():
    _bridge_with(("Idle", ""))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert r.calls == []


def test_enumerates_all_including_guest():
    _bridge_with(("Tactical", "DBTactical"),
                 ("Helm", "DBHelm"),
                 ("Guest", "DBCommander"))   # a non-standard slot name == "guest"
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    assert len(ctrl.officer_instances) == 3


def test_swap_destroys_prior_then_replaces():
    # Load 1: place an officer.
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    first = list(ctrl.officer_instances)
    assert first == [100]

    # Mission swap: production reset_sdk_globals clears g_kSetManager._sets, so
    # the next load enumerates a FRESH (untagged) character in a new set.
    _bridge_with(("Tactical", "DBTactical"))
    r2 = FakeRenderer()
    _place_bridge_officers(ctrl, r2)
    assert r2.destroyed == first                 # prior instance torn down
    assert [c[0] for c in r2.calls] == ["assemble", "create", "xform", "anim"]
    assert ctrl.officer_instances == [100]       # fresh placement on r2


def test_double_call_same_load_does_not_replace():
    # Within ONE load (no set rebuild), the per-character _render_instance tag
    # prevents double-placement if _place_bridge_officers is called twice.
    _bridge_with(("Tactical", "DBTactical"))
    r = FakeRenderer()
    ctrl = FakeController()
    _place_bridge_officers(ctrl, r)
    r2 = FakeRenderer()
    _place_bridge_officers(ctrl, r2)
    assert r2.destroyed == [100]                 # prior torn down
    assert r2.calls == []                        # tagged char not re-placed
    assert ctrl.officer_instances == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_place_bridge_officers.py -v`
Expected: FAIL — `ImportError: cannot import name '_place_bridge_officers'` / `OFFICER_TRANSFORM`.

- [ ] **Step 3: Add the OFFICER_TRANSFORM constant**

In `engine/host_loop.py`, near the other module-level matrix constants (search for `IDENTITY_MAT4`), add:

```python
# Officer instance world transform — the SP2-validated negate-X-basis identity
# (det<0). BC character NIFs are authored in a left-handed model frame; the
# renderer runs glFrontFace(GL_CW) and assumes det<0 world matrices, so plain
# identity would render the body inside-out AND mirrored. Negating the X basis
# axis mirrors the body into the renderer's right-handed world (matching ships)
# and gives the correct station pose. The placement clip's root track carries
# the per-station offset, so NO per-officer translation is set here — officers
# sit in bridge-set identity space like the bridge mesh.
#
# This is the live-tuning anchor: the X-flip assumption lived in the replaced
# placement layer, so re-verify orientation against the real SDK poses with
# Mark and tune this single matrix if needed. Row-major; set_world_transform
# transposes on input.
OFFICER_TRANSFORM = [
    -1.0, 0.0, 0.0, 0.0,
     0.0, 1.0, 0.0, 0.0,
     0.0, 0.0, 1.0, 0.0,
     0.0, 0.0, 0.0, 1.0,
]
```

- [ ] **Step 4: Add `_place_bridge_officers`**

In `engine/host_loop.py`, immediately after `_realize_bridge_model` (after line ~2047), add:

```python
def _place_bridge_officers(controller, r) -> None:
    """Render every SDK-populated bridge officer posed at its station.

    Called from _after_mission_loaded after _realize_bridge_model. Enumerates
    all CharacterClass objects in the SDK-created "bridge" set (5 standard crew
    + 3 random extras + any mission-added guest), captures each one's placement
    clip by running the SDK's own CommonAnimations.SetPosition (see
    engine.appc.bridge_placement.capture_placement — no invented table), and
    feeds the kept SP1/SP2 skinned renderer:
      assemble_officer -> create_bridge_instance -> set_world_transform
                       -> set_instance_animation (play placement clip once/hold).

    Leak-free + idempotent (mirrors _realize_bridge_model): destroys every prior
    officer instance before placing; per-character _render_instance tag prevents
    double-placement within a load. reset_sdk_globals clears g_kSetManager._sets
    each swap, so each load enumerates fresh (untagged) characters and the
    destroy-prior step recycles the previous load's instances.
    """
    import App as _App
    from engine.appc.characters import CharacterClass
    from engine.appc.bridge_placement import capture_placement

    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return

    # Tear down the previous load's officers first.
    for iid in controller.officer_instances:
        try:
            r.destroy_instance(iid)
        except Exception:
            pass
    controller.officer_instances = []

    def _abs(p):
        return str(PROJECT_ROOT / "game" / p) if p else None

    for off in bridge.GetObjectsByType(CharacterClass):
        if getattr(off, "_render_instance", None) is not None:
            continue                                   # already placed this load
        try:
            placement = capture_placement(off)
            if not placement or placement["hidden"]:
                continue
            ap = off.appearance()
            if not ap.get("body_nif"):
                continue

            model = r.assemble_officer(
                _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
                _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
                _abs(placement["clip_nif"]),
                placement["sample_at_start"],
            )
            iid = r.create_bridge_instance(model)
            try:
                r.set_world_transform(iid, OFFICER_TRANSFORM)
                r.set_instance_animation(
                    iid, 0, False, placement["sample_at_start"])
            except Exception:
                try:
                    r.destroy_instance(iid)
                except Exception:
                    pass
                raise
            off._render_instance = iid
            controller.officer_instances.append(iid)
        except Exception:
            name = ""
            try:
                name = off.GetCharacterName()
            except Exception:
                pass
            _log.exception("_place_bridge_officers: failed to place %r", name)
            continue
```

Note: confirm the module's logger name. Search `engine/host_loop.py` for an existing module logger (e.g. `_log = logging.getLogger(__name__)` or `logger = ...`) and use that exact name in the `.exception(...)` call. If none exists, replace the `_log.exception(...)` line with:

```python
            import logging
            logging.getLogger(__name__).exception(
                "_place_bridge_officers: failed to place %r", name)
```

- [ ] **Step 5: Wire into `_after_mission_loaded`**

In `engine/host_loop.py::_after_mission_loaded` (~line 2197), add the call immediately after the existing `_realize_bridge_model(controller, r)`:

```python
            _realize_bridge_model(controller, r)
            _place_bridge_officers(controller, r)
```

- [ ] **Step 6: Refresh the stale `officer_instances` comment**

In the controller constructor (~line 1752-1758), replace the comment that says officer placement "is not wired in this build; kept as an empty list for compatibility" with:

```python
        # InstanceIds of placed-and-posed bridge officers. Owned by the
        # controller (like bridge_instance) so it survives mission swaps;
        # repopulated each load by _place_bridge_officers, which destroys the
        # prior load's instances first.
        self.officer_instances: list = []
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_place_bridge_officers.py -v`
Expected: PASS (7 tests).

If `test_idempotent_destroys_prior_then_replaces` fails because `App.g_kSetManager` lacks `AddSet`, check `engine/appc/sets.py` for the real registration method name (likely `AddSet` or `_sets[...] =`) and adjust the test's `_bridge_with` helper accordingly — do not change production code for this.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/unit/test_place_bridge_officers.py
git commit -m "feat(bridge): place SDK-populated officers at their stations (step 4)"
```

---

## Task 6: Integration test — real SDK crew → captured clips

**Files:**
- Create: `tests/integration/test_officer_placement_sdk.py`

Proves the capture works end-to-end against the real SDK `LoadBridge.Load("GalaxyBridge")` → `ConfigureCharacters` → per-officer `ConfigureForGalaxy` (which sets the real locations), and that the new recording surfaces are faithful (not loud stubs).

- [ ] **Step 1: Write the test**

This reuses the **known-good** SDK-load harness from `tests/integration/test_sdk_bridge_load.py` (the `_SDKLoader`-based `importlib` path — `tools.mission_harness` is NOT how that test loads). Copy the three helpers (`_fresh_world`, `_sdk_loader`, `_load_sdk_loadbridge`) and the module-level `SDK_LOADBRIDGE` constant **verbatim** from `tests/integration/test_sdk_bridge_load.py:1-83` into the new file. Then create `tests/integration/test_officer_placement_sdk.py`:

```python
"""Step 4: the real SDK bridge crew resolve to real placement clips, and the
recording animation surfaces stay faithful (never loud stubs)."""
import importlib.util
import sys
from pathlib import Path

import pytest

import App
import engine.appc._stub_trace as st
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.bridge_placement import capture_placement
from engine.appc.characters import CharacterClass

SDK_LOADBRIDGE = (
    Path(__file__).resolve().parents[2]
    / "sdk" / "Build" / "scripts" / "LoadBridge.py"
)

# --- PASTE _fresh_world, _sdk_loader, _load_sdk_loadbridge verbatim from
# --- tests/integration/test_sdk_bridge_load.py here (unchanged). ---


@pytest.fixture
def sdk_loadbridge():
    st.reset()
    _fresh_world()
    mod = _load_sdk_loadbridge()
    yield mod
    App.g_kSetManager._sets.clear()
    _set_current_game(None)
    st.reset()


def test_standard_crew_resolve_to_expected_clips(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")

    expected = {
        "Tactical": "data/animations/db_stand_t_l.nif",
        "Helm":     "data/animations/db_stand_h_m.nif",
        "XO":       "data/animations/db_stand_c_m.nif",
        "Science":  "data/animations/db_StoL1_S.nif",
        "Engineer": "data/animations/db_EtoL1_s.nif",
    }
    for slot, clip in expected.items():
        off = App.CharacterClass_Cast(bridge.GetObject(slot))
        assert off is not None, slot
        p = capture_placement(off)
        assert p is not None and p["clip_nif"] == clip, (slot, p)

    # Science/Engineer use move-from-station clips -> sample at frame 0.
    assert capture_placement(App.CharacterClass_Cast(bridge.GetObject("Science")))["sample_at_start"] is True
    assert capture_placement(App.CharacterClass_Cast(bridge.GetObject("Engineer")))["sample_at_start"] is True


def test_all_characters_in_set_are_enumerable(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")
    chars = bridge.GetObjectsByType(CharacterClass)
    # 5 standard crew + 3 random extras.
    assert len(chars) >= 5


def test_recording_surfaces_are_not_loud_stubs(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")
    bridge = App.g_kSetManager.GetSet("bridge")
    st.reset()
    for off in bridge.GetObjectsByType(CharacterClass):
        capture_placement(off)
    # Capturing placement must not trip any loud stub: g_kAnimationManager and
    # TGAnimPosition_Create are real recording surfaces.
    fired = st.fired()
    assert "g_kAnimationManager" not in fired
    assert "TGAnimPosition_Create" not in fired
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_officer_placement_sdk.py -v`
Expected: PASS (3 tests).

If the SDK load raises, the pasted helpers don't match `tests/integration/test_sdk_bridge_load.py` — re-copy them verbatim. `st.fired()` and `st.reset()` are the real accessors (`engine/appc/_stub_trace.py` exposes `stub_call`/`fired`/`dump_stub_summary`/`reset`).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_officer_placement_sdk.py
git commit -m "test(bridge): SDK crew resolve to real placement clips; surfaces stay faithful"
```

---

## Task 7: Live verification with Mark (orientation tuning)

**Not automatable** — Mark drives all visual verification (no synthetic desktop input, no full-screen capture).

- [ ] **Step 1: Confirm no rebuild needed**

This step is Python-only (no `native/`, CMake, or shader change). Do **not** rebuild. The build artifact is the existing `./build/dauntless`.

- [ ] **Step 2: Hand off to Mark**

Ask Mark to run `./build/dauntless`, load the Galaxy bridge, and report:
1. Are all officers visible at their stations (Felix/Tactical, Kiska/Helm, Saffi/XO, Miguel/Science, Brex/Engineer, plus extras)?
2. Orientation: are they facing the right way / not mirrored / not inside-out?
3. Do Science/Engineer sit at their consoles (frame-0 hold) rather than mid-walk?

- [ ] **Step 3: Tune `OFFICER_TRANSFORM` if needed**

Orientation is the expected iteration point (the X-flip lived in the replaced layer). If officers are mirrored/rotated/offset, adjust the single `OFFICER_TRANSFORM` matrix in `engine/host_loop.py` per Mark's observations and re-run. Note the "lego/untextured heads" bug is **out of scope** — expected to still be present; do not chase it here.

- [ ] **Step 4: Commit any tuning**

```bash
git add engine/host_loop.py
git commit -m "fix(bridge): tune officer world transform from live verify"
```

---

## Self-Review notes

- **Spec coverage:** capture via SDK `SetPosition` (Tasks 1-3); enumerate all `CharacterClass` incl. guest (Task 5 test `test_enumerates_all_including_guest`, Task 6 `test_all_characters_in_set_are_enumerable`); kept renderer bindings via wrappers (Task 4); X-flip live-tuning anchor (Task 5 `OFFICER_TRANSFORM`, Task 7); idempotency/leak-free (Task 5 `test_idempotent_*`); `engine/appc` headless (Tasks 1-3 import no renderer); `sample_at_start` clip-name heuristic (Task 3); recording surfaces faithful not loud (Task 6 `test_recording_surfaces_are_not_loud_stubs`); out-of-scope lego heads (Task 7).
- **Type consistency:** `capture_placement` returns `{"clip_nif","hidden","sample_at_start"}` — consumed with those exact keys in Task 5. `assemble_officer(body, head, body_tex, head_tex, placement, sample)` arg order matches the binding (`host_bindings.cc:647`) and the Task 4 wrapper. `set_instance_animation(iid, clip_index, loop, sample_at_start)` matches the binding and the Task 5 call `(iid, 0, False, sample)`.
- **No full pytest:** every run command names an explicit file.
