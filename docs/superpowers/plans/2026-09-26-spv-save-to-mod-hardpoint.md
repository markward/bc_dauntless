# SPV Save-to-Mod-Hardpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Ship Property Viewer saves a ship whose hardpoint module comes from the mods directory, write the edits into that mod's own `ships/Hardpoints/<leaf>.py`; `hardpoint_overrides.py` stays the home for stock ships only.

**Architecture:** A new pure-text module `engine/appc/mod_hardpoint_writer.py` rewrites a mod hardpoint file: `SetPosition`/`SetRadius` are edited in place on the author's own call (located with Python 3 `ast`), everything else lives in one machine-owned, `DAUNTLESS_ENV`-guarded block at the end of the file, emitted by the existing `hardpoint_override_writer` emitter. A new `ModHardpointFileTarget` in `override_routing.py` does the file I/O (encoding, `.orig` backup, atomic replace), and `resolve_override_target` picks it when `mods.sdk_override` says the hardpoint is mod-supplied.

**Tech Stack:** Python 3 (`ast`, `os.replace`), pytest. Emitted code must be Python 1.5-safe.

**Spec:** `docs/superpowers/specs/2026-09-26-spv-save-to-mod-hardpoint-design.md`

## Global Constraints

- Emitted hardpoint code is **Python 1.5 safe**: no f-strings, no `True`/`False` literals, no `import X as Y`, no nested-scope closures (a `lambda` may only reference module globals such as `App`).
- The guard form is exactly `if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:`.
- `App.DAUNTLESS_ENV = 1` is a **real** module-level int in the project-root `App.py`. It must NOT go into `engine/appc/constants_generated.py` (generated; never hand-edit).
- The managed block's markers are exactly:
  `# >>> dauntless SPV edits -- machine-owned, regenerated on save; do not edit >>>` and `# <<< dauntless SPV edits <<<`.
- Outside the rewritten call spans and the managed block, the author's file text is **byte-identical** after a save (encoding and line endings preserved).
- Stock ships: `HardpointOverridesFileTarget` behaviour unchanged.
- No migration of existing overrides; `hardpoint_overrides.apply` behaviour for mod hardpoints is untouched.
- **Shared checkout — banned git:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore.
- Run pytest as `uv run pytest ...`.

## Review Focus

1. **CRLF line endings** — many BC mod files were authored on Windows. Expected: in-place edits and the appended block both keep `\r\n`; no line is converted. (Test in Task 4 and Task 5.)
2. **Non-UTF-8 bytes** (a Latin-1 `é` in an author comment) — expected: the file saves, and those bytes are written back unchanged. (Task 5.)
3. **No trailing newline on the last line** — expected: the block starts on its own line; the author's last line is not merged with the marker. (Task 3.)
4. **Read-only / unwritable mod file** — expected: the write raises, nothing is changed, the SPV keeps the staged edits and toasts the error. (Task 5 raises; Task 6 toasts.)
5. **A variable name reused for a different subsystem later in the file** (`p = App.X_Create("A"); p.SetPosition(...); p = App.X_Create("B"); p.SetPosition(...)`) — expected: an edit to `A` rewrites only `A`'s call. (Task 4.)

---

## File Structure

- `App.py` (modify): define `DAUNTLESS_ENV = 1`.
- `engine/appc/hardpoint_override_writer.py` (modify): marker guard in `_emit_part`; `DAUNTLESS_ENV` on `_RecordingApp`; extract `record_fn`; `fn_name` param on `_emit_function`; move edit dispatch here as `apply_edit`.
- `engine/appc/hardpoint_overrides.py` (regenerate): part blocks re-emitted with the new guard.
- `engine/appc/mod_hardpoint_writer.py` (create): pure text — split/read/emit the managed block, locate and rewrite in-place setter calls, `rewrite(text, leaf, edits) -> str`.
- `engine/appc/override_routing.py` (modify): `HardpointOverridesFileTarget` uses `apply_edit` and gains `describe()`; new `ModHardpointFileTarget`; routing branch.
- `engine/ui/ship_property_viewer_panel.py` (modify): save toasts destination / error.
- Tests: `tests/unit/test_dauntless_env_marker.py`, `tests/unit/test_mod_hardpoint_block.py`, `tests/unit/test_mod_hardpoint_inplace.py`, `tests/unit/test_mod_hardpoint_target.py`, `tests/unit/test_mod_hardpoint_e2e.py`, `tests/ui/test_ship_property_viewer_save_toast.py`; modify `tests/unit/test_override_routing.py`.

---

### Task 1: The `DAUNTLESS_ENV` marker and the part-block guard

**Files:**
- Modify: `App.py` (top-level, after the import block near line ~60, before other module-level definitions)
- Modify: `engine/appc/hardpoint_override_writer.py:60-81` (`_RecordingApp`), `:211-230` (`_emit_part`)
- Regenerate: `engine/appc/hardpoint_overrides.py`
- Test: `tests/unit/test_dauntless_env_marker.py`

**Interfaces:**
- Produces: `App.DAUNTLESS_ENV == 1` (int); `hardpoint_override_writer.env_guard(level: int = 1) -> str` returning `'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= %d:' % level` (no indentation, no newline).

