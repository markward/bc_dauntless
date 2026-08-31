# q13 Constant-Surface Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every invented or missing `App` constant in our shim with the value measured from the real game, so that an undefined constant can no longer silently degrade to a truthy `_NamedStub` or `int()==0`.

**Architecture:** A generator reads the machine-readable q13 dump
(`tools/probes/results/ghidra_export/stbc_constants.csv`, 3,829 usable rows) and
emits a data-only module, `engine/appc/constants_generated.py`. `App.py` applies
it at the very bottom of the file — after every real class is defined — injecting
module scalars, injecting class scalars onto classes we already implement, and
synthesizing the 228 classes we do not implement behind a stub-preserving base so
today's silent no-ops stay silent instead of becoming `AttributeError`s. An
explicit `DEVIATIONS` table records the handful of names we knowingly keep
different from BC, and a test asserts the shim matches the dump *except* for that
table, so the surface cannot drift again.

**Tech Stack:** Python 3 (repo shim + engine), pytest, the existing
`stub_telemetry` / `_NamedStub` machinery in `App.py`.

**Spec:** `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md` —
the q13 probe that captured this data and explicitly deferred this sweep
("Shim fix pass (226 wrong + ~1600 unique missing) is the remaining follow-up
work, tracked separately"). The measured numbers in that doc are superseded by
the audit in **Findings** below, which was run against the current tree.

## Global Constraints

- **Data source is `tools/probes/results/ghidra_export/stbc_constants.csv`.** It
  is the machine-readable twin of `q13_constants_battle.txt` /
  `q13_constants_menu.txt`. Never hand-type a constant value into the generated
  module; if a value looks wrong, fix the generator or add a `DEVIATIONS` entry.
- **Never define `__name__` or `__file__`** from the dump. They are in it
  (`'App'`, `'.\\Scripts\\App.pyc'`) and injecting them would break the module.
  Usable row count after excluding them is **3,829**.
- **Shared checkout.** Stage with explicit pathspecs only. Never `git add -A`,
  `git checkout --`, `git stash`, `git restore`, `git clean`, or
  `git reset --hard`. See `CLAUDE.md` § "Shared checkout".
- **Test gate is `scripts/check_tests.sh`**, not `scripts/run_tests.sh` — the
  latter is pytest-only and cannot see C++ regressions. A failure counts as
  pre-existing only if it is already in `tests/known_failures.txt`.
- **Baseline at time of writing:** `tests/known_failures.txt` holds zero ctest
  entries and exactly one pytest entry
  (`test_engineer_emitters.py::test_shield_level_change_announces`). Re-read the
  file rather than trusting this line.
- **Evidence tier.** Every value here is TESTED — read out of the running
  original game. Do not "improve" a measured value because it looks odd
  (`STBSF_SIZE_TO_TEXT == 0x40000000` and duplicate `WeaponsDisplay` indices are
  both real).

---

## Findings

This audit was run against the tree at plan time. It replaces the estimates in
the q13 doc. Reproduce with the script in Task 1.

| Scope | rows | already correct | **wrong value** | **missing** | **owner class absent** |
|---|---|---|---|---|---|
| module | 1,317 | 40 | 531 | 746 | — |
| class | 2,512 | 310 | 53 | 486 | 1,663 (228 classes) |
| **total** | **3,829** | **350** | **584** | **1,232** | **1,663** |

> These counts are only reproducible if the audit resolves `WC_*`/`KY_*` through
> `App.__getattr__` before classifying. That fallback memoizes into `vars(App)`
> on first access (`App.py:2284-2288`), so a dict-walk alone makes bucket
> membership depend on what else touched `App` first. See ruling PT1-1.

The 584 corrections are **not** uniformly mechanical. Seven families are coupled
to consuming code and get their own task:

1. **`CT_*` (37) — structural, not a renumbering.** Our `App.CT_NEBULA` is a
   *Python class object*, BC's is the int `32782`. `SetClass.GetClassObjectList`
   (`engine/appc/sets.py:450-461`) does `isinstance(obj, class_type)` and
   **returns `[]` when `class_type` is not a type**. Swapping in the ints
   without a registry silently empties every class-object query in the engine —
   nebulae, planets and suns would vanish from the renderer scene push
   (`host_loop.py:3984`). This is the single most dangerous item in the sweep.
   All 37 structurally-mismatched constants are `CT_*`; every other correction
   is number-to-number.
2. **`CSP_*` (2) — inverted polarity.** BC is
   `CSP_MISSION_CRITICAL=0, CSP_NORMAL=1, CSP_SPONTANEOUS=2` (lower wins); ours
   is the exact reverse (`engine/appc/ai.py:2159-2161`) and
   `CrewSpeechBus.speak` drops a line when `priority < self._active_priority`
   (`engine/appc/crew_speech.py:155`), i.e. higher-wins. Swapping the values
   without flipping that comparison makes mission-critical narration lose to
   idle chatter.
3. **`KeyboardBinding.KBT_*` (4 of 6) — sequential vs bitmask.** BC is
   `KBT_MANY_TO_MANY=1, KBT_SINGLE_EVENT_TO_KEY=2, KBT_SINGLE_KEY_TO_EVENT=4,
   KBT_LOCKOUT_CHANGE=8`; ours is `0,1,2,3`. Any `&` test against ours is
   meaningless today. `GET_BOOL_EVENT`/`GET_INT_EVENT` are also swapped (ours
   1/2, BC 2/1).
4. **`WC_*` / `KY_*` (338) — two namespaces our shim conflated.** BC's `WC_` are
   **lowercase** ASCII character codes (`WC_F == 102`, `WC_X == 120`) with
   function keys in a high band (`WC_F1 == 57365`, `WC_CURSOR == 57496`); BC's
   `KY_` are a separate small key-index enum (`KY_F == 33`, `KY_F1 == 59`,
   `KY_LBUTTON == 241`). Ours sets both to Windows VK codes.
5. **`TGKeyboardEvent.KS_*` (3) — renumbered.** BC `KS_NORMAL=0, KS_KEYDOWN=1,
   KS_KEYUP=2`; ours `KS_KEYDOWN=0, KS_KEYUP=1, KS_NORMAL=3`.
6. **`ET_*` (148) — safe symbolic swap, with two catches.** No arithmetic on any
   `ET_` constant exists anywhere in the SDK (1,228 files) or in `engine/`, so
   nothing depends on their spacing, and nothing persists them (no save/pickle
   path writes an event type). Catch (a): correcting them **fixes a live bug** —
   our invented values collide, `ET_CLOAKED_COLLISION == ET_POWER_FRACTION_CHANGED
   == 1075`, noted as out-of-scope at `tests/unit/test_wc_modifier_constants.py:85`.
   Catch (b): our invented `ET_WEAPON_FIRE_FAILED` was given `0x00800037`, which
   the dump shows is the real `ET_CANT_FIRE`. They are the same event; the
   uniqueness test needs to allow that alias deliberately.
7. **UI class constants (~30).** `WeaponsDisplay` (20), `TGParagraph` (5),
   `TGUIObject.ALIGN_*` (3), `TGSound` (3), `EffectController` (3),
   `TGModelPropertyManager` (2), `FloatRangeWatcher` (2), `ObjectGroup` (2),
   `ObjectGroupWithInfo` (2), `EngRepairPane.DIVIDER`, `TGFrame`,
   `STBSF_SIZE_TO_TEXT`, `SPECIES_GALAXY`/`SPECIES_SOVEREIGN`. Note
   `WeaponsDisplay`'s real values contain **intentional duplicates**
   (`TORPEDO_PANE == TOP_RIGHT_BORDER == 0`, `GLASS == LOWER_DISRUPTOR_INDICATOR_PANE == 8`)
   because BC shares one class namespace between a border enum and a pane enum.
   Do not "fix" them and do not assert uniqueness on that class.

**Deliberate deviations (do not correct):** `PI`, `HALF_PI`, `TWO_PI`,
`FOURTH_PI`. BC's are float32 (`PI == 3.14159274101`); ours are Python doubles
from `math`. Adopting BC's would lose ~7 digits of precision in physics for no
fidelity gain — nothing compares against them for equality. These go in
`DEVIATIONS` with that reason.

## File Structure

| File | Responsibility |
|---|---|
| `tools/gen_app_constants.py` (create) | Reads the CSV, writes `engine/appc/constants_generated.py`. Idempotent; re-runnable. |
| `engine/appc/constants_generated.py` (create, generated) | Data only: `MODULE_CONSTANTS`, `CLASS_CONSTANTS`. No logic, no imports from the engine. |
| `engine/appc/constants_apply.py` (create) | `apply_constants()` — injection logic, the stub-preserving synthesized-class base, and the `DEVIATIONS` table. |
| `App.py` (modify, bottom of file) | One call to `apply_constants(...)` after all real classes exist. |
| `engine/appc/object_types.py` (create, Task 9) | `CT_*` int↔class registry so BC's int type-tags and our `isinstance` dispatch coexist. |
| `tests/unit/test_constant_surface.py` (create) | The anti-drift gate: shim must match the dump except for `DEVIATIONS`. |

---

### Task 1: Audit script — reproduce the Findings table

Locks the numbers down so later tasks can assert progress against them.

**Files:**
- Create: `tools/constant_surface_audit.py`
- Test: `tests/unit/test_constant_surface_audit.py`

**Interfaces:**
- Produces: `load() -> (rows, ok, wrong, missing, noclass)` where each of the
  four buckets is a `list[tuple[dict, object, object]]` of
  `(csv_row, measured_value, our_value_or_None)`; and
  `real_attr(obj, name) -> tuple[bool, object]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_constant_surface_audit.py
from tools.constant_surface_audit import load, real_attr


def test_real_attr_ignores_getattr_stubs():
    """A _NamedStub vended by __getattr__ must not count as 'defined'."""
    import App
    # App has no such name; module __getattr__ vends a _NamedStub for it.
    assert getattr(App, "ZZ_NOT_A_REAL_CONSTANT") is not None
    assert real_attr(App, "ZZ_NOT_A_REAL_CONSTANT") == (False, None)


def test_load_partitions_every_usable_row():
    rows, ok, wrong, missing, noclass = load()
    assert len(rows) == 3829, "usable rows excl. __name__/__file__"
    assert len(ok) + len(wrong) + len(missing) + len(noclass) == len(rows)


def test_ct_constants_are_the_only_structural_mismatches():
    """Every non-numeric 'wrong' entry is a CT_ class object, not a number."""
    _, _, wrong, _, _ = load()
    structural = [r for r, _, have in wrong if not isinstance(have, (int, float))]
    assert len(structural) == 37
    assert all(r["name"].startswith("CT_") for r in structural)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_constant_surface_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.constant_surface_audit'`

- [ ] **Step 3: Write the implementation**

```python
# tools/constant_surface_audit.py
"""Compare the q13 measured constant surface against our App shim.

Data source: tools/probes/results/ghidra_export/stbc_constants.csv — the
machine-readable twin of the q13_constants_*.txt dumps.  Read, never guessed.
"""
import csv
import pathlib

CSV_PATH = (pathlib.Path(__file__).resolve().parent
            / "probes/results/ghidra_export/stbc_constants.csv")

# In the dump but never definable: they are Python module internals.
SKIP = {"__name__", "__file__"}


def parse(row):
    """The measured value for a dump row, correctly typed."""
    if row["type"] == "int":
        return int(row["dec"])
    if row["type"] == "float":
        return float(row["value_repr"])
    return row["value_repr"].strip("'")


def real_attr(obj, name):
    """(is_really_defined, value).

    Walks __dict__/__mro__ rather than using getattr, because App and TGObject
    both vend truthy stubs from __getattr__ for undefined names -- getattr can
    never distinguish 'defined' from 'stubbed'.
    """
    if isinstance(obj, type):
        for klass in obj.__mro__:
            if name in vars(klass):
                return True, vars(klass)[name]
        return False, None
    d = vars(obj)
    return (name in d, d.get(name))


def load():
    """Partition every usable dump row against the live App shim."""
    import App

    rows = [r for r in csv.DictReader(open(CSV_PATH)) if r["name"] not in SKIP]
    ok, wrong, missing, noclass = [], [], [], []
    for row in rows:
        want = parse(row)
        if row["scope"] == "module":
            have, val = real_attr(App, row["name"])
        else:
            has_cls, cls = real_attr(App, row["owner_class"])
            if not has_cls or not isinstance(cls, type):
                noclass.append((row, want, None))
                continue
            have, val = real_attr(cls, row["name"])
        bucket = ok if (have and val == want) else wrong if have else missing
        bucket.append((row, want, val))
    return rows, ok, wrong, missing, noclass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_constant_surface_audit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/constant_surface_audit.py tests/unit/test_constant_surface_audit.py
git commit -m "test(constants): audit script for the q13 constant surface"
```

---

### Task 2: Generator + generated data module

**Files:**
- Create: `tools/gen_app_constants.py`
- Create (generated): `engine/appc/constants_generated.py`
- Test: `tests/unit/test_constants_generated.py`

**Interfaces:**
- Consumes: `tools.constant_surface_audit.parse`, `SKIP`, `CSV_PATH` (Task 1).
- Produces: `engine/appc/constants_generated.py` exporting
  `MODULE_CONSTANTS: dict[str, int | float | str]` and
  `CLASS_CONSTANTS: dict[str, dict[str, int | float | str]]`;
  and `tools.gen_app_constants.render() -> str` returning the module source.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_constants_generated.py
from engine.appc.constants_generated import MODULE_CONSTANTS, CLASS_CONSTANTS


def test_counts_match_the_measured_dump():
    assert len(MODULE_CONSTANTS) == 1317
    assert sum(len(v) for v in CLASS_CONSTANTS.values()) == 2512
    # 314 distinct owner classes carry constants.  (The q13 header's "classes =
    # 630" counts every class in dir(App), most of which carry none.)
    assert len(CLASS_CONSTANTS) == 314


def test_module_internals_are_excluded():
    assert "__name__" not in MODULE_CONSTANTS
    assert "__file__" not in MODULE_CONSTANTS


def test_spot_values_are_the_measured_ones():
    assert MODULE_CONSTANTS["ET_CANT_FIRE"] == 0x800037
    assert MODULE_CONSTANTS["ET_SET_WARP_SEQUENCE"] == 0x8000EE
    assert MODULE_CONSTANTS["CSP_MISSION_CRITICAL"] == 0
    assert MODULE_CONSTANTS["STBSF_SIZE_TO_TEXT"] == 0x40000000
    assert CLASS_CONSTANTS["TGUIObject"]["ALIGN_UR"] == 1
    assert CLASS_CONSTANTS["KeyboardBinding"]["KBT_LOCKOUT_CHANGE"] == 8


def test_weapons_display_duplicates_are_preserved():
    """BC shares one class namespace between a border enum and a pane enum."""
    wd = CLASS_CONSTANTS["WeaponsDisplay"]
    assert wd["TORPEDO_PANE"] == wd["TOP_RIGHT_BORDER"] == 0
    assert wd["GLASS"] == wd["LOWER_DISRUPTOR_INDICATOR_PANE"] == 8


def test_generator_output_is_byte_identical_to_the_checked_in_file():
    """Guards against hand-editing the generated module."""
    import pathlib
    from tools.gen_app_constants import render
    path = (pathlib.Path(__file__).resolve().parents[2]
            / "engine/appc/constants_generated.py")
    assert path.read_text() == render()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_constants_generated.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.constants_generated'`

- [ ] **Step 3: Write the generator**

```python
# tools/gen_app_constants.py
"""Regenerate engine/appc/constants_generated.py from the q13 measured dump.

Run:  uv run python tools/gen_app_constants.py
"""
import csv
import pathlib

from tools.constant_surface_audit import CSV_PATH, SKIP, parse

OUT = (pathlib.Path(__file__).resolve().parents[1]
       / "engine/appc/constants_generated.py")

HEADER = '''"""App constant values measured from the ORIGINAL GAME.  GENERATED -- do not edit.

Regenerate with:  uv run python tools/gen_app_constants.py
Source:           tools/probes/results/ghidra_export/stbc_constants.csv
Provenance:       docs/instrumented_experiments/2026-07-13-constant-dump-probe.md

Every value here was read out of a running stbc.exe by probe q13.  None is
inferred from the SDK and none is invented.  `App.py` applies this table via
engine.appc.constants_apply.apply_constants; names we deliberately keep
different from BC are listed in that module's DEVIATIONS table.
"""

'''


def _lit(value):
    """Render a value as source.  Ints as hex when they are flag-like."""
    if isinstance(value, int) and value >= 0x1000:
        return hex(value)
    return repr(value)


def render():
    """The full source text of the generated module."""
    rows = [r for r in csv.DictReader(open(CSV_PATH)) if r["name"] not in SKIP]
    module = {r["name"]: parse(r) for r in rows if r["scope"] == "module"}
    classes = {}
    for r in rows:
        if r["scope"] != "module":
            classes.setdefault(r["owner_class"], {})[r["name"]] = parse(r)

    out = [HEADER, "MODULE_CONSTANTS: dict[str, int | float | str] = {\n"]
    for name in sorted(module):
        out.append("    %r: %s,\n" % (name, _lit(module[name])))
    out.append("}\n\nCLASS_CONSTANTS: dict[str, dict[str, int | float | str]] = {\n")
    for cls in sorted(classes):
        out.append("    %r: {\n" % cls)
        for name in sorted(classes[cls]):
            out.append("        %r: %s,\n" % (name, _lit(classes[cls][name])))
        out.append("    },\n")
    out.append("}\n")
    return "".join(out)


if __name__ == "__main__":
    OUT.write_text(render())
    print("wrote %s" % OUT)
```

- [ ] **Step 4: Generate the module and run the tests**

```bash
uv run python tools/gen_app_constants.py
uv run pytest tests/unit/test_constants_generated.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/gen_app_constants.py engine/appc/constants_generated.py tests/unit/test_constants_generated.py
git commit -m "feat(constants): generate measured App constant table from the q13 dump"
```

---

### Task 3: Injection with a stub-preserving synthesized class

Additive only — this task must not change a single existing value. Corrections
start at Task 5.

**Files:**
- Create: `engine/appc/constants_apply.py`
- Modify: `App.py` (append at end of file)
- Test: `tests/unit/test_constants_apply.py`

**Interfaces:**
- Consumes: `MODULE_CONSTANTS`, `CLASS_CONSTANTS` (Task 2); `_NamedStub` and
  `stub_telemetry` from `App.py`.
- Produces: `apply_constants(module, module_constants, class_constants, deviations, *, correct_existing) -> dict[str, int]`
  returning a counts dict with keys `"module_added"`, `"module_corrected"`,
  `"class_added"`, `"class_corrected"`, `"classes_synthesized"`, `"skipped"`;
  and `DEVIATIONS: dict[str, str]` mapping a qualified name
  (`"PI"`, `"TGUIObject.ALIGN_UR"`) to the reason we keep ours.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_constants_apply.py
import App
from tools.constant_surface_audit import real_attr


def test_previously_missing_constants_are_now_real_ints():
    """The 17 dead-handler event types from the stub report."""
    for name, want in [
        ("ET_CANT_FIRE", 0x800037), ("ET_FIRE", 0x800036),
        ("ET_OBJECTIVES", 0x80002E), ("ET_SET_WARP_SEQUENCE", 0x8000EE),
        ("ET_TORPEDO_ENTERED_SET", 0x80005C),
        ("ET_TRACTOR_BEAM_STARTED_FIRING", 0x80007D),
    ]:
        defined, value = real_attr(App, name)
        assert defined, "%s must be really defined, not stubbed" % name
        assert value == want


def test_synthesized_class_still_stubs_unknown_attributes():
    """A class we do not implement must keep today's silent-no-op behaviour:
    unknown attrs vend a stub, not AttributeError, and it stays callable."""
    cls = App.AnimTSParticleController
    assert cls.HIGH == 3 and cls.LOWEST == 0
    assert cls.SOME_ATTR_BC_HAS_THAT_WE_DO_NOT is not None   # must not raise
    instance = cls()                                          # must not raise
    assert instance.AnyMethod() is not None                   # must not raise


def test_injection_does_not_touch_classes_we_implement():
    """Real behaviour must survive: injecting constants onto ShipClass must
    not shadow its methods."""
    assert callable(App.ShipClass.GetName)


def test_additive_pass_changes_no_existing_value():
    """Task 3 is additive only -- corrections land in Tasks 5-11."""
    from tools.constant_surface_audit import load
    _, _, wrong, _, _ = load()
    assert len(wrong) == 584, "additive pass must not correct anything yet"


def test_deviations_are_respected():
    import math
    from engine.appc.constants_apply import DEVIATIONS
    assert "PI" in DEVIATIONS
    assert App.PI == math.pi          # ours, not BC's float32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_constants_apply.py -v`
Expected: FAIL — `test_previously_missing_constants_are_now_real_ints` fails
because `real_attr` reports `(False, None)` for `ET_CANT_FIRE`.

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/constants_apply.py
"""Apply the measured App constant table to the shim module.

Additive by default: a name we already define keeps its value unless
`correct_existing` names it.  That split exists because ~584 of our values are
invented and some are COUPLED to consuming code (CT_ class dispatch, CSP_
priority polarity, KBT_ bitmasks) -- those are corrected one audited family at
a time, not in one sweep.
"""

# Qualified name -> why we knowingly differ from the measured value.
DEVIATIONS: dict[str, str] = {
    "PI": "BC's is float32 (3.14159274101); ours is math.pi. Nothing compares "
          "these for equality and the extra precision matters to physics.",
    "HALF_PI": "See PI.",
    "TWO_PI": "See PI.",
    "FOURTH_PI": "See PI.",
}


def _make_synthesized(name, constants, named_stub_factory):
    """A class we do not implement, carrying its measured constants.

    Unknown attributes must keep vending a stub: before this table existed,
    `App.<Cls>` was itself a _NamedStub, so `App.<Cls>.anything` and
    `App.<Cls>(...)` were silent no-ops.  A plain `class X: ...` would turn
    every one of those into AttributeError/TypeError -- trading silent
    breakage for loud crashes across 228 classes we have never needed.
    """
    class _Meta(type):
        def __getattr__(cls, attr):
            return named_stub_factory("%s.%s" % (name, attr))

    def _instance_getattr(self, attr):
        return named_stub_factory("%s.%s" % (name, attr))

    body = dict(constants)
    body["__getattr__"] = _instance_getattr
    body["__init__"] = lambda self, *a, **k: None
    body["__doc__"] = ("Synthesized from the q13 constant dump; not implemented "
                       "by the shim. Unknown attributes still stub.")
    return _Meta(name, (), body)


def apply_constants(module, module_constants, class_constants, deviations,
                    *, correct_existing=frozenset(), named_stub_factory=None):
    """Inject measured constants into `module`.  Returns a counts dict."""
    counts = dict(module_added=0, module_corrected=0, class_added=0,
                  class_corrected=0, classes_synthesized=0, skipped=0)
    ns = module.__dict__

    for name, value in module_constants.items():
        if name in deviations:
            counts["skipped"] += 1
            continue
        if name not in ns:
            ns[name] = value
            counts["module_added"] += 1
        elif ns[name] != value and name in correct_existing:
            ns[name] = value
            counts["module_corrected"] += 1

    for cls_name, constants in class_constants.items():
        existing = ns.get(cls_name)
        if not isinstance(existing, type):
            ns[cls_name] = _make_synthesized(cls_name, constants,
                                             named_stub_factory)
            counts["classes_synthesized"] += 1
            continue
        for name, value in constants.items():
            qualified = "%s.%s" % (cls_name, name)
            if qualified in deviations:
                counts["skipped"] += 1
                continue
            # Never shadow a real method or attribute with a constant.
            current = next((vars(k)[name] for k in existing.__mro__
                            if name in vars(k)), None)
            if current is None and not any(name in vars(k)
                                           for k in existing.__mro__):
                setattr(existing, name, value)
                counts["class_added"] += 1
            elif callable(current):
                counts["skipped"] += 1
            elif current != value and qualified in correct_existing:
                setattr(existing, name, value)
                counts["class_corrected"] += 1
    return counts
```

Append to the **very bottom** of `App.py` (after every class is defined):

```python
# ── Measured constant surface ─────────────────────────────────────────────────
# Every App constant q13 read out of the running original game.  Applied last so
# the real classes defined above win over synthesized ones.  Additive for now:
# `correct_existing` grows one audited family at a time (see
# docs/superpowers/plans/2026-08-31-q13-constant-surface-sweep.md).
from engine.appc.constants_apply import DEVIATIONS, apply_constants
from engine.appc.constants_generated import CLASS_CONSTANTS, MODULE_CONSTANTS

CORRECT_EXISTING: frozenset[str] = frozenset()

apply_constants(
    sys.modules[__name__], MODULE_CONSTANTS, CLASS_CONSTANTS, DEVIATIONS,
    correct_existing=CORRECT_EXISTING, named_stub_factory=_NamedStub,
)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_constants_apply.py -v
scripts/check_tests.sh
```
Expected: `test_constants_apply.py` PASS (5 tests); gate names no failure absent
from `tests/known_failures.txt`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/constants_apply.py App.py tests/unit/test_constants_apply.py
git commit -m "feat(constants): inject 1,555 measured constants + synthesize 228 absent classes"
```

---

### Task 4: Anti-drift gate

Locks in the invariant "shim == dump, except DEVIATIONS" so this never rots
again. Written now, while the correction lists are still long, so each later
task shrinks a number the test prints.

**Files:**
- Create: `tests/unit/test_constant_surface.py`

**Interfaces:**
- Consumes: `tools.constant_surface_audit.load` (Task 1);
  `engine.appc.constants_apply.DEVIATIONS` (Task 3).

- [ ] **Step 1: Write the test (it passes immediately — it is a ratchet)**

```python
# tests/unit/test_constant_surface.py
"""The constant surface must match the game, and only shrink away from it.

REMAINING_WRONG is a ratchet: it may only ever be lowered.  When a task lands
a correction family, lower it by exactly that family's size.  A test that
fails saying the number is too HIGH means someone re-invented a value.
"""
from engine.appc.constants_apply import DEVIATIONS
from tools.constant_surface_audit import load

# Lower me. Never raise me.  584 at Task 4; 0 after Task 9.
REMAINING_WRONG = 584


def test_no_measured_constant_is_missing():
    _, _, _, missing, _ = load()
    assert missing == [], (
        "%d measured constants are undefined -- an undefined App constant "
        "silently degrades to a truthy _NamedStub or int()==0" % len(missing))


def test_every_measured_class_exists():
    _, _, _, _, noclass = load()
    assert noclass == [], "%d constants have no owner class" % len(noclass)


def test_wrong_values_only_ever_shrink():
    _, _, wrong, _, _ = load()
    named = sorted(r["qualified_name"] for r, _, _ in wrong)
    assert len(wrong) <= REMAINING_WRONG, (
        "constant surface regressed: %d wrong, ratchet allows %d.\n%s"
        % (len(wrong), REMAINING_WRONG, "\n".join(named)))
    assert len(wrong) == REMAINING_WRONG, (
        "%d wrong values remain but the ratchet says %d -- lower "
        "REMAINING_WRONG to %d" % (len(wrong), REMAINING_WRONG, len(wrong)))


def test_every_deviation_is_justified():
    for name, reason in DEVIATIONS.items():
        assert len(reason) > 40, "%s needs a real reason, not '%s'" % (name, reason)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/unit/test_constant_surface.py -v`
Expected: PASS (4 tests) — Task 3 already emptied `missing` and `noclass`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_constant_surface.py
git commit -m "test(constants): ratchet the constant surface against the measured dump"
```

---

### Task 5: Correct the 148 `ET_*` event values

Safe symbolically — no arithmetic on `ET_` constants exists in the SDK or
`engine/`, and nothing persists them. Fixes the live `1075` duplicate.

**Files:**
- Modify: `App.py` (the `CORRECT_EXISTING` set; delete the invented `ET_*`
  assignments at lines 893–1304 that the table now supplies)
- Modify: `engine/appc/events.py` (`ET_WEAPON_FIRE_FAILED` alias comment)
- Modify: `tests/unit/test_constant_surface.py` (`REMAINING_WRONG`: 584 → 436)
- Modify: `tests/unit/test_wc_modifier_constants.py:75-99` (drop the stale
  "pre-existing duplicate" caveat)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_constant_surface.py
def test_event_types_are_the_measured_values():
    import App
    assert App.ET_AI_TIMER == 0x800020
    assert App.ET_OBJECT_DESTROYED == 0x80004F
    assert App.ET_SET_TARGET == 0x8000E1
    assert App.ET_TACTICAL_SHIELD_0_LEVEL_CHANGE == 0x800041


def test_no_two_event_types_collide_except_the_known_alias():
    """ET_CLOAKED_COLLISION == ET_POWER_FRACTION_CHANGED == 1075 was a live
    bug in our invented numbering: two unrelated events sharing a handler
    chain.  The one legitimate duplicate is ET_WEAPON_FIRE_FAILED, which the
    dump shows IS ET_CANT_FIRE (0x800037)."""
    import App
    by_value = {}
    for name in dir(App):
        if name.startswith("ET_") and isinstance(getattr(App, name), int):
            by_value.setdefault(getattr(App, name), set()).add(name)
    dupes = {v: n for v, n in by_value.items() if len(n) > 1}
    assert dupes == {0x800037: {"ET_CANT_FIRE", "ET_WEAPON_FIRE_FAILED"}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_constant_surface.py -v`
Expected: FAIL — `App.ET_AI_TIMER` is still the invented `100`.

- [ ] **Step 3: Implement**

In `App.py`, delete the invented `ET_*` assignment blocks (the sections headed
"Event-type constants", "Input event types", "Bridge-interaction event types",
"Input events the SDK binds but the shim never defined", "FloatRangeWatcher
condition event", "Nebula + environmental event types", "Engineer status-report
event types", "AI condition watcher event types" — lines 893–1304), keeping any
name the dump does **not** carry (`ET_POWER_FRACTION_CHANGED`, `ET_PRELOAD_DONE`
— verify with the audit script, and give each a value outside BC's `0x30000+`
band). Then:

```python
CORRECT_EXISTING: frozenset[str] = frozenset(
    n for n in MODULE_CONSTANTS if n.startswith("ET_")
)
```

In `engine/appc/events.py`, replace the invented `ET_WEAPON_FIRE_FAILED` line
with an explicit alias:

```python
# The q13 dump shows BC has no distinct "fire failed" event: 0x00800037 IS
# ET_CANT_FIRE.  Keep the descriptive name as an alias rather than a second
# constant, so the two can never drift apart.
ET_WEAPON_FIRE_FAILED: int = 0x00800037  # == App.ET_CANT_FIRE
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_constant_surface.py tests/unit/test_wc_modifier_constants.py -v
scripts/check_tests.sh
```
Expected: PASS. Lower `REMAINING_WRONG` to `436`.

- [ ] **Step 5: Commit**

```bash
git add App.py engine/appc/events.py tests/unit/test_constant_surface.py tests/unit/test_wc_modifier_constants.py
git commit -m "fix(constants): adopt BC's measured ET_* values, fixing the 1075 collision"
```

---

### Task 6: Correct `CSP_*` and flip the priority comparison

Two values, one coupled comparison. Landing them apart would invert crew speech
priority, so they land together.

**Files:**
- Modify: `engine/appc/ai.py:2159-2163`
- Modify: `engine/appc/crew_speech.py:144-165`
- Modify: `App.py` (`CORRECT_EXISTING`)
- Modify: `tests/unit/test_crew_speech_priorities.py`
- Modify: `tests/unit/test_constant_surface.py` (`REMAINING_WRONG`: 436 → 434)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_crew_speech_priorities.py — replace the value assertions
def test_priority_constants_are_bcs_measured_values():
    """BC's convention is LOWER number = HIGHER priority."""
    import App
    assert App.CSP_MISSION_CRITICAL == 0
    assert App.CSP_NORMAL == 1
    assert App.CSP_SPONTANEOUS == 2


def test_mission_critical_line_interrupts_idle_chatter():
    """The behaviour the polarity protects: scripted narration must win."""
    import App
    from engine.appc.crew_speech import CrewSpeechBus
    bus = CrewSpeechBus()
    assert bus.speak("Felix", "idle", None, App.CSP_SPONTANEOUS, now=0.0) > 0.0
    assert bus.speak("Saffi", "critical", None, App.CSP_MISSION_CRITICAL,
                     now=0.1) > 0.0, "mission-critical must interrupt chatter"


def test_idle_chatter_does_not_interrupt_a_mission_critical_line():
    import App
    from engine.appc.crew_speech import CrewSpeechBus
    bus = CrewSpeechBus()
    assert bus.speak("Saffi", "critical", None, App.CSP_MISSION_CRITICAL,
                     now=0.0) > 0.0
    assert bus.speak("Felix", "idle", None, App.CSP_SPONTANEOUS,
                     now=0.1) == 0.0, "chatter must lose to mission-critical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_crew_speech_priorities.py -v`
Expected: FAIL — `App.CSP_MISSION_CRITICAL` is `2`, and
`test_mission_critical_line_interrupts_idle_chatter` fails once the values flip
but the comparison has not.

- [ ] **Step 3: Implement**

`engine/appc/ai.py`:

```python
# BC's measured values (q13 dump).  NOTE the polarity: LOWER number = HIGHER
# priority, the opposite of the invented values this replaces.  CrewSpeechBus
# .speak is written to match -- change one and you must change the other.
CSP_MISSION_CRITICAL = 0   # scripted mission narration -- wins
CSP_NORMAL           = 1   # acknowledgements; default
CSP_SPONTANEOUS      = 2   # idle chatter (engineer reports, ge*) -- loses
CSP_LOW  = CSP_SPONTANEOUS       # back-compat alias
CSP_HIGH = CSP_MISSION_CRITICAL  # back-compat alias
```

`engine/appc/crew_speech.py` — flip the drop test and the idle sentinel:

```python
        # BC's priority polarity is LOWER = MORE important (CSP_MISSION_CRITICAL
        # is 0), so a line is dropped when its number is GREATER than the one
        # already talking.  See engine/appc/ai.py CSP_* .
        if line_live and priority > self._active_priority:
            return 0.0  # a higher-priority line is still talking
```

and initialise the idle sentinel to a value nothing can lose to — replace both
`self._active_priority = -1` assignments (lines 95, 106, 131) with:

```python
        self._active_priority = sys.maxsize  # idle: any line outranks silence
```

Add `CSP_MISSION_CRITICAL`/`CSP_SPONTANEOUS` to `CORRECT_EXISTING` in `App.py`:

```python
CORRECT_EXISTING: frozenset[str] = frozenset(
    [n for n in MODULE_CONSTANTS if n.startswith("ET_")]
    + ["CSP_MISSION_CRITICAL", "CSP_SPONTANEOUS"]
)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_crew_speech_priorities.py tests/unit/test_ai_primitives.py tests/unit/test_constant_surface.py -v
scripts/check_tests.sh
```
Expected: PASS. Lower `REMAINING_WRONG` to `434`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai.py engine/appc/crew_speech.py App.py tests/unit/test_crew_speech_priorities.py tests/unit/test_constant_surface.py
git commit -m "fix(speech): adopt BC's CSP_ polarity and flip the arbitration test"
```

---

### Task 7: Correct the keyboard families (`WC_`, `KY_`, `KS_`, `KBT_`)

**347 corrections** (338 `WC_`/`KY_` + 3 `KS_` + 6 `KBT_`) plus **105
genuinely-missing** keyboard names, across four coupled tables. This is by far
the largest correction task and the highest-risk non-`CT_` family: our shim
conflated `WC_` (character codes) with `KY_` (key indices), and `KBT_` is a
bitmask we numbered sequentially.

Most `WC_`/`KY_` names are not literals in `App.py` at all — they resolve
through `App.__getattr__`'s fallback into `engine/appc/input.py` and memoize on
first access (`App.py:2284-2288`). Correcting them means correcting that table,
not adding lines to `App.py`.

**Files:**
- Modify: `engine/appc/input.py` (the generated `WC_`/`KY_` table)
- Modify: `App.py` (`CORRECT_EXISTING`)
- Modify: `tests/unit/test_wc_constants.py`, `tests/unit/test_keyboard_constant_table.py`
- Modify: `tests/unit/test_constant_surface.py` (`REMAINING_WRONG`: 434 → 87)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_keyboard_constant_table.py — replace the value assertions
def test_wc_are_character_codes_not_vk_codes():
    """BC's WC_ are LOWERCASE ASCII; ours were Windows VK codes."""
    import App
    assert App.WC_F == 102 and App.WC_G == 103 and App.WC_X == 120


def test_wc_function_keys_live_in_bcs_high_band():
    import App
    assert App.WC_F1 == 57365 and App.WC_F6 == 57370 and App.WC_F9 == 57373
    assert App.WC_CURSOR == 57496


def test_ky_is_a_separate_namespace_from_wc():
    """KY_ is a small key-index enum, NOT an alias of WC_."""
    import App
    assert App.KY_F == 33 and App.KY_F1 == 59 and App.KY_X == 45
    assert App.KY_LBUTTON == 241 and App.KY_RBUTTON == 242
    assert App.KY_F != App.WC_F, "the two namespaces must not be conflated"


def test_kbt_constants_are_a_bitmask():
    """BC's KBT_ are flag bits; ours were sequential 0-3, so every & test
    against them was meaningless."""
    import App
    kb = App.KeyboardBinding
    assert (kb.KBT_MANY_TO_MANY, kb.KBT_SINGLE_EVENT_TO_KEY,
            kb.KBT_SINGLE_KEY_TO_EVENT, kb.KBT_LOCKOUT_CHANGE) == (1, 2, 4, 8)
    assert kb.KBT_MANY_TO_MANY | kb.KBT_LOCKOUT_CHANGE == 9


def test_key_state_constants_are_the_measured_values():
    import App
    ke = App.TGKeyboardEvent
    assert (ke.KS_NORMAL, ke.KS_KEYDOWN, ke.KS_KEYUP) == (0, 1, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_keyboard_constant_table.py -v`
Expected: FAIL — `App.WC_F == 70` (VK code), `App.KY_F == 70` (aliased).

- [ ] **Step 3: Implement**

In `engine/appc/input.py`, stop deriving `KY_` from `WC_`; source both from
`MODULE_CONSTANTS`. Every key the dump carries takes its measured value; keys
the dump omits keep their current value and gain a comment saying so. Audit
every `KS_` comparison in the raw-keyboard dispatch path
(`_raw_keyboard_destination` and `TriggerKeyboardEvents`) — with `KS_NORMAL`
moving 3 → 0 and `KS_KEYDOWN` 0 → 1, any code testing `state == 0` by literal
must move to the constant. Add the four families to `CORRECT_EXISTING`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_keyboard_constant_table.py tests/unit/test_wc_constants.py tests/unit/test_wc_modifier_constants.py tests/unit/test_raw_keyboard_dispatch.py tests/unit/test_input_map_controls.py -v
scripts/check_tests.sh
```
Expected: PASS. Lower `REMAINING_WRONG` to `87`.

- [ ] **Step 5: Live check — keyboard is not provable headlessly**

```bash
./build/dauntless --developer
```
Confirm in-game: WASD flight, `F1`–`F9`, `` ` `` (profiler), `s` (E1M1 skip
intro), and one modifier chord still work. A green suite cannot see a dead key
— see `docs/engine/e1m1-skip-intro.md` for how `WC_*` collapse presented last
time.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/input.py App.py tests/unit/test_keyboard_constant_table.py tests/unit/test_wc_constants.py tests/unit/test_constant_surface.py
git commit -m "fix(input): separate BC's WC_ and KY_ namespaces, restore KBT_ bitmask"
```

---

### Task 8: Correct the UI class constants

~50 values with no ordering semantics — they index panes, alignments and
sounds. Mechanical, but `WeaponsDisplay` carries intentional duplicates.

**Files:**
- Modify: `App.py` (`CORRECT_EXISTING`)
- Modify: `tests/unit/test_constant_surface.py` (`REMAINING_WRONG`: 87 → 37)

Families: `WeaponsDisplay` (20), `TGParagraph` (5), `TGUIObject.ALIGN_*` (3),
`TGSound` (3), `EffectController` (3), `TGModelPropertyManager` (2),
`FloatRangeWatcher` (2), `ObjectGroup` (2), `ObjectGroupWithInfo` (2),
`EngRepairPane.DIVIDER` (1), `TGFrame` (1), `STBSF_SIZE_TO_TEXT` (1),
`SPECIES_GALAXY`/`SPECIES_SOVEREIGN` (2).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_constant_surface.py
def test_ui_class_constants_are_the_measured_values():
    import App
    assert App.TGUIObject.ALIGN_UR == 1 and App.TGUIObject.ALIGN_BL == 2
    assert App.EngRepairPane.DIVIDER == 6
    assert App.STBSF_SIZE_TO_TEXT == 0x40000000, "a flag bit, not 1"
    assert App.SPECIES_GALAXY == 101 and App.SPECIES_SOVEREIGN == 102


def test_weapons_display_keeps_bcs_intentional_duplicates():
    """BC shares one class namespace between a border enum and a pane enum;
    the repeated indices are real and must not be 'fixed'."""
    import App
    wd = App.WeaponsDisplay
    assert wd.TORPEDO_PANE == wd.TOP_RIGHT_BORDER == 0
    assert wd.GLASS == wd.LOWER_DISRUPTOR_INDICATOR_PANE == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_constant_surface.py -v`
Expected: FAIL — `App.TGUIObject.ALIGN_UR == 2`, `App.STBSF_SIZE_TO_TEXT == 1`.

- [ ] **Step 3: Implement**

Extend `CORRECT_EXISTING` with the qualified names for those thirteen families.
`ALIGN_*` and `STBSF_SIZE_TO_TEXT` both previously caused real bugs from stub
collapse (`docs/stub_heatmap.md`), so grep for literal-int comparisons against
them before landing.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/ui tests/unit/test_constant_surface.py -v
scripts/check_tests.sh
```
Expected: PASS. Lower `REMAINING_WRONG` to `37`.

- [ ] **Step 5: Live check**

```bash
./build/dauntless --developer
```
Confirm the tactical weapons display, the engineering repair pane and the
bridge menus still lay out correctly — `ALIGN_*` and the `WeaponsDisplay` pane
indices are pure layout and no test can see them.

- [ ] **Step 6: Commit**

```bash
git add App.py tests/unit/test_constant_surface.py
git commit -m "fix(ui): adopt BC's measured widget, alignment and species constants"
```

---

### Task 9: `CT_*` int↔class registry

The last 37, and the only architectural change. BC's `CT_*` are int type-tags;
ours are class objects consumed by `isinstance`. Both must work.

**Files:**
- Create: `engine/appc/object_types.py`
- Modify: `engine/appc/sets.py:450-461`
- Modify: `App.py` (`CT_*` block at lines 306–406, `CORRECT_EXISTING`)
- Test: `tests/unit/test_object_types.py`
- Modify: `tests/unit/test_constant_surface.py` (`REMAINING_WRONG`: 37 → 0)

**Interfaces:**
- Produces: `engine.appc.object_types.class_for(type_tag: int) -> type | None`
  and `tag_for(cls: type) -> int | None`; `register(tag: int, cls: type)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_object_types.py
import App
from engine.appc.object_types import class_for, tag_for


def test_ct_constants_are_bcs_int_tags():
    assert App.CT_NEBULA == 32782
    assert App.CT_SHIP == 32776
    assert App.CT_ASTEROID_FIELD == 32788


def test_tags_round_trip_to_our_classes():
    from engine.appc.nebula import Nebula
    assert class_for(App.CT_NEBULA) is Nebula
    assert tag_for(Nebula) == App.CT_NEBULA


def test_get_class_object_list_accepts_an_int_tag():
    """The regression this task exists to prevent: sets.py used to return []
    for any non-type argument, so int tags would silently empty every query."""
    from engine.appc.sets import SetClass
    from engine.appc.nebula import Nebula
    s = SetClass("test")
    neb = Nebula()
    s.AddObject(neb)
    assert s.GetClassObjectList(App.CT_NEBULA) == [neb]


def test_get_class_object_list_still_accepts_a_class():
    """Back-compat: engine code passing a class must keep working."""
    from engine.appc.sets import SetClass
    from engine.appc.nebula import Nebula
    s = SetClass("test")
    neb = Nebula()
    s.AddObject(neb)
    assert s.GetClassObjectList(Nebula) == [neb]


def test_unknown_tag_returns_empty_not_everything():
    from engine.appc.sets import SetClass
    s = SetClass("test")
    assert s.GetClassObjectList(0x7FFF) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_object_types.py -v`
Expected: FAIL — `App.CT_NEBULA` is a class, not `32787`.

- [ ] **Step 3: Implement**

```python
# engine/appc/object_types.py
"""BC's CT_* object type-tags, and the map to the classes our shim uses.

BC's CT_* are ints (measured: CT_NEBULA == 32787).  Our shim historically bound
the NAME to the CLASS, because SetClass.GetClassObjectList filters with
isinstance.  Both representations now coexist: the constants carry BC's ints and
this registry resolves a tag back to the class the filter needs.
"""
_BY_TAG: dict[int, type] = {}
_BY_CLASS: dict[type, int] = {}


def register(tag: int, cls: type) -> None:
    _BY_TAG[int(tag)] = cls
    _BY_CLASS.setdefault(cls, int(tag))


def class_for(tag):
    return _BY_TAG.get(int(tag)) if isinstance(tag, int) else None


def tag_for(cls):
    return _BY_CLASS.get(cls)
```

In `App.py`, replace each `CT_X = SomeClass` line with a `register` call, and
let the generated table supply the int:

```python
# CT_* now carry BC's measured int tags (see engine/appc/object_types.py);
# the class each tag maps to is registered here for isinstance-based filters.
for _tag_name, _cls in [
    ("CT_SUBSYSTEM_PROPERTY", SubsystemProperty),
    ("CT_NEBULA", Nebula),
    # ... one row per CT_ constant, same pairs as the old assignments
]:
    object_types.register(MODULE_CONSTANTS[_tag_name], _cls)
```

In `engine/appc/sets.py`, resolve a tag before filtering:

```python
    def GetClassObjectList(self, class_type):
        from engine.appc import object_types
        from engine.appc.properties import ShipProperty
        from engine.appc.ships import ShipClass
        # BC passes an int CT_ tag; engine code may still pass a class.
        if isinstance(class_type, int):
            class_type = object_types.class_for(class_type)
        # CT_SHIP maps to ShipProperty (the property template) but the SDK's
        # object-iteration sites want live ShipClass instances. Translate.
        if class_type is ShipProperty:
            class_type = ShipClass
        if not isinstance(class_type, type):
            return []
        return [obj for obj in self._objects.values()
                if isinstance(obj, class_type)]
```

Grep for every other consumer of a `CT_` constant (`GetNebula`,
`host_loop.py:3984`, the scene-push aggregators) and confirm each goes through
`GetClassObjectList` or `class_for` rather than comparing a class identity.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_object_types.py tests/unit/test_constant_surface.py -v
scripts/check_tests.sh
```
Expected: PASS. Lower `REMAINING_WRONG` to `0`.

- [ ] **Step 5: Live check — the failure mode is invisible headlessly**

```bash
DAUNTLESS_MISSION=engine.dev_missions.combat_stress ./build/dauntless --developer
```
Confirm nebulae, planets and suns still render. An empty `GetClassObjectList`
would silently remove them from the scene push with no error.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/object_types.py engine/appc/sets.py App.py tests/unit/test_object_types.py tests/unit/test_constant_surface.py
git commit -m "fix(constants): give CT_ BC's int tags behind an int<->class registry"
```

---

### Task 10: Close the loop on the 17 dead event handlers

With every constant real, five bridge menu items should come alive on their own
(both poster and handler are SDK-side). The other twelve need engine emitters —
this task records which, so the win is not mistaken for completeness.

**Files:**
- Modify: `engine/appc/events.py` (the undefined-event summary)
- Create: `docs/engine/event-emitter-gaps.md`
- Test: `tests/integration/test_bridge_menu_events_live.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_bridge_menu_events_live.py
import App


def test_bridge_menu_button_event_reaches_its_handler():
    """CreateBridgeMenuButton stamps App.ET_X on a TGIntEvent the button posts
    (sdk Bridge/BridgeUtils.py:37-43).  While ET_X was a _NamedStub the module
    __getattr__ vended a FRESH object per access, so the button's key and the
    handler's key were different objects and the click went nowhere."""
    assert isinstance(App.ET_SHOW_MISSION_LOG, int)
    fired = []
    obj = App.TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(App.ET_SHOW_MISSION_LOG,
                                        "tests.integration."
                                        "test_bridge_menu_events_live.record")
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_SHOW_MISSION_LOG)
    evt.SetDestination(obj)
    obj.ProcessEvent(evt)
    assert fired == [evt], "the handler must actually run"


def test_undefined_event_summary_is_empty():
    from engine.appc.events import undefined_event_type_summary_lines
    assert undefined_event_type_summary_lines() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_bridge_menu_events_live.py -v`
Expected: FAIL on the `record` helper not existing; write it as a
module-level `def record(evt): fired.append(evt)` bound to a module list.

- [ ] **Step 3: Implement**

Write `docs/engine/event-emitter-gaps.md` listing the twelve event types that
now have real constants but still no engine emitter — `ET_CANT_FIRE`,
`ET_SET_TARGET`, `ET_NAME_CHANGE`, `ET_TARGET_LIST_OBJECT_ADDED`,
`ET_TARGET_LIST_OBJECT_REMOVED`, `ET_TORPEDO_ENTERED_SET`,
`ET_TORPEDO_EXITED_SET`, `ET_TRACTOR_BEAM_STARTED_FIRING`,
`ET_TRACTOR_BEAM_STOPPED_FIRING`, `ET_RESTORE_PERSISTENT_TARGET`,
`ET_IN_SYSTEM_WARP`, `ET_SET_WARP_SEQUENCE` — each with the SDK handler that is
waiting for it and the engine call site that should post it. Defining a constant
removes its name from the undefined-event summary, so without this document the
sweep would trade a loud "this handler is dead" signal for a silent one.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/integration/test_bridge_menu_events_live.py -v
scripts/check_tests.sh
```
Expected: PASS.

- [ ] **Step 5: Live check**

```bash
./build/dauntless --developer
```
On the bridge, confirm the five previously-dead menu items now respond: XO →
Show Mission Log, XO → Contact Engineering, XO → Objectives, Science → Launch
Probe, Tactical → Fire.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/events.py docs/engine/event-emitter-gaps.md tests/integration/test_bridge_menu_events_live.py
git commit -m "feat(events): revive five bridge menu items; record the 12 emitter gaps"
```

---

### Task 11: Update the project docs

**Files:**
- Modify: `docs/instrumented_experiments/2026-07-13-constant-dump-probe.md`
- Modify: `docs/stub_heatmap.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the q13 probe doc**

Replace the "Shim fix pass … tracked separately" status line with the closure:
all 3,829 measured constants applied, four deliberate deviations (`PI` family),
this plan as the record.

- [ ] **Step 2: Regenerate the stub heatmap**

```bash
uv run python tools/stub_heatmap.py
```
Every `App.<NAME>` and `App.<CLASS>.<CONST>` row the sweep covers should
disappear. Note in the doc that the remaining rows are *methods*, not
constants — a different bug class needing different work.

- [ ] **Step 3: Add a CLAUDE.md reference row**

```markdown
| Measured constant surface | `engine/appc/constants_generated.py`, `tools/gen_app_constants.py`, `tests/unit/test_constant_surface.py` | All 3,829 `App` constants read out of the running original game by probe q13, applied to the shim. **Never hand-edit the generated module** — change the generator or add a `DEVIATIONS` entry in `engine/appc/constants_apply.py`. `test_constant_surface.py` ratchets the surface: `REMAINING_WRONG` may only fall. Four deliberate deviations (`PI`/`HALF_PI`/`TWO_PI`/`FOURTH_PI` — BC's are float32). Two traps this sweep uncovered: BC's `CSP_*` polarity is **lower = higher priority** (`crew_speech.py` is written to match — change one, change both), and `CT_*` are **int tags**, resolved to classes for `isinstance` filtering by `engine/appc/object_types.py`. |
```

- [ ] **Step 4: Verify doc consistency**

```bash
uv run pytest tests/docs/test_doc_consistency.py -v
scripts/check_tests.sh
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/instrumented_experiments/2026-07-13-constant-dump-probe.md docs/stub_heatmap.md CLAUDE.md
git commit -m "docs(constants): close the q13 shim fix pass"
```

---

## Self-Review

**Spec coverage.** The q13 doc's deferred work is "226 wrong + ~1600 unique
missing". Tasks 2–4 cover every missing constant (1,555 scalars + 1,663 on
absent classes); Tasks 5–9 cover all 584 wrong values, partitioned so no family
lands without its coupled consumers audited (`ET_` 148, `CSP_` 2, keyboard 347,
UI 50, `CT_` 37). Task 4's ratchet proves the partition is exhaustive — it fails
unless `REMAINING_WRONG` reaches 0. Task 10 covers the question that started
this work (the 17 dead handlers) and Task 11 the doc trail.

**Placeholder scan.** Every code step carries runnable source. The two steps
that legitimately cannot enumerate their content inline — Task 5's deletion of
the invented `ET_*` blocks and Task 7's `input.py` rework — name exact line
ranges (`App.py:893-1304`) and give the audit script as the way to enumerate
them.

**Type consistency.** `real_attr` (Task 1) returns `(bool, object)` and is used
that way in Tasks 3, 4. `apply_constants` (Task 3) is called with the keyword
arguments its signature declares. `MODULE_CONSTANTS` / `CLASS_CONSTANTS` keep
one shape from Task 2 through Task 9. `class_for` / `tag_for` / `register`
(Task 9) match their use in `sets.py`. `REMAINING_WRONG` steps
584 → 436 → 434 → 87 → 37 → 0, summing to exactly 584.

**Known risk this plan does not remove.** Tasks 7, 8, 9 and 10 each carry a live
check, because their failure modes — a dead key, a mislaid pane, an emptied
object query, an unresponsive menu item — are all invisible to a green test
suite. Do not report the sweep complete on `check_tests.sh` alone.