Note: `tests/unit/test_bop_pose_migration.py` holds a FROZEN legacy block with the old guard — do **not** edit it; it execs against its own recording App and still passes. `tests/unit/test_override_writer_create.py` asserts `"ArticulatedPartProperty_Create" in text` — still true (the create call remains; only the guard changes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dauntless_env_marker.py
"""App.DAUNTLESS_ENV: the versioned marker emitted hardpoint code guards on
(spec 2026-09-26 section 4.3)."""
import App

from engine.appc import hardpoint_override_writer as w


def test_marker_is_a_real_int_not_a_stub():
    # The App module __getattr__ answers ANY undefined name with a stub, so
    # hasattr alone proves nothing here: the value must be a genuine int.
    assert "DAUNTLESS_ENV" in vars(App)
    assert type(App.DAUNTLESS_ENV) is int
    assert App.DAUNTLESS_ENV >= 1


def test_env_guard_text():
    assert w.env_guard() == 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:'
    assert w.env_guard(2).endswith(">= 2:")


def test_part_block_uses_the_marker_guard():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    text = w.emit(models)
    assert '    ' + w.env_guard() in text
    assert 'hasattr(App, "ArticulatedPartProperty_Create")' not in text


def test_part_round_trips_through_read_models_with_the_new_guard():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    again = w.read_models_from_source(w.emit(models))
    assert again["birdofprey"]["__parts__"]["left wing"] == [("SetTransitionSeconds", (2.0,))]


class _StockApp:
    """Stock BC's App: no marker, no ArticulatedPartProperty_Create."""
    class g_kModelPropertyManager:
        @staticmethod
        def RegisterLocalTemplate(p):
            raise AssertionError("stock BC must never register a part")


def test_stock_bc_skips_the_part_block():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [("SetTransitionSeconds", (2.0,))])
    ns = {}
    exec(w.emit(models), ns)
    import sys
    prev = sys.modules.get("App")
    sys.modules["App"] = _StockApp
    try:
        ns["_birdofprey"](lambda name: None)     # must not raise
    finally:
        sys.modules["App"] = prev
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_dauntless_env_marker.py -v`
Expected: FAIL — `DAUNTLESS_ENV` not in `vars(App)`; `env_guard` missing.

- [ ] **Step 3: Implement**

In `App.py`, after the import block:

```python
# Versioned marker for Dauntless-only code in hardpoint files (spec
# 2026-09-26 section 4.3). Emitted code guards with
#   if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= N:
# so stock stbc.exe skips it. Bump ONLY when newly emitted hardpoint code
# needs engine surface an older Dauntless lacks, and guard that code with the
# new level. Must stay a real definition: this module's __getattr__ answers
# any undefined name with a stub. Not a measured BC constant -- never add it
# to constants_generated.py.
DAUNTLESS_ENV = 1
```

In `engine/appc/hardpoint_override_writer.py`:

```python
def env_guard(level: int = 1) -> str:
    """The Python-1.5-safe guard every Dauntless-only emitted block sits
    under (spec 2026-09-26 section 4.3)."""
    return 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= %d:' % level
```

In `_RecordingApp` add a class attribute `DAUNTLESS_ENV = 1` (without it, `read_models` would skip every part block and a second save would silently drop all parts). In `_emit_part` replace the guard line with:

```python
    lines.append('    ' + env_guard())
```

and update its docstring: the guard sits on the versioned marker, not on a borrowed function name.

- [ ] **Step 4: Regenerate the override file**

```bash
uv run python -c "import engine.appc.hardpoint_overrides as ho; from engine.appc import hardpoint_override_writer as w; t=w.emit(w.read_models(ho)); open(ho.__file__,'w',encoding='utf-8').write(t)"
grep -c 'DAUNTLESS_ENV' engine/appc/hardpoint_overrides.py   # expect >= 2 (one per part block)
grep -c 'ArticulatedPartProperty_Create")' engine/appc/hardpoint_overrides.py   # expect 0
```

Check `git diff --stat engine/appc/hardpoint_overrides.py` shows only guard lines changed.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_dauntless_env_marker.py tests/unit/test_hardpoint_overrides_canonical.py tests/unit/test_bop_pose_migration.py tests/unit/test_override_writer_create.py tests/unit/test_authored_part_data.py tests/unit/test_constant_surface.py tests/unit/test_constant_surface_audit.py tests/ui/test_spv_part_nodes.py -v`
Expected: PASS. If a constant-surface test objects to the unmeasured `DAUNTLESS_ENV`, add a documented exemption in that test (never in `constants_generated.py`).

- [ ] **Step 6: Commit**

```bash
git add App.py engine/appc/hardpoint_override_writer.py engine/appc/hardpoint_overrides.py tests/unit/test_dauntless_env_marker.py
git commit -m "feat(appc): versioned App.DAUNTLESS_ENV marker guards Dauntless-only hardpoint code"
```

---

### Task 2: Writer refactor — `record_fn`, `fn_name`, shared `apply_edit`

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py` (`read_models`, `_emit_function`)
- Modify: `engine/appc/override_routing.py:46-67` (`HardpointOverridesFileTarget.write`)
- Test: `tests/unit/test_hardpoint_override_writer.py` (append)

**Interfaces:**
- Consumes: Task 1's `env_guard`.
- Produces:
  - `record_fn(fn) -> dict` — runs one override-shaped function `fn(find)` against the recorder with `_RecordingApp` swapped into `sys.modules["App"]`; returns `{subsystem: [(setter, args)], "__parts__": {...}}` (the `__parts__` key only when non-empty).
  - `_emit_function(leaf, per_sub, fn_name=None) -> str` — `fn_name` defaults to `"_" + leaf`.
  - `apply_edit(models, leaf, edit) -> None` — dispatches one edit tuple (the 3- and 4-tuple vocabulary currently inlined in `HardpointOverridesFileTarget.write`).

- [ ] **Step 1: Write the failing tests**

```python
# appended to tests/unit/test_hardpoint_override_writer.py
def test_record_fn_captures_setters_and_parts():
    src = w._emit_function("x", {
        "Port Warp": [("SetRadius", (1.5,))],
        "__parts__": {"wing": [("SetTransitionSeconds", (2.0,))]},
    }, fn_name="_spv")
    ns = {}
    exec(src, ns)
    got = w.record_fn(ns["_spv"])
    assert got["Port Warp"] == [("SetRadius", (1.5,))]
    assert got["__parts__"] == {"wing": [("SetTransitionSeconds", (2.0,))]}


def test_emit_function_default_name_unchanged():
    assert w._emit_function("galaxy", {}).startswith("def _galaxy(find):")


def test_apply_edit_dispatches_every_shape():
    m = {}
    w.apply_edit(m, "g", ("A", "SetRadius", (1.0,)))
    w.apply_edit(m, "g", ("A", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))]))
    w.apply_edit(m, "g", ("A", "__emitter__", 0, [("SetLightEmitterKind", (0, "point"))]))
    w.apply_edit(m, "g", ("wing", "__part__", [("SetTransitionSeconds", (2.0,))]))
    assert ("SetRadius", (1.0,)) in m["g"]["A"]
    assert ("SetGlowRegionShape", (0, "Box")) in m["g"]["A"]
    assert ("SetLightEmitterKind", (0, "point")) in m["g"]["A"]
    assert m["g"]["__parts__"]["wing"] == [("SetTransitionSeconds", (2.0,))]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -v -k "record_fn or default_name or apply_edit"`
Expected: FAIL — `record_fn` / `apply_edit` missing, `fn_name` unexpected keyword.

- [ ] **Step 3: Implement**

```python
def record_fn(fn) -> dict:
    """{subsystem: [(setter, args)], "__parts__": {...}} for ONE override-shaped
    function, by executing it against the recording find and a recording App."""
    per_sub: dict = {}
    parts: dict = {}
    prev_app = sys.modules.get("App", _NOT_SET)
    sys.modules["App"] = _RecordingApp(parts)
    try:
        fn(_make_find(per_sub))
    finally:
        if prev_app is _NOT_SET:
            del sys.modules["App"]
        else:
            sys.modules["App"] = prev_app
    if parts:
        per_sub[_PARTS_KEY] = parts
    return per_sub


def read_models(module) -> dict:
    """...(keep existing docstring)..."""
    return {leaf: record_fn(fn) for leaf, fn in module.OVERRIDES.items()}


def apply_edit(models, leaf, edit) -> None:
    """Apply one SPV edit tuple (see HardpointOverridesFileTarget.write)."""
    if len(edit) == 4 and edit[1] == "__region__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls)
    elif len(edit) == 4 and edit[1] == "__emitter__":
        subsystem, _tag, index, calls = edit
        set_region(models, leaf, subsystem, index, calls, prefix=_EMITTER_PREFIX)
    elif len(edit) == 3 and edit[1] == "__part__":
        name, _tag, calls = edit
        set_part(models, leaf, name, calls)
    else:
        subsystem, setter, args = edit
        set_setter(models, leaf, subsystem, setter, args)
```

`_emit_function(leaf, per_sub, fn_name=None)`: first line becomes `"def %s(find):" % (fn_name or "_" + leaf)`; nothing else changes.

In `override_routing.HardpointOverridesFileTarget.write`, replace the inline `for edit in edits:` dispatch with `for edit in edits: _writer.apply_edit(models, leaf, edit)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py tests/unit/test_override_routing.py tests/unit/test_hardpoint_overrides_canonical.py tests/unit/test_override_writer_create.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py engine/appc/override_routing.py tests/unit/test_hardpoint_override_writer.py
git commit -m "refactor(appc): extract record_fn/apply_edit and name-parameterise _emit_function"
```

---

### Task 3: Managed block — split, read, emit

**Files:**
- Create: `engine/appc/mod_hardpoint_writer.py`
- Test: `tests/unit/test_mod_hardpoint_block.py`

**Interfaces:**
- Consumes: `hardpoint_override_writer.record_fn`, `_emit_function(leaf, per_sub, fn_name=...)`, `env_guard()`.
- Produces:
  - `START_MARKER`, `END_MARKER` (str constants, exact text in Global Constraints).
  - `BLOCK_FN = "_dauntless_spv"`.
  - `class ManagedBlockError(ValueError)`.
  - `split_block(text: str) -> tuple[str, str | None]` — `(author_text, block_text)`; `block_text` runs from the start marker's line through the end marker's line (inclusive, with its newline); `author_text` is everything else, unchanged. Raises `ManagedBlockError` for: a start without an end, an end without a start, or more than one start marker.
  - `read_block(block_text: str | None) -> dict` — per_sub model (empty dict for `None`).
  - `emit_block(per_sub: dict, newline: str = "\n") -> str` — the whole block including markers, ending with `newline`; `""` when the model has no non-empty entries.
  - `append_block(author_text: str, block: str, newline: str) -> str` — author text + (a `newline` first if the author text is non-empty and does not already end with a newline) + block.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mod_hardpoint_block.py
import ast

import pytest

from engine.appc import mod_hardpoint_writer as mw

AUTHOR = 'import App\nX = App.EngineProperty_Create("Port Warp")\nApp.g_kModelPropertyManager.RegisterLocalTemplate(X)\n'


def _model():
    return {
        "Port Warp": [("SetGlowRegionShape", (0, "Box")),
                      ("SetLightEmitterKind", (0, "point"))],
        "__parts__": {"wing": [("SetTransitionSeconds", (2.0,))]},
    }


def test_emit_then_split_then_read_round_trips():
    block = mw.emit_block(_model())
    text = mw.append_block(AUTHOR, block, "\n")
    author, got = mw.split_block(text)
    assert author == AUTHOR
    assert got == block
    assert mw.read_block(got) == _model()


def test_block_is_guarded_and_python_parses():
    block = mw.emit_block(_model())
    assert block.startswith(mw.START_MARKER)
    assert block.rstrip("\n").endswith(mw.END_MARKER)
    assert 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:' in block
    assert "def _dauntless_spv(find):" in block
    ast.parse(block)
    for bad in ("f\"", "True", "False", " as "):
        assert bad not in block


def test_empty_model_emits_nothing():
    assert mw.emit_block({}) == ""
    assert mw.emit_block({"Port Warp": [], "__parts__": {}}) == ""


def test_reading_a_block_has_no_side_effect_on_the_live_manager():
    import App
    mgr = App.g_kModelPropertyManager
    scope = App.TGModelPropertyManager.LOCAL_TEMPLATES
    assert mgr.FindByName("wing", scope) is None
    mw.read_block(mw.emit_block(_model()))
    assert mgr.FindByName("wing", scope) is None


def test_no_block_reads_as_empty():
    author, block = mw.split_block(AUTHOR)
    assert author == AUTHOR and block is None
    assert mw.read_block(None) == {}


@pytest.mark.parametrize("text", [
    AUTHOR + mw.START_MARKER + "\n",                                  # no end
    AUTHOR + mw.END_MARKER + "\n",                                    # no start
    AUTHOR + mw.emit_block(_model()) + mw.emit_block(_model()),       # two blocks
])
def test_malformed_markers_are_refused(text):
    with pytest.raises(mw.ManagedBlockError):
        mw.split_block(text)


def test_author_without_trailing_newline_gets_one_before_the_block():
    text = mw.append_block(AUTHOR.rstrip("\n"), mw.emit_block(_model()), "\n")
    assert "RegisterLocalTemplate(X)\n" + mw.START_MARKER in text


def test_crlf_block():
    block = mw.emit_block(_model(), newline="\r\n")
    assert "\r\n" in block and "\n" not in block.replace("\r\n", "")
    assert mw.read_block(block) == _model()


def test_the_block_runs_against_a_live_find():
    """Executed as a hardpoint file would be: the guarded call site applies
    the setters to whatever find() returns."""
    calls = []

    class Prop:
        def __getattr__(self, n):
            return lambda *a: calls.append((n, a))

    class Mgr:
        def FindByName(self, name, scope):
            return Prop() if name == "Port Warp" else None
        def RegisterLocalTemplate(self, p):
            pass

    class FakeApp:
        DAUNTLESS_ENV = 1
        g_kModelPropertyManager = Mgr()
        class TGModelPropertyManager:
            LOCAL_TEMPLATES = 1
        @staticmethod
        def ArticulatedPartProperty_Create(name):
            return Prop()

    import sys
    prev = sys.modules.get("App")
    sys.modules["App"] = FakeApp
    try:
        exec(mw.emit_block(_model()), {"App": FakeApp})
    finally:
        sys.modules["App"] = prev
    assert ("SetGlowRegionShape", (0, "Box")) in calls
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_mod_hardpoint_block.py -v`
Expected: FAIL — module `engine.appc.mod_hardpoint_writer` not found.

- [ ] **Step 3: Implement**

```python
"""Rewrite a MOD's own ships/Hardpoints/<leaf>.py with Ship Property Viewer
edits (spec docs/superpowers/specs/2026-09-26-spv-save-to-mod-hardpoint-design.md).

Pure text in, text out -- file I/O lives in override_routing.ModHardpointFileTarget.
SetPosition/SetRadius are rewritten in place on the author's own call; every
other edit lives in ONE machine-owned block at the end of the file, between
START_MARKER and END_MARKER, guarded on App.DAUNTLESS_ENV so stock stbc.exe
skips it. Emitted code must stay Python 1.5 safe.
"""
from __future__ import annotations

import ast

from engine.appc import hardpoint_override_writer as _w

START_MARKER = "# >>> dauntless SPV edits -- machine-owned, regenerated on save; do not edit >>>"
END_MARKER = "# <<< dauntless SPV edits <<<"
BLOCK_FN = "_dauntless_spv"
_PARTS_KEY = "__parts__"


class ManagedBlockError(ValueError):
    """The file's managed-block markers are malformed; never guess."""


def _marker_lines(text):
    """[(line_start, line_end_incl_newline, stripped_line)] for marker lines."""
    out, pos = [], 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s in (START_MARKER, END_MARKER):
            out.append((pos, pos + len(line), s))
        pos += len(line)
    return out


def split_block(text):
    marks = _marker_lines(text)
    if not marks:
        return text, None
    kinds = [m[2] for m in marks]
    if kinds != [START_MARKER, END_MARKER]:
        raise ManagedBlockError("malformed dauntless SPV markers: %r" % kinds)
    (s0, _s1, _), (_e0, e1, _) = marks
    return text[:s0] + text[e1:], text[s0:e1]


def read_block(block_text):
    """The block's model. Only the `def _dauntless_spv` is executed -- never
    the block's `import App` + guarded call, which under the real shim would
    register parts on the live g_kModelPropertyManager as a side effect."""
    if not block_text:
        return {}
    tree = ast.parse(block_text)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == BLOCK_FN]
    if len(fn) != 1:
        raise ManagedBlockError("managed block has no %s()" % BLOCK_FN)
    ns = {}
    exec(compile(ast.Module(body=fn, type_ignores=[]), "<dauntless SPV block>", "exec"), ns)  # noqa: S102
    return _w.record_fn(ns[BLOCK_FN])


def _non_empty(per_sub):
    subs = any(c for s, c in per_sub.items() if s != _PARTS_KEY)
    parts = any(c for c in per_sub.get(_PARTS_KEY, {}).values())
    return subs or parts


def emit_block(per_sub, newline="\n"):
    if not _non_empty(per_sub):
        return ""
    lines = [START_MARKER,
             _w._emit_function("spv", per_sub, fn_name=BLOCK_FN),
             "",
             "import App",
             _w.env_guard(),
             "    %s(lambda n: App.g_kModelPropertyManager.FindByName("
             "n, App.TGModelPropertyManager.LOCAL_TEMPLATES))" % BLOCK_FN,
             END_MARKER]
    return newline.join("\n".join(lines).split("\n")) + newline


def append_block(author_text, block, newline):
    if not block:
        return author_text
    if author_text and not author_text.endswith(("\n", "\r")):
        author_text += newline
    return author_text + block
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_mod_hardpoint_block.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/mod_hardpoint_writer.py tests/unit/test_mod_hardpoint_block.py
git commit -m "feat(appc): managed SPV block for mod hardpoint files"
```

---

### Task 4: In-place `SetPosition`/`SetRadius` rewrite and `rewrite()`

**Files:**
- Modify: `engine/appc/mod_hardpoint_writer.py`
- Test: `tests/unit/test_mod_hardpoint_inplace.py`

**Interfaces:**
- Consumes: Task 3's `split_block`, `read_block`, `emit_block`, `append_block`, `ManagedBlockError`; Task 2's `apply_edit`.
- Produces:
  - `INPLACE_SETTERS = ("SetPosition", "SetRadius")`.
  - `find_setter_call(tree: ast.Module, subsystem: str, setter: str) -> ast.Call | None` — module-level only.
  - `format_setter_call(var: str, setter: str, args: tuple) -> str` — e.g. `PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)`; floats as `%f`.
  - `rewrite(text: str, leaf: str, edits: list) -> str` — the full pure transform (spec §5 steps 3–6).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mod_hardpoint_inplace.py
import ast

import pytest

from engine.appc import mod_hardpoint_writer as mw

SRC = '''# my refit, do not touch this comment
import App

PortWarp = App.EngineProperty_Create("Port Warp")
PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand
PortWarp.SetRadius(1.200000)
App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)

Hull = App.HullProperty_Create("Hull")
App.g_kModelPropertyManager.RegisterLocalTemplate(Hull)
'''


def _changed_lines(a, b):
    return [(x, y) for x, y in zip(a.splitlines(), b.splitlines()) if x != y]


def test_setposition_rewritten_in_place_only():
    out = mw.rewrite(SRC, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.5))])
    assert _changed_lines(SRC, out) == [(
        "PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)   # tuned by hand",
        "PortWarp.SetPosition(1.000000, 2.000000, 3.500000)   # tuned by hand")]
    assert mw.START_MARKER not in out        # nothing needed the block


def test_setradius_rewritten_in_place():
    out = mw.rewrite(SRC, "refit", [("Port Warp", "SetRadius", (0.5,))])
    assert "PortWarp.SetRadius(0.500000)" in out
    assert len(_changed_lines(SRC, out)) == 1


def test_missing_setter_falls_back_to_the_block():
    out = mw.rewrite(SRC, "refit", [("Hull", "SetRadius", (4.0,))])
    assert SRC in out                          # author text untouched
    _author, block = mw.split_block(out)
    assert mw.read_block(block)["Hull"] == [("SetRadius", (4.0,))]


def test_loop_created_subsystem_falls_back():
    src = SRC + 'for n in ["A"]:\n    q = App.EngineProperty_Create(n)\n    q.SetRadius(1.0)\n'
    out = mw.rewrite(src, "refit", [("A", "SetRadius", (2.0,))])
    assert out.startswith(src)
    assert mw.read_block(mw.split_block(out)[1])["A"] == [("SetRadius", (2.0,))]


def test_py2_syntax_file_puts_everything_in_the_block():
    src = SRC + "print 'hello'\n"
    out = mw.rewrite(src, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    assert out.startswith(src)
    assert mw.read_block(mw.split_block(out)[1])["Port Warp"] == [
        ("SetPosition", (1.0, 2.0, 3.0))]


def test_glow_goes_to_block_and_block_merges_across_saves():
    once = mw.rewrite(SRC, "refit", [("Port Warp", "__region__", 0,
                                      [("SetGlowRegionShape", (0, "Box"))])])
    twice = mw.rewrite(once, "refit", [("Hull", "SetRadius", (4.0,))])
    assert twice.count(mw.START_MARKER) == 1
    model = mw.read_block(mw.split_block(twice)[1])
    assert model["Port Warp"] == [("SetGlowRegionShape", (0, "Box"))]
    assert model["Hull"] == [("SetRadius", (4.0,))]


def test_inplace_success_drops_a_stale_block_entry():
    # An older save put SetPosition in the block (e.g. before the author added
    # the call). Once it is done in place, the block copy must go.
    stale = mw.append_block(SRC, mw.emit_block({"Port Warp": [
        ("SetPosition", (9.0, 9.0, 9.0)), ("SetGlowRegionShape", (0, "Box"))]}), "\n")
    out = mw.rewrite(stale, "refit", [("Port Warp", "SetPosition", (1.0, 2.0, 3.0))])
    model = mw.read_block(mw.split_block(out)[1])
    assert model["Port Warp"] == [("SetGlowRegionShape", (0, "Box"))]
    assert "PortWarp.SetPosition(1.000000, 2.000000, 3.000000)" in out


def test_emptying_the_block_removes_it():
    with_block = mw.rewrite(SRC, "refit", [("wing", "__part__",
                                            [("SetTransitionSeconds", (2.0,))])])
    out = mw.rewrite(with_block, "refit", [("wing", "__part__", [])])
    assert out == SRC


def test_reused_variable_only_rewrites_the_named_subsystem():
    src = ('import App\n'
           'p = App.EngineProperty_Create("A")\np.SetRadius(1.000000)\n'
           'p = App.EngineProperty_Create("B")\np.SetRadius(2.000000)\n')
    out = mw.rewrite(src, "x", [("A", "SetRadius", (7.0,))])
    assert out == src.replace("p.SetRadius(1.000000)", "p.SetRadius(7.000000)")


def test_crlf_preserved_for_inplace_and_block():
    src = SRC.replace("\n", "\r\n")
    out = mw.rewrite(src, "refit", [
        ("Port Warp", "SetRadius", (0.5,)),
        ("Hull", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))])])
    assert "\n" not in out.replace("\r\n", "")
    assert "PortWarp.SetRadius(0.500000)\r\n" in out


def test_malformed_markers_raise():
    with pytest.raises(mw.ManagedBlockError):
        mw.rewrite(SRC + mw.START_MARKER + "\n", "refit",
                   [("Port Warp", "SetRadius", (0.5,))])


def test_result_parses():
    out = mw.rewrite(SRC, "refit", [
        ("Port Warp", "SetPosition", (1.0, 2.0, 3.0)),
        ("wing", "__part__", [("SetTransitionSeconds", (2.0,))])])
    ast.parse(out)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_mod_hardpoint_inplace.py -v`
Expected: FAIL — `rewrite` missing.

- [ ] **Step 3: Implement** (append to `engine/appc/mod_hardpoint_writer.py`)

```python
INPLACE_SETTERS = ("SetPosition", "SetRadius")


def _is_create_of(node, subsystem):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "App"
            and node.func.attr.endswith("_Create")
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == subsystem)


def find_setter_call(tree, subsystem, setter):
    """The LAST module-level `V.<setter>(...)` issued while V is bound to
    `App.<X>_Create("<subsystem>")`. None when absent (loop-built, computed
    name, inside a function, or no such call)."""
    var, hit = None, None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if len(stmt.targets) == 1 and names and _is_create_of(stmt.value, subsystem):
                var, hit = names[0], None
            elif var in names:
                var = None                          # rebound: later calls are not ours
        elif (var is not None and isinstance(stmt, ast.Expr)
              and isinstance(stmt.value, ast.Call)
              and isinstance(stmt.value.func, ast.Attribute)
              and stmt.value.func.attr == setter
              and isinstance(stmt.value.func.value, ast.Name)
              and stmt.value.func.value.id == var):
            hit = stmt.value
    return hit


def format_setter_call(var, setter, args):
    return "%s.%s(%s)" % (var, setter, ", ".join("%f" % float(a) for a in args))


def _char_span(text, node):
    """(start, end) character offsets of `node` in `text`. ast columns are
    UTF-8 byte offsets within a line, so convert per line."""
    lines = text.split("\n")                 # CRLF keeps its \r on the line: fine for offsets
    def off(lineno, col_bytes):
        before = sum(len(l) + 1 for l in lines[:lineno - 1])
        return before + len(lines[lineno - 1].encode("utf-8")[:col_bytes].decode("utf-8"))
    return off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)


def _newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def rewrite(text, leaf, edits):
    newline = _newline_of(text)
    author, block = split_block(text)
    models = {leaf: read_block(block)}
    try:
        tree = ast.parse(author) if ("\r" not in author.replace("\r\n", "")) else None
    except SyntaxError:
        tree = None

    replacements = []                         # (start, end, new_text)
    for edit in edits:
        if tree is not None and len(edit) == 3 and edit[1] in INPLACE_SETTERS:
            subsystem, setter, args = edit
            call = find_setter_call(tree, subsystem, setter)
            if call is not None:
                start, end = _char_span(author, call)
                replacements.append((start, end,
                                     format_setter_call(call.func.value.id, setter, args)))
                calls = models[leaf].get(subsystem)
                if calls:
                    models[leaf][subsystem] = [(s, a) for (s, a) in calls if s != setter]
                continue
        _w.apply_edit(models, leaf, edit)

    new_author = author
    for start, end, new in sorted(replacements, reverse=True):
        new_author = new_author[:start] + new + new_author[end:]

    # Verify: undoing exactly the replaced spans restores the author text.
    # Ascending order: every earlier span is already reverted to its original
    # length, so each span sits at its ORIGINAL start offset.
    restored = new_author
    for start, end, new in sorted(replacements):
        restored = restored[:start] + author[start:end] + restored[start + len(new):]
    if restored != author:
        raise ManagedBlockError("in-place rewrite touched text outside its call spans")

    out = append_block(new_author, emit_block(models[leaf], newline), newline)
    if tree is not None:
        ast.parse(out)                        # raises SyntaxError on a bad result
    return out
```

If `test_emptying_the_block_removes_it` fails because `append_block` returns the author text plus nothing, the author text must be the pre-block text byte-for-byte — `split_block` guarantees that.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_mod_hardpoint_inplace.py tests/unit/test_mod_hardpoint_block.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/mod_hardpoint_writer.py tests/unit/test_mod_hardpoint_inplace.py
git commit -m "feat(appc): rewrite SetPosition/SetRadius in place in mod hardpoint files"
```

---

### Task 5: `ModHardpointFileTarget` and routing

**Files:**
- Modify: `engine/appc/override_routing.py`
- Test: `tests/unit/test_mod_hardpoint_target.py`; modify `tests/unit/test_override_routing.py` (the existing `test_resolve_returns_file_target` must configure an empty mod index — `mods.configure(None)` — so it stays a stock-ship test)

**Interfaces:**
- Consumes: `mod_hardpoint_writer.rewrite(text, leaf, edits)`; `engine.mods.sdk_override(module_rel) -> Path | None`.
- Produces:
  - `HardpointOverridesFileTarget.describe() -> str` → `"hardpoint_overrides.py"`.
  - `ModHardpointFileTarget(path: str)` with `.path`, `write(leaf, edits) -> None`, `describe() -> str` → `"mod file: " + path`.
  - `resolve_override_target(ship) -> HardpointOverridesFileTarget | ModHardpointFileTarget`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mod_hardpoint_target.py
import os
import stat

import pytest

from engine import mods
import engine.appc.override_routing as r
from engine.appc import mod_hardpoint_writer as mw

SRC = ('import App\n'
       'PortWarp = App.EngineProperty_Create("Port Warp")\n'
       'PortWarp.SetRadius(1.200000)\n'
       'App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)\n')


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


class _Ship:
    def GetScript(self):
        return "ships.Refit"


def _mod_tree(tmp_path, body=SRC.encode()):
    f = tmp_path / "M" / "Scripts" / "ships" / "Hardpoints" / "refit.py"
    f.parent.mkdir(parents=True)
    f.write_bytes(body)
    return f


def test_mod_backed_leaf_routes_to_the_mod_file(tmp_path, monkeypatch):
    f = _mod_tree(tmp_path)
    mods.configure(mods.build_index(tmp_path))
    monkeypatch.setattr(r, "hardpoint_leaf_for_ship", lambda ship: "refit")
    t = r.resolve_override_target(_Ship())
    assert isinstance(t, r.ModHardpointFileTarget)
    assert os.path.samefile(t.path, f)
    assert t.describe().startswith("mod file: ")


def test_stock_leaf_routes_to_overrides(monkeypatch):
    monkeypatch.setattr(r, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    t = r.resolve_override_target(_Ship())
    assert isinstance(t, r.HardpointOverridesFileTarget)
    assert t.describe() == "hardpoint_overrides.py"


def test_write_edits_in_place_and_backs_up_once(tmp_path):
    f = _mod_tree(tmp_path)
    t = r.ModHardpointFileTarget(str(f))
    t.write("refit", [("Port Warp", "SetRadius", (0.5,))])
    assert "PortWarp.SetRadius(0.500000)" in f.read_text()
    orig = tmp_path / "M" / "Scripts" / "ships" / "Hardpoints" / "refit.py.orig"
    assert orig.read_bytes() == SRC.encode()
    t.write("refit", [("Port Warp", "SetRadius", (0.7,))])
    assert orig.read_bytes() == SRC.encode()          # never overwritten
    assert not (f.parent / "refit.py.tmp").exists()


def test_latin1_bytes_survive(tmp_path):
    body = ("# caf\xe9 refit\n" + SRC).encode("latin-1")
    f = _mod_tree(tmp_path, body)
    r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    out = f.read_bytes()
    assert out.startswith(b"# caf\xe9 refit\n")
    assert b"PortWarp.SetRadius(0.500000)" in out


def test_crlf_bytes_survive(tmp_path):
    f = _mod_tree(tmp_path, SRC.replace("\n", "\r\n").encode())
    r.ModHardpointFileTarget(str(f)).write("refit", [
        ("Port Warp", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))])])
    out = f.read_bytes()
    assert b"\n" not in out.replace(b"\r\n", b"")


def test_failure_leaves_the_file_untouched(tmp_path, monkeypatch):
    f = _mod_tree(tmp_path)
    def boom(text, leaf, edits):
        raise ValueError("bad emit")
    monkeypatch.setattr(r._mod_writer, "rewrite", boom)
    with pytest.raises(ValueError):
        r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    assert f.read_bytes() == SRC.encode()
    assert not (f.parent / "refit.py.tmp").exists()


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX perms")
def test_unwritable_directory_raises_and_leaves_file(tmp_path):
    f = _mod_tree(tmp_path)
    (f.parent / "refit.py.orig").write_bytes(SRC.encode())   # backup already exists
    os.chmod(f.parent, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(OSError):
            r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    finally:
        os.chmod(f.parent, stat.S_IRWXU)
    assert f.read_bytes() == SRC.encode()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_mod_hardpoint_target.py -v`
Expected: FAIL — `ModHardpointFileTarget` missing.

- [ ] **Step 3: Implement** (in `engine/appc/override_routing.py`)

```python
import shutil

from engine import mods as _mods
from engine.appc import mod_hardpoint_writer as _mod_writer


class ModHardpointFileTarget:
    """Writes SPV edits into a mod's own ships/Hardpoints/<leaf>.py
    (spec 2026-09-26). Encoding and line endings are preserved: the file is
    read as UTF-8, falling back to Latin-1 (which round-trips any byte), and
    written back in the same encoding with newline translation off."""

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def describe(self) -> str:
        return "mod file: " + self.path

    def write(self, leaf, edits) -> None:
        with open(self.path, "rb") as fh:
            raw = fh.read()
        try:
            text, enc = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, enc = raw.decode("latin-1"), "latin-1"
        new_text = _mod_writer.rewrite(text, leaf, edits)   # raises on any problem
        orig = self.path + ".orig"
        if not os.path.exists(orig):
            shutil.copy2(self.path, orig)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(new_text.encode(enc))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
```

Add to `HardpointOverridesFileTarget`:

```python
    def describe(self) -> str:
        return "hardpoint_overrides.py"
```

Replace `resolve_override_target`:

```python
def resolve_override_target(ship):
    """A mod-supplied hardpoint file owns its ship's edits; stock ships go to
    hardpoint_overrides.py (spec 2026-09-26 section 3)."""
    leaf = hardpoint_leaf_for_ship(ship)
    if leaf:
        path = _mods.sdk_override("ships/Hardpoints/%s.py" % leaf)
        if path is not None:
            return ModHardpointFileTarget(str(path))
    return HardpointOverridesFileTarget()
```

Update the module docstring (drop "Today every ship routes to ..."). In `tests/unit/test_override_routing.py` add `from engine import mods` and call `mods.configure(None)` at the start of `test_resolve_returns_file_target`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_mod_hardpoint_target.py tests/unit/test_override_routing.py tests/unit/test_mods_sdk_finder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/override_routing.py tests/unit/test_mod_hardpoint_target.py tests/unit/test_override_routing.py
git commit -m "feat(spv): route mod-ship saves into the mod's own hardpoint file"
```

---

### Task 6: SPV save toast — destination and error

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py:3595-3603` (the `resolve_override_target(ship).write(...)` try/except in the `"save"` action)
- Test: `tests/ui/test_ship_property_viewer_save_toast.py`

**Interfaces:**
- Consumes: `target.describe()` (Task 5); existing `self._show_toast(text)` / `self._current_toast()`.
- Produces: toast text `"Saved to " + target.describe()` on success when the target has `describe`, `"Saved"` otherwise; `"Save failed: " + str(e)` on a write exception.

- [ ] **Step 1: Write the failing tests**

Reuse the `make_panel` fixture pattern from `tests/ui/test_ship_property_viewer_save_persistence.py` (copy its `_FakeShip`, `_FAKE_DESCRIPTORS` imports — import them from that module rather than duplicating: `from tests.ui.test_ship_property_viewer_save_persistence import _FakeShip, _FAKE_DESCRIPTORS`; if that import path does not work under the suite's rootdir, copy the two definitions verbatim).

```python
# tests/ui/test_ship_property_viewer_save_toast.py
import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from tests.ui.test_ship_property_viewer_save_persistence import _FakeShip, _FAKE_DESCRIPTORS


class _OkTarget:
    def write(self, leaf, edits):
        pass
    def describe(self):
        return "mod file: /mods/M/Scripts/ships/Hardpoints/refit.py"


class _FailTarget:
    def write(self, leaf, edits):
        raise PermissionError("read-only")
    def describe(self):
        return "mod file: x"


def _panel(monkeypatch, target):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]])
                                      for d in _FAKE_DESCRIPTORS])
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "refit")
    p = ShipPropertyViewerPanel(ship_getter=lambda: _FakeShip())
    p.open()
    return p


def test_save_toasts_the_destination(monkeypatch):
    p = _panel(monkeypatch, _OkTarget())
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._current_toast() == "Saved to mod file: /mods/M/Scripts/ships/Hardpoints/refit.py"


def test_failed_save_toasts_the_error_and_keeps_edits(monkeypatch):
    p = _panel(monkeypatch, _FailTarget())
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("save")
    assert p._current_toast() == "Save failed: read-only"
    assert p._pending_radius.get(0) == 3.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer_save_toast.py -v`
Expected: FAIL — toast is `None`.

- [ ] **Step 3: Implement**

```python
            target = resolve_override_target(ship)
            try:
                target.write(leaf, edits)
            except Exception as e:
                from engine import dev_mode
                dev_mode.log_swallowed("spv light/radius save", e)
                self._show_toast("Save failed: %s" % e)
                # Write failed — keep the staged edits (dirty markers + Save
                # bar stay) rather than silently discarding them.
                self._last_pushed = None
                return True
            describe = getattr(target, "describe", None)
            self._show_toast("Saved to " + describe() if describe else "Saved")
```

(`getattr` because many existing UI tests pass a bare `_Target` with only `write`.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ui/test_ship_property_viewer_save_toast.py tests/ui/test_ship_property_viewer_save_persistence.py tests/ui/test_spv_part_nodes.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS. If an existing test asserts `toast is None` right after a save, it is pinning the old silence — update it to the new text and say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_save_toast.py
git commit -m "feat(spv): toast where a save went, and why a save failed"
```

---

### Task 7: End-to-end load and stock-BC compatibility; gate

**Files:**
- Test: `tests/unit/test_mod_hardpoint_e2e.py`

**Interfaces:**
- Consumes: `ModHardpointFileTarget` (Task 5); real `App` shim (`App.g_kModelPropertyManager`, `App.TGModelPropertyManager.LOCAL_TEMPLATES`, `App.EngineProperty_Create`, `App.HullProperty_Create`).

- [ ] **Step 1: Write the tests**

```python
# tests/unit/test_mod_hardpoint_e2e.py
"""A saved mod hardpoint file loads the way a hardpoint file loads (exec with
the real App shim) and the edits reach the property templates; and the same
file runs under a stock-BC App without touching any Dauntless-only surface."""
import sys

import pytest

import App
import engine.appc.override_routing as r

SRC = ('import App\n'
       'PortWarp = App.EngineProperty_Create("Port Warp")\n'
       'PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)\n'
       'PortWarp.SetRadius(1.200000)\n'
       'App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)\n')

EDITS = [
    ("Port Warp", "SetPosition", (1.0, 2.0, 3.0)),
    ("Port Warp", "SetRadius", (0.5,)),
    ("Port Warp", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))]),
    ("wing", "__part__", [("SetTransitionSeconds", (2.0,))]),
]


@pytest.fixture
def saved(tmp_path):
    f = tmp_path / "refit.py"
    f.write_text(SRC)
    r.ModHardpointFileTarget(str(f)).write("refit", EDITS)
    return f.read_text()


@pytest.fixture
def clean_templates():
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    yield mgr
    mgr.ClearLocalTemplates()


def test_edits_reach_the_templates(saved, clean_templates):
    exec(compile(saved, "refit.py", "exec"), {"__name__": "refit"})
    scope = App.TGModelPropertyManager.LOCAL_TEMPLATES
    p = clean_templates.FindByName("Port Warp", scope)
    pos = p.GetPosition()
    assert (pos.x, pos.y, pos.z) == (1.0, 2.0, 3.0)
    assert p.GetRadius() == 0.5
    assert p.GetGlowRegionShape(0) == "Box"
    assert clean_templates.FindByName("wing", scope) is not None


class _StockProp:
    """Only the SDK surface a stock property has."""
    def __init__(self, name):
        self.name, self.calls = name, []
    def SetPosition(self, *a): self.calls.append(("SetPosition", a))
    def SetRadius(self, *a): self.calls.append(("SetRadius", a))


class _StockApp:
    created = []
    class g_kModelPropertyManager:
        @staticmethod
        def RegisterLocalTemplate(p): pass
    @classmethod
    def EngineProperty_Create(cls, name):
        p = _StockProp(name); cls.created.append(p); return p


def test_stock_bc_runs_the_file_and_applies_only_sdk_edits(saved):
    prev = sys.modules.get("App")
    sys.modules["App"] = _StockApp
    try:
        exec(compile(saved, "refit.py", "exec"), {"__name__": "refit"})   # must not raise
    finally:
        sys.modules["App"] = prev
    (p,) = _StockApp.created
    assert p.calls == [("SetPosition", (1.0, 2.0, 3.0)), ("SetRadius", (0.5,))]
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/unit/test_mod_hardpoint_e2e.py -v`
Expected: PASS (all behaviour exists by now). If `GetGlowRegionShape(0)` does not read back as `"Box"`, read the data-bag note at the top of `hardpoint_override_writer.py` and assert via `p._data` instead — do not change production code to suit the test.

- [ ] **Step 3: Mutation check** (proves the e2e test guards the guard)

```bash
cp engine/appc/hardpoint_override_writer.py /tmp/bak_hpw.py
# Edit env_guard to return 'if 1:' , then:
uv run pytest tests/unit/test_mod_hardpoint_e2e.py::test_stock_bc_runs_the_file_and_applies_only_sdk_edits -v   # expect FAIL
cp /tmp/bak_hpw.py engine/appc/hardpoint_override_writer.py
diff engine/appc/hardpoint_override_writer.py /tmp/bak_hpw.py   # expect no output
```

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 (no failure outside `tests/known_failures.txt`).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_mod_hardpoint_e2e.py
git commit -m "test(spv): saved mod hardpoint file loads in Dauntless and in stock BC"
```

---

## Live check (Mark, after merge)

With a mod ship installed: `--developer` → open the SPV on the mod ship → move a subsystem pin and add a glow → Save. Expect a toast "Saved to mod file: …", the mod's `ships/Hardpoints/<leaf>.py` to show the new `SetPosition` value in place plus a `# >>> dauntless SPV edits` block at the end, a `<leaf>.py.orig` beside it, and the edits present after respawning the ship. A stock ship's save still toasts "Saved to hardpoint_overrides.py".
