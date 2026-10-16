# `.pyc`-only Mod Modules (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mod scripts shipped only as Python 1.5 bytecode (`.pyc`, magic `0x4E99`) import and run through the SDK loader. First consumer: the LC Intrepid Pack's `Tactical.Projectiles.ZZ_VoyPhoton` and `ZZ_Tricobalt`, which today fall back to the stock photon.

**Architecture:** A new `engine/py15/` package reads the 1.5 `.pyc` format and *lifts* straight-line bytecode into the Python 3 `ast.Module` that the module's source would have parsed to. Anything outside that subset raises `Py15Unsupported`. Both SDK loader twins (`tools/mission_harness.py`, `tests/conftest.py`) accept a mod `.pyc` only when no `.py` exists. They get their tree from one shared `_module_tree()` helper, and from there the existing transform pipeline is unchanged. Stock content still loads only from SDK `.py`.

**Tech Stack:** Python 3.11 (`ast`, `importlib`, `struct`), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md`. Phase 1 = §0. Read §2.3–2.4 for why there is no decompiler and §4 for the design.

## Global Constraints

- **Phase 1 is mod scripts only.** The lifter is reachable only through `_mod_override_spec` and the finder's mod-index branches. Never add a `.pyc` lookup to a stock-SDK branch (spec §0, §4.3).
- **Precedence per layer:** `.py` → `/__init__.py` → `.pyc` → `/__init__.pyc`. A mod `.pyc` beats the stock SDK `.py`. Any mod's `.py` beats any mod's `.pyc` (spec §4.3).
- **Never write, log or commit decompiled or lifted mod text, and never commit a mod-derived value in a test.** Tests about the Intrepid assert against the mod module's own getters (spec §6).
- **No new dependency.** `xdis`/`uncompyle6` are not to be added to `pyproject.toml`, imported, or shelled out to (spec §2.3).
- **Both twins identically.** Every finder/loader change lands in `tools/mission_harness.py` AND `tests/conftest.py`, and `tests/unit/test_sdk_finder_twins_stay_in_sync.py` must cover it (CLAUDE.md; memory `project_duplicate_sdk_ast_transforms`).
- **Never spell `game` or `sdk` as a path segment.** Use `engine.paths` / `tests.helpers.bc_assets.require_game_dir` (CLAUDE.md, `tests/unit/test_path_indirection.py`).
- **Shared checkout: no destructive git.** Never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`. Stage with explicit pathspecs. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` (CLAUDE.md "Shared checkout").
- **D1–D3 take the spec's recommended options:** an unloadable `.pyc` raises (no stock fall-through); straight-line subset only; this plan does **not** depend on `be914a7b`.
- **Gate before merge:** `scripts/check_tests.sh` must pass. Never baseline a new failure in `tests/known_failures.txt`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A corrupt or truncated `.pyc`** (bad download, half-extracted zip) must produce `Py15Unsupported` and the one log line, never a `struct.error`/`IndexError` crash at import. Pinned in Task 1 (`test_every_truncation_is_a_format_error`, `test_a_negative_length_is_…`) and Task 2 (`test_corrupt_bytecode_only_ever_raises_py15unsupported`, prefix + 2000 bit-flips).
2. **An upper-case `.PYC` extension** (Windows-authored zips) must load like `.pyc`. Pinned in Task 4 (`test_an_upper_case_pyc_extension_loads`).
3. **`reload()` of a `.pyc`-backed module** (SDK `loadspacehelper.py` reloads hardpoint modules) must re-lift, not crash or keep stale code. Pinned in Task 4 (`test_reload_re_lifts_the_pyc`).
4. **An unloadable mod `.pyc` that shadows a stock module** must fail with `Py15Unsupported` and not silently fall through to the stock `.py` (D1). Pinned in Task 4 (`test_an_unloadable_pyc_shadowing_stock_does_not_fall_back_to_stock`).
5. **Log hygiene:** a loadable `.pyc` prints no `[sdk-loader]` line, and an unloadable one prints exactly one however often it is imported. Pinned in Task 2 (`load_tree` tests), Task 4 (`test_a_pyc_only_mod_module_loads`, `test_an_unloadable_pyc_fails_loudly_once`) and Task 5 (`test_the_mod_projectile_loads_from_its_pyc`).

---

## Setup (once, before Task 1)

The work continues in the spec's worktree. Rename its branch, then give it the per-tree files a worktree lacks. Without `settings.json`, BC paths don't resolve. Without `mods/`, the Intrepid tests skip. Without the build, the gate fails. Run each command and check it succeeds:

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/pyc-mod-loading
git branch -m docs/pyc-mod-loading-spec feat/pyc-only-mod-modules
cp /Users/mward/Documents/Projects/bc_dauntless/settings.json .
mkdir -p mods && cp -Rc /Users/mward/Documents/Projects/bc_dauntless/mods/. mods/
uv sync --extra dev
U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none; cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION
cmake --build build -j
uv run pytest tests/unit/test_sdk_finder_twins_stay_in_sync.py tests/unit/test_mods_sdk_finder.py -q
```

Expected: the last command passes. `git status --short` shows no tracked changes: `settings.json`, `mods/` and `build/` are gitignored.

## File structure

| File | Responsibility |
|---|---|
| `engine/py15/__init__.py` (create) | Public API: `Py15Unsupported`, `is_py15_pyc`, `lift`, `lift_file`, `load_tree` (the one-time production log line). |
| `engine/py15/opcodes15.py` (create) | The Python 1.5 opcode table, comparison table and flag bits. Data only. |
| `engine/py15/marshal15.py` (create) | `.pyc` header + 1.5 marshal reader → `Code15`. Never executes anything. |
| `engine/py15/lift.py` (create) | `Code15` → `ast.Module` for the straight-line subset; `Py15Unsupported`. |
| `tests/helpers/py15_assembler.py` (create) | Test-only 1.5 marshal **writer** and assembler for hand-made fixtures. |
| `tools/mission_harness.py`, `tests/conftest.py` (modify) | `_module_tree()` helper; `_SDKLoader.exec_module` uses it; `.pyc` suffixes in `_mod_override_spec`; bare-name mod-index loop accepts `.pyc`. |
| `tests/unit/test_sdk_finder_twins_stay_in_sync.py` (modify) | Also compares `_module_tree`. |
| `engine/appc/weapon_subsystems.py`, `tests/unit/test_torpedo_script_fallback.py` (modify) | Docstrings only: the photon is now the fallback for *refused* bytecode. |
| `CLAUDE.md` (modify) | One reference row. |

---

### Task 1: Python 1.5 `.pyc` reader and the test assembler

**Files:**
- Create: `engine/py15/opcodes15.py`
- Create: `engine/py15/marshal15.py`
- Create: `engine/py15/__init__.py` (temporary one-liner, completed in Task 2)
- Create: `tests/helpers/py15_assembler.py`
- Test: `tests/unit/test_py15_marshal.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `engine.py15.opcodes15`: `HAVE_ARGUMENT = 90`, `NAMES: dict[int, str]`, `COMPARE: tuple[str, ...]`, `CO_VARARGS = 0x4`, `CO_VARKEYWORDS = 0x8`.
  - `engine.py15.marshal15`: `MAGIC = b"\x99N\r\n"`, `class Py15FormatError(ValueError)`, frozen dataclass `Code15(argcount, nlocals, stacksize, flags, code: bytes, consts: tuple, names: tuple[str], varnames: tuple[str], filename: str, name: str, firstlineno: int, lnotab: bytes)`, `is_py15_pyc(data: bytes) -> bool`, `load_pyc(data: bytes) -> Code15`. String constants stay `bytes`; identifiers are latin-1 `str`.
  - `tests.helpers.py15_assembler`: `OPCODES: dict[str, int]`, `FUNCTION_FLAGS = 0x3`, `asm(instructions) -> bytes`, `function(name, instructions, *, consts=(None,), names=(), varnames=(), argcount=0, flags=FUNCTION_FLAGS, firstlineno=1) -> Code15`, `module(instructions, *, consts=(None,), names=()) -> Code15`, `dumps(value) -> bytes`, `pyc(code, mtime=0) -> bytes`, `projectile_module(damage=500.0) -> Code15`.

- [ ] **Step 1: Write the failing test** at `tests/unit/test_py15_marshal.py`:

```python
"""engine.py15.marshal15 reads Python 1.5 .pyc files.

The synthetic round-trips run on any machine: every fixture is our own
bytecode, built by tests/helpers/py15_assembler.py. The stock-corpus read
needs a BC install (configured through engine.paths) and skips without one.
"""
import pytest

from engine.py15.marshal15 import Code15, Py15FormatError, is_py15_pyc, load_pyc
from tests.helpers import py15_assembler as A

RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]


@pytest.mark.parametrize("value", [
    None, 1, -7, 2**40, -2**40, 1.5, -0.25, 1 + 2j, b"ab", (1, (2,)), [1],
    {b"k": 2}, Ellipsis,
])
def test_a_constant_round_trips(value):
    code = A.module(RET, consts=(value,))
    assert load_pyc(A.pyc(code)).consts == (value,)


def test_a_code_object_round_trips_whole():
    code = A.projectile_module()
    assert load_pyc(A.pyc(code)) == code


def test_identifiers_are_text_and_bytecode_is_bytes():
    code = load_pyc(A.pyc(A.projectile_module()))
    assert code.names == ("App", "Create", "GetDamage")
    assert isinstance(code.code, bytes)
    assert isinstance(code.consts[0], Code15)


def test_only_the_python_15_magic_is_accepted():
    data = A.pyc(A.module(RET))
    assert is_py15_pyc(data)
    with pytest.raises(Py15FormatError, match="not Python 1.5"):
        load_pyc(b"\xa7\r\r\n" + data[4:])      # CPython 3.11's magic


def test_every_truncation_is_a_format_error():
    data = A.pyc(A.projectile_module())
    for n in range(len(data)):
        with pytest.raises(Py15FormatError):
            load_pyc(data[:n])


def test_a_negative_length_is_a_format_error_not_a_short_read():
    data = A.pyc(A.module(RET, consts=(b"abcd",)))
    at = data.index(b"s\x04\x00\x00\x00abcd")
    bad = data[:at + 1] + b"\xfc\xff\xff\xff" + data[at + 5:]
    with pytest.raises(Py15FormatError):
        load_pyc(bad)


def test_every_stock_pyc_reads():
    """BC ships every game script as 1.5 .pyc; the reader must take them
    all. (1201 files on the GOG install this was measured against.)"""
    from tests.helpers.bc_assets import require_game_dir

    scripts = require_game_dir("scripts")
    files = sorted(scripts.rglob("*.pyc"))
    assert len(files) > 1000, "expected the full retail script set"
    for path in files:
        code = load_pyc(path.read_bytes())
        assert code.name == "?", path      # 1.5 names every module code "?"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_py15_marshal.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'engine.py15'`.

- [ ] **Step 3: Create the package stub.** `engine/py15/__init__.py` needs a placeholder now so the package imports. Task 2 replaces it whole:

```python
"""Load mod scripts shipped only as Python 1.5 bytecode. Completed in Task 2."""
```

- [ ] **Step 4: Create `engine/py15/opcodes15.py`:**

```python
"""Python 1.5 opcode numbers, and the comparison table COMPARE_OP indexes.

An opcode at or above HAVE_ARGUMENT is followed by a 16-bit little-endian
argument; the others are one byte. Python 1.5 has no EXTENDED_ARG.
"""

HAVE_ARGUMENT = 90

NAMES = {
    0: "STOP_CODE", 1: "POP_TOP", 2: "ROT_TWO", 3: "ROT_THREE", 4: "DUP_TOP",
    10: "UNARY_POSITIVE", 11: "UNARY_NEGATIVE", 12: "UNARY_NOT",
    13: "UNARY_CONVERT", 15: "UNARY_INVERT",
    19: "BINARY_POWER", 20: "BINARY_MULTIPLY", 21: "BINARY_DIVIDE",
    22: "BINARY_MODULO", 23: "BINARY_ADD", 24: "BINARY_SUBTRACT",
    25: "BINARY_SUBSCR",
    30: "SLICE_0", 31: "SLICE_1", 32: "SLICE_2", 33: "SLICE_3",
    40: "STORE_SLICE_0", 41: "STORE_SLICE_1", 42: "STORE_SLICE_2",
    43: "STORE_SLICE_3",
    50: "DELETE_SLICE_0", 51: "DELETE_SLICE_1", 52: "DELETE_SLICE_2",
    53: "DELETE_SLICE_3",
    60: "STORE_SUBSCR", 61: "DELETE_SUBSCR",
    62: "BINARY_LSHIFT", 63: "BINARY_RSHIFT", 64: "BINARY_AND",
    65: "BINARY_XOR", 66: "BINARY_OR",
    70: "PRINT_EXPR", 71: "PRINT_ITEM", 72: "PRINT_NEWLINE",
    80: "BREAK_LOOP", 82: "LOAD_LOCALS", 83: "RETURN_VALUE", 85: "EXEC_STMT",
    87: "POP_BLOCK", 88: "END_FINALLY", 89: "BUILD_CLASS",
    90: "STORE_NAME", 91: "DELETE_NAME", 92: "UNPACK_TUPLE", 93: "UNPACK_LIST",
    95: "STORE_ATTR", 96: "DELETE_ATTR", 97: "STORE_GLOBAL",
    98: "DELETE_GLOBAL",
    100: "LOAD_CONST", 101: "LOAD_NAME", 102: "BUILD_TUPLE", 103: "BUILD_LIST",
    104: "BUILD_MAP", 105: "LOAD_ATTR", 106: "COMPARE_OP", 107: "IMPORT_NAME",
    108: "IMPORT_FROM",
    110: "JUMP_FORWARD", 111: "JUMP_IF_FALSE", 112: "JUMP_IF_TRUE",
    113: "JUMP_ABSOLUTE", 114: "FOR_LOOP", 116: "LOAD_GLOBAL",
    120: "SETUP_LOOP", 121: "SETUP_EXCEPT", 122: "SETUP_FINALLY",
    124: "LOAD_FAST", 125: "STORE_FAST", 126: "DELETE_FAST", 127: "SET_LINENO",
    130: "RAISE_VARARGS", 131: "CALL_FUNCTION", 132: "MAKE_FUNCTION",
    133: "BUILD_SLICE",
}

# COMPARE_OP's argument indexes this. 10 ("exception match") only ever
# appears inside an except clause, which the lifter refuses anyway.
COMPARE = ("<", "<=", "==", "!=", ">", ">=", "in", "not in", "is", "is not",
           "exception match", "BAD")

# Code-object flags (Include/compile.h, 1.5).
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008
```

- [ ] **Step 5: Create `engine/py15/marshal15.py`:**

```python
"""Read a Python 1.5 ``.pyc`` file: header, then one marshalled code object.

BC's ``stbc.exe`` embeds Python 1.5 (magic ``0x4E99``), and mod authors ship
modules as the ``.pyc`` it wrote. CPython 3 cannot read that format, and its
``marshal`` module never could: 1.5 code objects carry 16-bit fields and
floats as decimal text.

Pure data: nothing here executes the bytecode. Strings stay ``bytes`` except
identifiers (names, varnames, filename, code name), which are ASCII in every
file BC itself shipped and are decoded as latin-1 so no byte is ever lost.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# b"\x99\x4e\x0d\x0a": 20121 (0x4E99) little-endian, then "\r\n".
MAGIC = b"\x99N\r\n"


class Py15FormatError(ValueError):
    """The file is not a well-formed Python 1.5 .pyc."""


@dataclass(frozen=True)
class Code15:
    argcount: int
    nlocals: int
    stacksize: int
    flags: int
    code: bytes
    consts: tuple
    names: tuple
    varnames: tuple
    filename: str
    name: str
    firstlineno: int
    lnotab: bytes


class _Reader:
    def __init__(self, data: bytes, pos: int):
        self.data = data
        self.pos = pos

    def _take(self, n: int) -> bytes:
        end = self.pos + n
        if n < 0 or end > len(self.data):
            raise Py15FormatError("truncated at offset %d" % self.pos)
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def byte(self) -> int:
        return self._take(1)[0]

    def short(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def long(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def _float_text(self) -> float:
        return float(self._take(self.byte()).decode("ascii"))

    def _ident(self) -> str:
        value = self.object()
        if not isinstance(value, bytes):
            raise Py15FormatError("expected a string, got %r" % type(value))
        return value.decode("latin-1")

    def object(self):
        kind = chr(self.byte())
        if kind == "N":
            return None
        if kind == ".":
            return Ellipsis
        if kind == "i":
            return self.long()
        if kind == "I":
            return struct.unpack("<q", self._take(8))[0]
        if kind == "f":
            return self._float_text()
        if kind == "x":
            real = self._float_text()
            return complex(real, self._float_text())
        if kind == "l":
            n = self.long()
            value = 0
            for i in range(abs(n)):
                value |= struct.unpack("<H", self._take(2))[0] << (15 * i)
            return -value if n < 0 else value
        if kind == "s":
            return self._take(self.long())
        if kind in "([":
            items = tuple(self.object() for _ in range(self.long()))
            return items if kind == "(" else list(items)
        if kind == "{":
            out = {}
            while True:
                if self.data[self.pos:self.pos + 1] == b"0":
                    self.pos += 1
                    return out
                key = self.object()
                out[key] = self.object()
        if kind == "c":
            argcount, nlocals, stacksize, flags = (self.short() for _ in range(4))
            code = self.object()
            consts = self.object()
            names = tuple(n.decode("latin-1") for n in self.object())
            varnames = tuple(n.decode("latin-1") for n in self.object())
            filename = self._ident()
            name = self._ident()
            firstlineno = self.short()
            lnotab = self.object()
            return Code15(argcount, nlocals, stacksize, flags, code, consts,
                          names, varnames, filename, name, firstlineno, lnotab)
        raise Py15FormatError("unknown marshal type %r at offset %d"
                              % (kind, self.pos - 1))


def is_py15_pyc(data: bytes) -> bool:
    """True when `data` starts with the Python 1.5 .pyc magic."""
    return data[:4] == MAGIC


def load_pyc(data: bytes) -> Code15:
    """The module code object of a Python 1.5 .pyc file's bytes."""
    if not is_py15_pyc(data):
        raise Py15FormatError("not Python 1.5 bytecode (magic %s)" % data[:4].hex())
    reader = _Reader(data, 8)          # magic + 4-byte mtime
    try:
        code = reader.object()
    except Py15FormatError:
        raise
    except (ValueError, TypeError, AttributeError, IndexError,
            struct.error, RecursionError) as exc:
        # Corrupt input must surface as a format error, never as whatever
        # a half-read value happened to raise.
        raise Py15FormatError("malformed: %s: %s" % (type(exc).__name__, exc)) from exc
    if not isinstance(code, Code15):
        raise Py15FormatError("top-level object is not a code object")
    return code
```

- [ ] **Step 6: Create `tests/helpers/py15_assembler.py`:**

```python
"""Assemble Python 1.5 ``.pyc`` bytes for tests.

A test-only marshal WRITER, the inverse of engine/py15/marshal15.py. Every
fixture it builds is our own bytecode written by hand, so tests of the
lifter run on a machine with no Bridge Commander install and commit no BC or
mod content.

    pyc_bytes = pyc(module([("LOAD_CONST", 0), ("RETURN_VALUE",)],
                           consts=(None,)))
"""
from __future__ import annotations

import struct

from engine.py15 import opcodes15
from engine.py15.marshal15 import MAGIC, Code15

OPCODES = {name: num for num, name in opcodes15.NAMES.items()}

# CO_OPTIMIZED | CO_NEWLOCALS: what the 1.5 compiler sets on every def.
FUNCTION_FLAGS = 0x0003


def asm(instructions) -> bytes:
    """Bytecode for [("NAME",) or ("NAME", arg), ...]."""
    out = bytearray()
    for ins in instructions:
        num = OPCODES[ins[0]]
        out.append(num)
        if num >= opcodes15.HAVE_ARGUMENT:
            out += struct.pack("<H", ins[1])
    return bytes(out)


def function(name, instructions, *, consts=(None,), names=(), varnames=(),
             argcount=0, flags=FUNCTION_FLAGS, firstlineno=1) -> Code15:
    """A def's code object. consts[0] is the docstring slot (None or str),
    exactly as the 1.5 compiler lays it out."""
    return Code15(argcount, len(varnames), 10, flags, asm(instructions),
                  tuple(consts), tuple(names), tuple(varnames), "test.py",
                  name, firstlineno, b"")


def module(instructions, *, consts=(None,), names=()) -> Code15:
    return Code15(0, 0, 10, 0, asm(instructions), tuple(consts), tuple(names),
                  (), "test.py", "?", 1, b"")


def dumps(value) -> bytes:
    if value is None:
        return b"N"
    if value is Ellipsis:
        return b"."
    if isinstance(value, bool):
        raise TypeError("Python 1.5 has no bool")
    if isinstance(value, int):
        if -2**31 <= value < 2**31:
            return b"i" + struct.pack("<i", value)
        digits, n = [], abs(value)
        while n:
            digits.append(n & 0x7FFF)
            n >>= 15
        count = len(digits) if value > 0 else -len(digits)
        return (b"l" + struct.pack("<i", count)
                + b"".join(struct.pack("<H", d) for d in digits))
    if isinstance(value, float):
        text = repr(value).encode("ascii")
        return b"f" + bytes([len(text)]) + text
    if isinstance(value, complex):
        real, imag = (repr(v).encode("ascii") for v in (value.real, value.imag))
        return b"x" + bytes([len(real)]) + real + bytes([len(imag)]) + imag
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return b"s" + struct.pack("<i", len(value)) + bytes(value)
    if isinstance(value, (tuple, list)):
        tag = b"(" if isinstance(value, tuple) else b"["
        return tag + struct.pack("<i", len(value)) + b"".join(map(dumps, value))
    if isinstance(value, dict):
        return (b"{" + b"".join(dumps(k) + dumps(v) for k, v in value.items())
                + b"0")
    if isinstance(value, Code15):
        return (b"c" + struct.pack("<4h", value.argcount, value.nlocals,
                                   value.stacksize, value.flags)
                + dumps(value.code) + dumps(value.consts) + dumps(value.names)
                + dumps(value.varnames) + dumps(value.filename)
                + dumps(value.name) + struct.pack("<h", value.firstlineno)
                + dumps(value.lnotab))
    raise TypeError("cannot marshal %r" % type(value))


def pyc(code: Code15, mtime: int = 0) -> bytes:
    return MAGIC + struct.pack("<I", mtime) + dumps(code)


def projectile_module(damage=500.0):
    """The stock projectile shape in miniature, as straight-line 1.5 bytecode:

        import App
        def Create(pTorp):
            pTorp.SetDamage(GetDamage())
            import Multiplayer.SpeciesToTorp
            pTorp.SetNetType(Multiplayer.SpeciesToTorp.PHOTON)
            return 0
        def GetDamage():
            return <damage>
    """
    create = function(
        "Create",
        [("SET_LINENO", 3), ("LOAD_FAST", 0), ("LOAD_ATTR", 0),
         ("LOAD_GLOBAL", 1), ("CALL_FUNCTION", 0), ("CALL_FUNCTION", 1),
         ("POP_TOP",),
         ("SET_LINENO", 4), ("IMPORT_NAME", 2), ("STORE_FAST", 1),
         ("SET_LINENO", 5), ("LOAD_FAST", 0), ("LOAD_ATTR", 3),
         ("LOAD_FAST", 1), ("LOAD_ATTR", 4), ("LOAD_ATTR", 5),
         ("CALL_FUNCTION", 1), ("POP_TOP",),
         ("SET_LINENO", 6), ("LOAD_CONST", 1), ("RETURN_VALUE",),
         ("LOAD_CONST", 0), ("RETURN_VALUE",)],
        consts=(None, 0),
        names=("SetDamage", "GetDamage", "Multiplayer.SpeciesToTorp",
               "SetNetType", "SpeciesToTorp", "PHOTON"),
        varnames=("pTorp", "Multiplayer"), argcount=1, firstlineno=2)
    get_damage = function(
        "GetDamage",
        [("SET_LINENO", 8), ("LOAD_CONST", 1), ("RETURN_VALUE",),
         ("LOAD_CONST", 0), ("RETURN_VALUE",)],
        consts=(None, damage), firstlineno=7)
    return module(
        [("SET_LINENO", 1), ("IMPORT_NAME", 0), ("STORE_NAME", 0),
         ("SET_LINENO", 2), ("LOAD_CONST", 0), ("MAKE_FUNCTION", 0),
         ("STORE_NAME", 1),
         ("SET_LINENO", 7), ("LOAD_CONST", 1), ("MAKE_FUNCTION", 0),
         ("STORE_NAME", 2),
         ("LOAD_CONST", 2), ("RETURN_VALUE",)],
        consts=(create, get_damage, None),
        names=("App", "Create", "GetDamage"))
```

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest tests/unit/test_py15_marshal.py -v`
Expected: all PASS. `test_every_stock_pyc_reads` PASSes when `settings.json` resolves the BC install (it reads all 1201 stock files) and SKIPs only without one.

- [ ] **Step 8: Commit**

```bash
git add engine/py15/__init__.py engine/py15/opcodes15.py engine/py15/marshal15.py tests/helpers/py15_assembler.py tests/unit/test_py15_marshal.py
git commit -m "feat(py15): Python 1.5 .pyc reader and a test-only assembler

Reads the .pyc header and the 1.5 marshal stream (16-bit code-object
fields, floats as text). Every corrupt input surfaces as Py15FormatError.
Verified against all 1201 stock BC .pyc.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The lifter and the package API

**Files:**
- Create: `engine/py15/lift.py`
- Modify: `engine/py15/__init__.py` (replace the Task 1 stub whole)
- Test: `tests/unit/test_py15_lift.py`

**Interfaces:**
- Consumes: `marshal15.Code15`, `marshal15.Py15FormatError`, `marshal15.load_pyc`, `opcodes15.*` (Task 1); `py15_assembler.*` in tests.
- Produces:
  - `engine.py15.Py15Unsupported(ImportError)` with attributes `reason: str`, `opcode: str | None`, `offset: int | None`, `path: str | None`.
  - `engine.py15.lift(data: bytes) -> ast.Module`, with line numbers set and ready for `compile()`.
  - `engine.py15.lift_file(path) -> ast.Module` (sets `exc.path` on refusal).
  - `engine.py15.load_tree(path, fullname: str) -> ast.Module`: on refusal, prints one `[sdk-loader] …` line per path, ever, then re-raises.
  - `engine.py15._reported: set[str]`: the paths already reported. Tests clear it.

- [ ] **Step 1: Write the failing test** at `tests/unit/test_py15_lift.py`:

```python
"""engine.py15 lifts straight-line Python 1.5 bytecode to a Python 3 AST.

Every fixture is hand-assembled 1.5 bytecode (tests/helpers/py15_assembler),
so this file needs no BC install and contains no BC or mod content. The
expected output is always the AST the SDK loader would parse from the same
module's source -- that is the lifter's whole contract.
"""
import ast
import random
import textwrap

import pytest

from engine import py15
from engine.py15 import Py15Unsupported, lift
from engine.py15.marshal15 import Code15
from tests.helpers import py15_assembler as A

M, F = A.module, A.function
RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]


def _same(code, source):
    got = lift(A.pyc(code))
    want = ast.parse(textwrap.dedent(source))
    assert ast.dump(got) == ast.dump(want), ast.unparse(got)


def test_the_projectile_shape_lifts_to_its_source():
    _same(A.projectile_module(), """
        import App
        def Create(pTorp):
            pTorp.SetDamage(GetDamage())
            import Multiplayer.SpeciesToTorp
            pTorp.SetNetType(Multiplayer.SpeciesToTorp.PHOTON)
            return 0
        def GetDamage():
            return 500.0
    """)


def test_set_lineno_becomes_statement_line_numbers():
    tree = lift(A.pyc(A.projectile_module()))
    assert [s.lineno for s in tree.body] == [1, 2, 7]
    assert [s.lineno for s in tree.body[1].body] == [3, 4, 5, 6]


CASES = {
    # 1.5 has no None constant: it is LOAD_GLOBAL/LOAD_NAME "None".
    "none-is-a-name-in-1.5": (
        M([("LOAD_GLOBAL", 0), ("STORE_NAME", 1)] + RET, names=("None", "x")),
        "x = None"),
    "dict-literal": (
        M([("BUILD_MAP", 0),
           ("DUP_TOP",), ("LOAD_CONST", 1), ("ROT_TWO",), ("LOAD_CONST", 2),
           ("STORE_SUBSCR",),
           ("DUP_TOP",), ("LOAD_CONST", 3), ("ROT_TWO",), ("LOAD_CONST", 4),
           ("STORE_SUBSCR",),
           ("STORE_NAME", 0)] + RET,
          consts=(None, 1, "a", 2, "b"), names=("d",)),
        "d = {'a': 1, 'b': 2}"),
    # _fix_py2_syntax rewrites `.has_key(` in source; same result here.
    "has-key-call": (
        M([("LOAD_NAME", 0), ("LOAD_ATTR", 1), ("LOAD_CONST", 1),
           ("CALL_FUNCTION", 1), ("STORE_NAME", 2)] + RET,
          consts=(None, "a"), names=("d", "has_key", "x")),
        "x = d.__contains__('a')"),
    "print-statement": (
        M([("LOAD_CONST", 1), ("PRINT_ITEM",), ("LOAD_NAME", 0),
           ("PRINT_ITEM",), ("PRINT_NEWLINE",), ("PRINT_NEWLINE",)] + RET,
          consts=(None, "a"), names=("b",)),
        "print('a', b)\nprint()"),
    "function-docstring-and-global": (
        M([("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 0)] + RET,
          consts=(None, F("f", [("LOAD_CONST", 1), ("STORE_GLOBAL", 0),
                                ("LOAD_CONST", 2), ("RETURN_VALUE",)],
                          consts=("Doc.", 1, None), names=("g",))),
          names=("f",)),
        "def f():\n    'Doc.'\n    global g\n    g = 1"),
    "module-docstring": (
        M([("LOAD_CONST", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, "Module doc."), names=("__doc__",)),
        "'Module doc.'"),
    "default-arguments": (
        M([("LOAD_CONST", 1), ("LOAD_CONST", 2), ("MAKE_FUNCTION", 1),
           ("STORE_NAME", 0)] + RET,
          consts=(None, 2.0, F("f", [("LOAD_FAST", 1), ("RETURN_VALUE",)] + RET,
                               varnames=("a", "b"), argcount=2)),
          names=("f",)),
        "def f(a, b=2.0):\n    return b"),
    "keyword-call": (
        M([("LOAD_NAME", 0), ("LOAD_CONST", 1), ("LOAD_CONST", 2),
           ("CALL_FUNCTION", 256), ("POP_TOP",)] + RET,
          consts=(None, "x", 1), names=("f",)),
        "f(x=1)"),
    "stores-operators-compare": (
        M([("LOAD_NAME", 0), ("LOAD_NAME", 1), ("STORE_ATTR", 2),
           ("LOAD_CONST", 1), ("LOAD_NAME", 1), ("LOAD_CONST", 2),
           ("STORE_SUBSCR",),
           ("LOAD_NAME", 1), ("LOAD_CONST", 2), ("BINARY_SUBSCR",),
           ("LOAD_CONST", 3), ("BINARY_DIVIDE",), ("UNARY_NEGATIVE",),
           ("STORE_NAME", 3),
           ("LOAD_NAME", 3), ("LOAD_CONST", 4), ("COMPARE_OP", 7),
           ("STORE_NAME", 4)] + RET,
          consts=(None, 5, 0, 2.0, (1, 2)), names=("v", "o", "attr", "y", "z")),
        "o.attr = v\no[0] = 5\ny = -(o[0] / 2.0)\nz = y not in (1, 2)"),
    # The SDK loader reads source as utf-8 with errors="replace".
    "non-utf8-string-matches-the-source-path": (
        M([("LOAD_CONST", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, b"caf\xe9"), names=("s",)),
        "s = 'caf�'"),
    "list-in-tuple": (
        M([("LOAD_CONST", 1), ("LOAD_CONST", 2), ("BUILD_LIST", 2),
           ("BUILD_TUPLE", 1), ("STORE_NAME", 0)] + RET,
          consts=(None, 1, 2), names=("t",)),
        "t = ([1, 2],)"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_supported_construct_lifts_to_its_source(case):
    code, source = CASES[case]
    _same(code, source)


@pytest.mark.parametrize("opname", [
    "JUMP_IF_FALSE", "JUMP_IF_TRUE", "JUMP_FORWARD", "JUMP_ABSOLUTE",
    "FOR_LOOP", "SETUP_LOOP", "SETUP_EXCEPT", "SETUP_FINALLY", "BUILD_CLASS",
    "IMPORT_FROM", "UNPACK_TUPLE", "UNPACK_LIST", "EXEC_STMT", "UNARY_CONVERT",
    "RAISE_VARARGS", "DELETE_NAME", "SLICE_0", "LOAD_LOCALS", "PRINT_EXPR",
    "BUILD_SLICE",
])
def test_an_opcode_outside_the_subset_is_refused_by_name(opname):
    ins = (opname, 0) if A.OPCODES[opname] >= 90 else (opname,)
    code = M([("LOAD_CONST", 0), ins] + RET, names=("n",))
    with pytest.raises(Py15Unsupported) as info:
        lift(A.pyc(code))
    assert (info.value.opcode, info.value.offset) == (opname, 3)
    assert opname in str(info.value)


def _def(code_obj):
    return M([("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_NAME", 0)] + RET,
             consts=(None, code_obj), names=("f",))


SHAPES = {
    "*args": _def(F("f", RET, flags=A.FUNCTION_FLAGS | 0x4, varnames=("a",))),
    "lambda": _def(F("<lambda>", RET)),
    "nested function": _def(F(
        "f", [("LOAD_CONST", 1), ("MAKE_FUNCTION", 0), ("STORE_FAST", 0)] + RET,
        consts=(None, F("g", RET)), varnames=("g",))),
    "import alias": M([("IMPORT_NAME", 0), ("STORE_NAME", 1)] + RET,
                      names=("a.b", "x")),
    "DUP_TOP outside a dict literal": M(
        [("LOAD_CONST", 1), ("DUP_TOP",), ("STORE_NAME", 0),
         ("STORE_NAME", 1)] + RET, consts=(None, 1), names=("a", "b")),
    "module-level return": M([("LOAD_CONST", 1), ("RETURN_VALUE",)] + RET,
                             consts=(None, 1)),
    "trailing comma": M([("LOAD_CONST", 1), ("PRINT_ITEM",)] + RET,
                        consts=(None, 1)),
    "malformed bytecode": M([("LOAD_CONST", 7)] + RET),
}


@pytest.mark.parametrize("needle", sorted(SHAPES))
def test_a_shape_outside_the_subset_is_refused(needle):
    with pytest.raises(Py15Unsupported, match=needle.replace("*", r"\*")):
        lift(A.pyc(SHAPES[needle]))


def test_an_unknown_opcode_byte_is_refused():
    base = M(RET)
    code = Code15(base.argcount, base.nlocals, base.stacksize, base.flags,
                  bytes([200]) + base.code, base.consts, base.names,
                  base.varnames, base.filename, base.name, base.firstlineno,
                  base.lnotab)
    with pytest.raises(Py15Unsupported, match="unknown opcode 200"):
        lift(A.pyc(code))


def test_non_15_bytecode_is_refused():
    with pytest.raises(Py15Unsupported, match="not Python 1.5"):
        lift(b"\xa7\r\r\n" + A.pyc(M(RET))[4:])


def test_corrupt_bytecode_only_ever_raises_py15unsupported():
    """Truncated or bit-flipped files must give the one exception the loader
    turns into a log line -- never a struct.error/IndexError from deep in a
    half-read value -- and whatever still lifts must compile."""
    data = A.pyc(A.projectile_module())
    for n in range(len(data)):
        with pytest.raises(Py15Unsupported):
            lift(data[:n])
    rng = random.Random(1)
    for _ in range(2000):
        mutated = bytearray(data)
        mutated[rng.randrange(8, len(mutated))] = rng.randrange(256)
        try:
            tree = lift(bytes(mutated))
        except Py15Unsupported:
            continue
        compile(tree, "<fuzz>", "exec")


def test_the_lifted_projectile_runs_create_against_the_real_sdk():
    """Executed in the test harness: `import App` is our shim and
    Multiplayer.SpeciesToTorp is the real SDK module."""
    import Multiplayer.SpeciesToTorp as species

    namespace = {}
    exec(compile(lift(A.pyc(A.projectile_module(750.0))), "<lifted>", "exec"),
         namespace)
    calls = []

    class Recorder:
        def __getattr__(self, name):
            return lambda *args: calls.append((name,) + args)

    assert namespace["Create"](Recorder()) == 0
    assert calls == [("SetDamage", 750.0), ("SetNetType", species.PHOTON)]


@pytest.fixture
def _fresh_reports():
    py15._reported.clear()
    yield
    py15._reported.clear()


def test_load_tree_returns_the_module_ast(tmp_path, _fresh_reports, capsys):
    path = tmp_path / "Ok.pyc"
    path.write_bytes(A.pyc(A.projectile_module()))
    tree = py15.load_tree(path, "Tactical.Projectiles.Ok")
    assert isinstance(tree, ast.Module)
    assert "[sdk-loader]" not in capsys.readouterr().out


def test_load_tree_names_an_unloadable_file_exactly_once(tmp_path, _fresh_reports,
                                                         capsys):
    path = tmp_path / "Jumpy.pyc"
    path.write_bytes(A.pyc(M([("JUMP_FORWARD", 0)] + RET)))
    for _ in range(2):
        with pytest.raises(Py15Unsupported) as info:
            py15.load_tree(path, "Tactical.Projectiles.Jumpy")
        assert info.value.path == str(path)
    lines = [l for l in capsys.readouterr().out.splitlines() if "[sdk-loader]" in l]
    assert len(lines) == 1
    assert "Tactical.Projectiles.Jumpy" in lines[0]
    assert "JUMP_FORWARD" in lines[0]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_py15_lift.py -q`
Expected: collection error, `ImportError: cannot import name 'Py15Unsupported' from 'engine.py15'`.

- [ ] **Step 3: Create `engine/py15/lift.py`:**

```python
"""Turn straight-line Python 1.5 bytecode into a Python 3 ``ast.Module``.

The output is the tree the SDK loader would have built from the module's
source: ``ast.parse(_fix_py2_syntax(source))``. The loader then runs the same
compatibility transforms over it, so a ``.pyc`` loads exactly as its ``.py``
would.

Only a closed subset is accepted: code with no jump of any kind, no class, no
nested or variadic function, no ``from`` import. Every opcode or shape outside
it raises ``Py15Unsupported`` rather than guessing. The subset grows only when
stock modules exercise a new shape and the stock-corpus oracle test
(tests/unit/test_py15_stock_oracle.py) proves them identical to their SDK
source. Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md
"""
from __future__ import annotations

import ast

from . import opcodes15 as op
from .marshal15 import Code15, Py15FormatError, load_pyc


class Py15Unsupported(ImportError):
    """Python 1.5 bytecode this engine cannot load (yet)."""

    def __init__(self, reason, opcode=None, offset=None, path=None):
        self.reason = reason
        self.opcode = opcode
        self.offset = offset
        where = "" if opcode is None else " (%s at offset %d)" % (opcode, offset)
        super().__init__(reason + where, path=path)


_BINARY = {
    "BINARY_ADD": ast.Add, "BINARY_SUBTRACT": ast.Sub,
    "BINARY_MULTIPLY": ast.Mult, "BINARY_DIVIDE": ast.Div,
    "BINARY_MODULO": ast.Mod, "BINARY_POWER": ast.Pow,
    "BINARY_LSHIFT": ast.LShift, "BINARY_RSHIFT": ast.RShift,
    "BINARY_AND": ast.BitAnd, "BINARY_OR": ast.BitOr, "BINARY_XOR": ast.BitXor,
}
_UNARY = {
    "UNARY_NEGATIVE": ast.USub, "UNARY_POSITIVE": ast.UAdd,
    "UNARY_INVERT": ast.Invert, "UNARY_NOT": ast.Not,
}
_COMPARE = (ast.Lt, ast.LtE, ast.Eq, ast.NotEq, ast.Gt, ast.GtE, ast.In,
            ast.NotIn, ast.Is, ast.IsNot)


# Stack values that are not expressions. Consuming one as an expression is
# a shape outside the subset.
class _Import:
    def __init__(self, name):
        self.name = name


class _CodeRef:
    def __init__(self, code):
        self.code = code


class _Function:
    def __init__(self, code, defaults):
        self.code = code
        self.defaults = defaults


class _DictDup:
    """The DUP_TOP'd dict of a 1.5 dict literal: BUILD_MAP, then per pair
    DUP_TOP <value> ROT_TWO <key> STORE_SUBSCR."""

    def __init__(self, target):
        self.target = target


def _instructions(code: bytes):
    """(offset, name, arg) for every instruction; arg is None below
    HAVE_ARGUMENT."""
    i = 0
    while i < len(code):
        num = code[i]
        name = op.NAMES.get(num)
        if name is None:
            raise Py15Unsupported("unknown opcode %d" % num, "?", i)
        if num >= op.HAVE_ARGUMENT:
            if i + 2 >= len(code):
                raise Py15Unsupported("truncated instruction", name, i)
            yield i, name, code[i + 1] | (code[i + 2] << 8)
            i += 3
        else:
            yield i, name, None
            i += 1


def _text(raw: bytes) -> str:
    # The SDK loader reads source as utf-8 with errors="replace"; a string
    # constant must come out the way the same bytes would from a .py.
    return raw.decode("utf-8", errors="replace")


def _const(value):
    if isinstance(value, bytes):
        return ast.Constant(_text(value))
    if isinstance(value, tuple):
        return ast.Tuple([_const(v) for v in value], ast.Load())
    if value is None or isinstance(value, (int, float, complex)) \
            or value is Ellipsis:
        return ast.Constant(value)
    raise Py15Unsupported("constant of type %s" % type(value).__name__)


def _place(node, lineno):
    """Give a statement a one-line source span; fix_missing_locations then
    copies it onto every expression inside."""
    node.lineno = node.end_lineno = lineno
    node.col_offset = node.end_col_offset = 0
    return node


class _Lifter:
    def __init__(self, code: Code15, in_function: bool):
        self.co = code
        self.in_function = in_function
        self.stack = []
        self.body = []
        self.globals = []
        self.print_items = None
        self.lineno = code.firstlineno or 1

    # -- helpers ---------------------------------------------------------
    def emit(self, stmt):
        self.body.append(_place(stmt, self.lineno))

    def pop_expr(self, opcode, offset):
        if not self.stack:
            raise Py15Unsupported("stack underflow", opcode, offset)
        value = self.stack.pop()
        if not isinstance(value, ast.expr):
            raise Py15Unsupported("%s used as a value" % type(value).__name__,
                                  opcode, offset)
        return value

    def store(self, name, is_global, opcode, offset):
        value = self.stack.pop()
        if isinstance(value, _Import):
            if value.name.split(".")[0] != name:
                raise Py15Unsupported("import alias", opcode, offset)
            self.emit(ast.Import([ast.alias(value.name, None)]))
            return
        if isinstance(value, _Function):
            self.emit(self.function_def(name, value, opcode, offset))
            return
        if not isinstance(value, ast.expr):
            raise Py15Unsupported("%s stored" % type(value).__name__,
                                  opcode, offset)
        if (not self.in_function and name == "__doc__" and not self.body
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            self.emit(ast.Expr(value))           # the module docstring
            return
        if is_global and self.in_function and name not in self.globals:
            self.globals.append(name)
        self.emit(ast.Assign([ast.Name(name, ast.Store())], value))

    def function_def(self, name, func, opcode, offset):
        co = func.code
        if self.in_function:
            raise Py15Unsupported("nested function", opcode, offset)
        if co.name != name:
            raise Py15Unsupported("function %r stored as %r (lambda?)"
                                  % (co.name, name), opcode, offset)
        if co.flags & (op.CO_VARARGS | op.CO_VARKEYWORDS):
            raise Py15Unsupported("*args/**kwargs parameters", opcode, offset)
        params = list(co.varnames[:co.argcount])
        if not all(p.isidentifier() for p in params):
            raise Py15Unsupported("tuple parameters", opcode, offset)
        body = _Lifter(co, in_function=True).run()
        while (body and isinstance(body[-1], ast.Return)
               and isinstance(body[-1].value, ast.Constant)
               and body[-1].value.value is None):
            body.pop()
        # 1.5 always reserves co_consts[0] for the docstring (None if absent).
        if co.consts and isinstance(co.consts[0], bytes):
            body.insert(0, _place(ast.Expr(ast.Constant(_text(co.consts[0]))),
                                  co.firstlineno))
        if not body:
            body = [_place(ast.Pass(), co.firstlineno)]
        args = ast.arguments(posonlyargs=[], args=[ast.arg(p) for p in params],
                             vararg=None, kwonlyargs=[], kw_defaults=[],
                             kwarg=None, defaults=func.defaults)
        node = ast.FunctionDef(name=name, args=args, body=body,
                               decorator_list=[], returns=None,
                               type_comment=None)
        _place(node, co.firstlineno)
        node.end_lineno = max(co.firstlineno, max(s.end_lineno for s in body))
        return node

    # -- the walk --------------------------------------------------------
    def run(self):
        instrs = list(_instructions(self.co.code))
        names, varnames = self.co.names, self.co.varnames
        for index, (offset, name, arg) in enumerate(instrs):
            if name == "SET_LINENO":
                self.lineno = arg
            elif name == "LOAD_CONST":
                value = self.co.consts[arg]
                self.stack.append(_CodeRef(value) if isinstance(value, Code15)
                                  else _const(value))
            elif name in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST"):
                ident = varnames[arg] if name == "LOAD_FAST" else names[arg]
                # 1.5 has no None constant: it is a name lookup.
                self.stack.append(ast.Constant(None) if ident == "None"
                                  else ast.Name(ident, ast.Load()))
            elif name == "LOAD_ATTR":
                self.stack.append(ast.Attribute(self.pop_expr(name, offset),
                                                names[arg], ast.Load()))
            elif name in ("STORE_NAME", "STORE_GLOBAL"):
                self.store(names[arg], name == "STORE_GLOBAL", name, offset)
            elif name == "STORE_FAST":
                self.store(varnames[arg], False, name, offset)
            elif name == "STORE_ATTR":
                obj = self.pop_expr(name, offset)
                value = self.pop_expr(name, offset)
                self.emit(ast.Assign(
                    [ast.Attribute(obj, names[arg], ast.Store())], value))
            elif name == "STORE_SUBSCR":
                key = self.pop_expr(name, offset)
                obj = self.stack.pop() if self.stack else None
                value = self.pop_expr(name, offset)
                if isinstance(obj, _DictDup):
                    obj.target.keys.append(key)
                    obj.target.values.append(value)
                elif isinstance(obj, ast.expr):
                    self.emit(ast.Assign(
                        [ast.Subscript(obj, key, ast.Store())], value))
                else:
                    raise Py15Unsupported("subscript store target", name, offset)
            elif name == "BINARY_SUBSCR":
                key = self.pop_expr(name, offset)
                obj = self.pop_expr(name, offset)
                self.stack.append(ast.Subscript(obj, key, ast.Load()))
            elif name in _BINARY:
                right = self.pop_expr(name, offset)
                left = self.pop_expr(name, offset)
                self.stack.append(ast.BinOp(left, _BINARY[name](), right))
            elif name in _UNARY:
                self.stack.append(ast.UnaryOp(_UNARY[name](),
                                              self.pop_expr(name, offset)))
            elif name == "COMPARE_OP":
                if arg >= len(_COMPARE):
                    raise Py15Unsupported("comparison %r" % op.COMPARE[arg],
                                          name, offset)
                right = self.pop_expr(name, offset)
                left = self.pop_expr(name, offset)
                self.stack.append(ast.Compare(left, [_COMPARE[arg]()], [right]))
            elif name == "CALL_FUNCTION":
                keywords = []
                for _ in range(arg >> 8):
                    value = self.pop_expr(name, offset)
                    key = self.pop_expr(name, offset)
                    keywords.insert(0, ast.keyword(key.value, value))
                positional = [self.pop_expr(name, offset)
                              for _ in range(arg & 0xFF)][::-1]
                func = self.pop_expr(name, offset)
                # _fix_py2_syntax's `.has_key(` -> `.__contains__(`.
                if isinstance(func, ast.Attribute) and func.attr == "has_key":
                    func.attr = "__contains__"
                self.stack.append(ast.Call(func, positional, keywords))
            elif name in ("BUILD_TUPLE", "BUILD_LIST"):
                items = [self.pop_expr(name, offset) for _ in range(arg)][::-1]
                node = ast.Tuple if name == "BUILD_TUPLE" else ast.List
                self.stack.append(node(items, ast.Load()))
            elif name == "BUILD_MAP":
                if arg:
                    raise Py15Unsupported("BUILD_MAP with a size", name, offset)
                self.stack.append(ast.Dict([], []))
            elif name == "DUP_TOP":
                following = instrs[index + 1][1] if index + 1 < len(instrs) else ""
                if not (self.stack and isinstance(self.stack[-1], ast.Dict)
                        and not following.startswith("STORE_")):
                    raise Py15Unsupported("DUP_TOP outside a dict literal",
                                          name, offset)
                self.stack.append(_DictDup(self.stack[-1]))
            elif name == "ROT_TWO":
                if len(self.stack) < 2 or not isinstance(self.stack[-2], _DictDup):
                    raise Py15Unsupported("ROT_TWO outside a dict literal",
                                          name, offset)
                self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]
            elif name == "POP_TOP":
                self.emit(ast.Expr(self.pop_expr(name, offset)))
            elif name == "RETURN_VALUE":
                value = self.pop_expr(name, offset)
                if self.in_function:
                    self.emit(ast.Return(value))
                elif not (index == len(instrs) - 1
                          and isinstance(value, ast.Constant)
                          and value.value is None):
                    raise Py15Unsupported("module-level return", name, offset)
            elif name == "IMPORT_NAME":
                self.stack.append(_Import(names[arg]))
            elif name == "MAKE_FUNCTION":
                code = self.stack.pop() if self.stack else None
                if not isinstance(code, _CodeRef):
                    raise Py15Unsupported("MAKE_FUNCTION without code", name, offset)
                defaults = [self.pop_expr(name, offset) for _ in range(arg)][::-1]
                self.stack.append(_Function(code.code, defaults))
            elif name == "PRINT_ITEM":
                if self.print_items is None:
                    self.print_items = []
                self.print_items.append(self.pop_expr(name, offset))
            elif name == "PRINT_NEWLINE":
                self.emit(ast.Expr(ast.Call(ast.Name("print", ast.Load()),
                                            self.print_items or [], [])))
                self.print_items = None
            else:
                raise Py15Unsupported("unsupported opcode", name, offset)
        if self.stack:
            raise Py15Unsupported("values left on the stack")
        if self.print_items is not None:
            raise Py15Unsupported("print statement with a trailing comma")
        if self.globals:
            at = 1 if (self.body and isinstance(self.body[0], ast.Expr)
                       and isinstance(self.body[0].value, ast.Constant)) else 0
            self.body.insert(at, _place(ast.Global(self.globals),
                                        self.co.firstlineno))
        return self.body


def lift(data: bytes) -> ast.Module:
    """The Python 3 module AST for a Python 1.5 .pyc file's bytes."""
    try:
        code = load_pyc(data)
    except Py15FormatError as exc:
        raise Py15Unsupported("not a readable Python 1.5 .pyc: %s" % exc) from exc
    try:
        body = _Lifter(code, in_function=False).run()
    except (IndexError, KeyError, AttributeError, TypeError) as exc:
        # An operand index past its table, or a stack shape no real
        # compiler emits: corrupt or hand-made bytecode, not a new shape.
        raise Py15Unsupported("malformed bytecode: %s: %s"
                              % (type(exc).__name__, exc)) from exc
    tree = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(tree)
    return tree
```

- [ ] **Step 4: Replace `engine/py15/__init__.py` whole with:**

```python
"""Load mod scripts shipped only as Python 1.5 bytecode (``.pyc``).

BC's ``stbc.exe`` embeds Python 1.5 and imports ``.pyc`` directly, so some
mods ship no source (the LC Intrepid Pack's two torpedo projectiles). The
SDK loader in both tools/mission_harness.py and tests/conftest.py calls
``load_tree`` for a mod ``.pyc`` and then treats the tree exactly like one
parsed from source.

Nothing derived from a mod is ever written anywhere: the tree goes straight
to ``compile()``. Spec:
docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md
"""
from __future__ import annotations

import ast

from .lift import Py15Unsupported, lift
from .marshal15 import is_py15_pyc

__all__ = ["Py15Unsupported", "is_py15_pyc", "lift", "lift_file", "load_tree"]

# Paths already reported, so each unloadable file is named exactly once.
_reported: set = set()


def lift_file(path) -> ast.Module:
    """lift() on a file, with the path attached to any refusal."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        return lift(data)
    except Py15Unsupported as exc:
        exc.path = str(path)
        raise


def load_tree(path, fullname: str) -> ast.Module:
    """The module AST the SDK loader compiles for a mod ``.pyc``.

    On refusal, prints ONE production log line per file (not only under
    --developer: a player whose mod weapon turned into a photon deserves to
    be told why) and re-raises, so the import fails like any other and
    callers with a fallback (the projectile and torpedo-ammo resolvers)
    use it."""
    try:
        return lift_file(path)
    except Py15Unsupported as exc:
        key = str(path)
        if key not in _reported:
            _reported.add(key)
            print("[sdk-loader] mod module %s (%s) is Python 1.5 bytecode this "
                  "engine cannot load yet: %s; importers fall back where they "
                  "can" % (fullname, key, exc), flush=True)
        raise
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/unit/test_py15_lift.py tests/unit/test_py15_marshal.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/py15/lift.py engine/py15/__init__.py tests/unit/test_py15_lift.py
git commit -m "feat(py15): lift straight-line Python 1.5 bytecode to a Python 3 AST

Emits the tree the SDK loader would parse from the module's source, and
refuses every opcode or shape outside a closed subset with Py15Unsupported.
That covers jumps, classes, nested and variadic defs, lambda, from-imports
and aliased imports. load_tree prints one [sdk-loader] line per refused file.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The stock-corpus oracle

This test proves the lifter correct. Every stock `.pyc` it accepts must match its SDK source. The test is the gate for growing the subset later.

**Files:**
- Test: `tests/unit/test_py15_stock_oracle.py`

**Interfaces:**
- Consumes: `engine.py15.lift_file`, `engine.py15.Py15Unsupported` (Task 2); `tools.mission_harness._fix_py2_syntax`; `engine.paths.sdk_scripts()`; `tests.helpers.bc_assets.require_game_dir`.
- Produces: `ACCEPTED_FLOOR = 514`, the ratchet later work raises.

- [ ] **Step 1: Write the test** at `tests/unit/test_py15_stock_oracle.py`:

```python
"""The lifter is right on every stock module it accepts.

Retail BC ships all its game scripts as Python 1.5 .pyc only (1201 on the
GOG install), and the SDK ships each one's .py. For every stock .pyc that
engine.py15 accepts, the lifted AST must equal what the SDK loader parses
from the .py -- ast.parse(_fix_py2_syntax(source)) -- after this CLOSED
normalisation, each item being something 1.5 bytecode cannot carry:

  * `pass` statements;
  * bare string statements other than a docstring (compiled away);
  * a function's trailing `return` / `return None` (the implicit return);
  * `global` names a function never assigns (no bytecode trace); the
    remaining names merge into one sorted declaration after the docstring.

Never widen that list to make a mismatch go away: a mismatch is a lifter bug
until proven otherwise.

The floor is a ratchet. Raise ACCEPTED_FLOOR when the subset grows (the
subset only grows when this test proves the new shape); never lower it.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §7 T2.
"""
import ast
import warnings

import pytest

from engine import paths, py15
from tests.helpers.bc_assets import require_game_dir
from tools.mission_harness import _fix_py2_syntax

ACCEPTED_FLOOR = 514


def _is_doc(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _norm_body(body, is_function):
    body = [s for s in body if not isinstance(s, ast.Pass)]
    doc = []
    if body and _is_doc(body[0]):
        doc, body = [body[0]], body[1:]
    body = [s for s in body if not _is_doc(s)]
    if is_function:
        while body and isinstance(body[-1], ast.Return) and (
                body[-1].value is None
                or (isinstance(body[-1].value, ast.Constant)
                    and body[-1].value.value is None)):
            body.pop()
    return doc + body


def _normalise(tree):
    tree.body = _norm_body(tree.body, False)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        stored = {n.id for n in ast.walk(fn)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        declared = sorted({g for n in ast.walk(fn) if isinstance(n, ast.Global)
                           for g in n.names} & stored)
        body = _norm_body([s for s in fn.body if not isinstance(s, ast.Global)],
                          True)
        if declared:
            body.insert(1 if body and _is_doc(body[0]) else 0,
                        ast.Global(declared))
        fn.body = body or [ast.Pass()]
    return ast.dump(tree)


def _sdk_tree(path):
    # Exactly what the SDK loader does to a .py before its AST transforms.
    source = path.read_text(encoding="utf-8", errors="replace").expandtabs(4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(_fix_py2_syntax(source), filename=str(path))


@pytest.fixture(scope="module")
def oracle():
    game_scripts = require_game_dir("scripts")
    sdk = paths.sdk_scripts()
    accepted, wrong = [], []
    for pyc in sorted(game_scripts.rglob("*.pyc")):
        rel = pyc.relative_to(game_scripts).with_suffix(".py")
        if not (sdk / rel).is_file():
            continue
        try:
            lifted = py15.lift_file(pyc)
        except py15.Py15Unsupported:
            continue
        compile(lifted, str(pyc), "exec")
        accepted.append(rel.as_posix())
        if _normalise(lifted) != _normalise(_sdk_tree(sdk / rel)):
            wrong.append(rel.as_posix())
    return game_scripts, accepted, wrong


def test_no_accepted_stock_module_differs_from_its_source(oracle):
    _, _, wrong = oracle
    assert wrong == []


def test_the_accepted_count_never_drops_below_the_floor(oracle):
    _, accepted, _ = oracle
    assert len(accepted) >= ACCEPTED_FLOOR, (
        "the lifter accepts %d stock modules, below the %d floor"
        % (len(accepted), ACCEPTED_FLOOR))


def test_every_stock_projectile_is_accepted(oracle):
    game_scripts, accepted, _ = oracle
    projectiles = sorted(
        p.relative_to(game_scripts).with_suffix(".py").as_posix()
        for p in (game_scripts / "Tactical" / "Projectiles").glob("*.pyc"))
    assert projectiles, "no stock projectiles found"
    assert set(projectiles) <= set(accepted)


def test_the_normalisation_still_sees_real_differences():
    """Guard against a vacuous pass: a normaliser that flattened everything
    would make the oracle agree with anything."""
    def norm(src):
        return _normalise(ast.parse(src))

    assert norm("x = 1") != norm("x = 2")
    assert norm("def f():\n    return 0") != norm("def f():\n    return 1")
    # A `global` that IS assigned survives normalisation...
    assert norm("def f():\n    global g\n    g = 1") != norm("def f():\n    g = 1")
    # ...one that is only read does not.
    assert norm("def f():\n    global g\n    return g") == norm("def f():\n    return g")
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/unit/test_py15_stock_oracle.py -v`
Expected: 4 PASS in a few seconds (the whole corpus lifts in ~1.5 s). The lifter already exists, so this test is a **verification** task, not red-green.

- [ ] **Step 3: Prove the oracle can fail.** Back up the lifter, break one rule, watch the oracle catch it, restore, and prove the restore:

```bash
cp engine/py15/lift.py /tmp/lift_py_bak
```

In `engine/py15/lift.py`, change `self.stack.append(ast.Constant(None) if ident == "None"` to `self.stack.append(ast.Constant(0) if ident == "None"`.

Run: `uv run pytest tests/unit/test_py15_stock_oracle.py -q`
Expected: FAIL in `test_no_accepted_stock_module_differs_from_its_source`, listing modules.

```bash
cp /tmp/lift_py_bak engine/py15/lift.py
diff engine/py15/lift.py /tmp/lift_py_bak && echo RESTORED
uv run pytest tests/unit/test_py15_stock_oracle.py -q
```

Expected: `RESTORED`, then 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_py15_stock_oracle.py
git commit -m "test(py15): stock-corpus oracle — every accepted stock .pyc equals its SDK source

514 of the 1201 retail .pyc lift; all match their SDK .py's AST under a
closed normalisation of what 1.5 bytecode cannot carry. The floor is a
ratchet.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire `.pyc` into both SDK finders and loaders

**Files:**
- Modify: `tools/mission_harness.py`: add `_module_tree` above `class _SDKLoader` (~line 442); `_SDKLoader.exec_module` (~line 455); `_mod_override_spec` suffix tuple (~line 534); bare-name mod-index loop at the end of `_SDKFinder.find_spec` (~line 691).
- Modify: `tests/conftest.py`: the same four places (`_SDKLoader` ~line 466, `exec_module` ~line 481, `_mod_override_spec` ~line 562, bare-name loop ~line 731).
- Modify: `tests/unit/test_sdk_finder_twins_stay_in_sync.py`: parametrize list.
- Test: `tests/unit/test_mods_pyc_finder.py`

**Interfaces:**
- Consumes: `engine.py15.load_tree`, `engine.py15.Py15Unsupported`, `engine.py15._reported` (Task 2); `tests.helpers.py15_assembler` (Task 1); `engine.mods.build_index`, `engine.mods.configure`.
- Produces: `_module_tree(path, fullname) -> ast.Module` in both twins, with AST-identical bodies.

- [ ] **Step 1: Write the failing test** at `tests/unit/test_mods_pyc_finder.py`:

```python
"""A mod `.pyc` with no `.py` resolves and loads through BOTH SDK finders.

tests/conftest.py owns the finder the suite imports through and
tools/mission_harness.py the one the game uses; every case here runs against
each, because a rule that holds in only one is green tests, wrong game.

Fixtures are hand-assembled Python 1.5 bytecode (tests/helpers/
py15_assembler) in a temporary mods tree -- no BC or mod content.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §4.3-4.4.
"""
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

import tools.mission_harness as harness
from engine import mods, py15
from tests.helpers import py15_assembler as A

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]
JUMPY = A.module([("JUMP_FORWARD", 0)] + RET)


def _conftest_module():
    """The already-imported tests/conftest.py (never re-import it)."""
    target = str(PROJECT_ROOT / "tests" / "conftest.py")
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) == target:
            return mod
    raise AssertionError("tests/conftest.py is not in sys.modules")


_FINDERS = {
    "conftest": lambda: _conftest_module()._SDKFinder(),
    "mission_harness": lambda: harness._SDKFinder(),
}


@pytest.fixture(params=sorted(_FINDERS))
def finder(request):
    return _FINDERS[request.param]()


@pytest.fixture(autouse=True)
def _isolated():
    mods.configure(None)
    py15._reported.clear()
    yield
    mods.configure(None)
    py15._reported.clear()


def _mod_file(root: Path, mod: str, rel: str, data) -> Path:
    path = root / mod / "Scripts" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data)
    return path


def _index(root: Path) -> None:
    mods.configure(mods.build_index(root))


def _load(finder, name):
    """find_spec + exec, without registering anything in sys.modules."""
    spec = finder.find_spec(name, None)
    assert spec is not None, name
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return spec, module


def test_a_pyc_only_mod_module_loads(finder, tmp_path, capsys):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessPycOnly.pyc",
              A.pyc(A.projectile_module(750.0)))
    _index(tmp_path)
    spec, module = _load(finder, "Tactical.Projectiles._DauntlessPycOnly")
    assert spec.origin.endswith("_DauntlessPycOnly.pyc")
    assert module.GetDamage() == 750.0
    assert "[sdk-loader]" not in capsys.readouterr().out


def test_an_upper_case_pyc_extension_loads(finder, tmp_path):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessUpper.PYC",
              A.pyc(A.projectile_module(5.0)))
    _index(tmp_path)
    _, module = _load(finder, "Tactical.Projectiles._DauntlessUpper")
    assert module.GetDamage() == 5.0


def test_a_py_beats_a_pyc_in_the_same_mod(finder, tmp_path):
    rel = "Tactical/Projectiles/_DauntlessBoth"
    _mod_file(tmp_path, "M", rel + ".pyc", A.pyc(A.projectile_module(750.0)))
    _mod_file(tmp_path, "M", rel + ".py", "def GetDamage():\n    return 1.0\n")
    _index(tmp_path)
    spec, module = _load(finder, "Tactical.Projectiles._DauntlessBoth")
    assert spec.origin.endswith(".py")
    assert module.GetDamage() == 1.0


def test_a_py_in_one_mod_beats_a_pyc_in_another(finder, tmp_path):
    rel = "Tactical/Projectiles/_DauntlessTwoMods"
    _mod_file(tmp_path, "A", rel + ".pyc", A.pyc(A.projectile_module(750.0)))
    _mod_file(tmp_path, "B", rel + ".py", "def GetDamage():\n    return 1.0\n")
    _index(tmp_path)
    spec, _ = _load(finder, "Tactical.Projectiles._DauntlessTwoMods")
    assert spec.origin.endswith(".py")


def test_a_mod_pyc_beats_the_stock_sdk_py(finder, tmp_path):
    """BC: the mod's .pyc overwrites the retail .pyc, and no stock .py
    exists to recompile from. find_spec only -- the stock module is not
    executed or replaced."""
    hit = _mod_file(tmp_path, "M", "Tactical/Projectiles/PhotonTorpedo.pyc",
                    A.pyc(A.projectile_module()))
    _index(tmp_path)
    spec = finder.find_spec("Tactical.Projectiles.PhotonTorpedo", None)
    assert spec.origin == str(hit)


def test_a_bare_name_import_finds_a_pyc_in_a_mod_subdirectory(finder, tmp_path):
    hit = _mod_file(tmp_path, "M", "Custom/_DauntlessBarePyc.pyc",
                    A.pyc(A.projectile_module()))
    _index(tmp_path)
    spec = finder.find_spec("_DauntlessBarePyc", None)
    assert spec is not None and spec.origin == str(hit)


def test_an_unloadable_pyc_fails_loudly_once(finder, tmp_path, capsys):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessJumpy.pyc",
              A.pyc(JUMPY))
    _index(tmp_path)
    for _ in range(2):
        with pytest.raises(py15.Py15Unsupported):
            _load(finder, "Tactical.Projectiles._DauntlessJumpy")
    lines = [l for l in capsys.readouterr().out.splitlines()
             if "[sdk-loader]" in l]
    assert len(lines) == 1
    assert "Tactical.Projectiles._DauntlessJumpy" in lines[0]
    assert "JUMP_FORWARD" in lines[0]


def test_an_unloadable_pyc_shadowing_stock_does_not_fall_back_to_stock(
        finder, tmp_path):
    """Spec decision D1: the mod's version was asked for; a silent stock
    substitute is not the caller's choice to make."""
    hit = _mod_file(tmp_path, "M", "Tactical/Projectiles/PhotonTorpedo.pyc",
                    A.pyc(JUMPY))
    _index(tmp_path)
    spec = finder.find_spec("Tactical.Projectiles.PhotonTorpedo", None)
    assert spec.origin == str(hit)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(py15.Py15Unsupported):
        spec.loader.exec_module(module)


def test_a_non_15_pyc_is_refused(finder, tmp_path):
    _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessPy311.pyc",
              b"\xa7\r\r\n" + b"\x00" * 12)
    _index(tmp_path)
    with pytest.raises(py15.Py15Unsupported, match="not Python 1.5"):
        _load(finder, "Tactical.Projectiles._DauntlessPy311")


def test_reload_re_lifts_the_pyc(tmp_path):
    """SDK loadspacehelper.py calls reload(mod) on hardpoint modules; a
    .pyc-backed module must survive it. Real import machinery, so this goes
    through the suite's own (conftest) finder."""
    name = "Tactical.Projectiles._DauntlessReload"
    path = _mod_file(tmp_path, "M", "Tactical/Projectiles/_DauntlessReload.pyc",
                     A.pyc(A.projectile_module(1.0)))
    _index(tmp_path)
    try:
        module = importlib.import_module(name)
        assert module.GetDamage() == 1.0
        path.write_bytes(A.pyc(A.projectile_module(2.0)))
        assert importlib.reload(module).GetDamage() == 2.0
    finally:
        sys.modules.pop(name, None)
```

- [ ] **Step 2: Add `_module_tree` to the twin-parity test.** In `tests/unit/test_sdk_finder_twins_stay_in_sync.py`, replace

```python
@pytest.mark.parametrize("helper", ["_mods_may_override", "_mod_override_spec"])
```

with

```python
@pytest.mark.parametrize("helper", ["_mods_may_override", "_mod_override_spec",
                                    "_module_tree"])
```

- [ ] **Step 3: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_mods_pyc_finder.py tests/unit/test_sdk_finder_twins_stay_in_sync.py -q`
Expected: FAILs. `find_spec` returns `None` for the `.pyc`-only modules (`AssertionError: Tactical.Projectiles._DauntlessPycOnly`), and the parity test fails with `AttributeError: … has no attribute '_module_tree'`. These tests pass already: `test_a_py_beats_a_pyc_in_the_same_mod` and `test_a_py_in_one_mod_beats_a_pyc_in_another`, because `.py` already wins.

- [ ] **Step 4: `tools/mission_harness.py`: add `_module_tree`** immediately above `class _SDKLoader(importlib.abc.Loader):`:

```python
def _module_tree(path, fullname):
    """The AST an SDK-loader file compiles from: parsed from source, or --
    for a mod-provided Python 1.5 `.pyc` with no `.py` -- lifted from its
    bytecode by engine.py15 into the tree that source would have parsed to.
    Only _mod_override_spec ever hands this a `.pyc`; stock always loads
    from SDK source. Mirrors tests/conftest._module_tree."""
    if str(path).lower().endswith(".pyc"):
        from engine import py15
        return py15.load_tree(path, fullname)
    with open(path, encoding="utf-8", errors="replace") as f:
        source = f.read()
    source = _fix_py2_syntax(source.expandtabs(4))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source, filename=path)
```

- [ ] **Step 5: `tools/mission_harness.py`: use it in `_SDKLoader.exec_module`.** Replace

```python
    def exec_module(self, module):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        source = source.expandtabs(4)
        source = _fix_py2_syntax(source)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=self.path)
            tree = _MoveGlobalsToTop().visit(tree)
```

with

```python
    def exec_module(self, module):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = _module_tree(self.path, module.__name__)
            tree = _MoveGlobalsToTop().visit(tree)
```

The rest of `exec_module` stays exactly as it is: the remaining transforms, `compile`, the `apply`/`reload`/`BORG` injections, `also_register_as` and the `sdk_overrides` pass.

- [ ] **Step 6: `tests/conftest.py`: add the twin `_module_tree`** immediately above `class _SDKLoader(importlib.abc.Loader):`. Its body is identical; only the docstring's last sentence names the other twin:

```python
def _module_tree(path, fullname):
    """The AST an SDK-loader file compiles from: parsed from source, or --
    for a mod-provided Python 1.5 `.pyc` with no `.py` -- lifted from its
    bytecode by engine.py15 into the tree that source would have parsed to.
    Only _mod_override_spec ever hands this a `.pyc`; stock always loads
    from SDK source. Mirrors tools/mission_harness._module_tree."""
    if str(path).lower().endswith(".pyc"):
        from engine import py15
        return py15.load_tree(path, fullname)
    with open(path, encoding="utf-8", errors="replace") as f:
        source = f.read()
    source = _fix_py2_syntax(source.expandtabs(4))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(source, filename=path)
```

- [ ] **Step 7: `tests/conftest.py`: use it in `_SDKLoader.exec_module`.** Replace

```python
    def exec_module(self, module):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        source = source.expandtabs(4)
        source = _fix_py2_syntax(source)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=self.path)
        tree = _MoveGlobalsToTop().visit(tree)
```

with

```python
    def exec_module(self, module):
        tree = _module_tree(self.path, module.__name__)
        tree = _MoveGlobalsToTop().visit(tree)
```

- [ ] **Step 8: Both twins: the `.pyc` suffixes in `_mod_override_spec`.** In **each** of `tools/mission_harness.py` and `tests/conftest.py`, replace

```python
    for suffix, is_pkg in ((".py", False), ("/__init__.py", True)):
```

with

```python
    # A mod's .py always beats a .pyc for the same module (Python 1.5's own
    # rule when the two disagree), so the bytecode arms come last. Only mod
    # files ever reach engine.py15 -- see _module_tree.
    for suffix, is_pkg in ((".py", False), ("/__init__.py", True),
                           (".pyc", False), ("/__init__.pyc", True)):
```

- [ ] **Step 9: Both twins: the bare-name mod-index loop accepts `.pyc`.** In **each** twin, at the end of `_SDKFinder.find_spec`, replace

```python
                if _key.rpartition("/")[2] != fullname.lower() + ".py":
                    continue
                _logical = _key[:-len(".py")]
```

with

```python
                _leaf = _key.rpartition("/")[2]
                if _leaf == fullname.lower() + ".py":
                    _logical = _key[:-len(".py")]
                elif _leaf == fullname.lower() + ".pyc":
                    _logical = _key[:-len(".pyc")]
                else:
                    continue
```

(`_mod_override_spec` then tries `.py` before `.pyc` for that logical path, so a mod shipping both still loads the `.py`.)

- [ ] **Step 10: Run the tests and watch them pass**

Run: `uv run pytest tests/unit/test_mods_pyc_finder.py tests/unit/test_sdk_finder_twins_stay_in_sync.py tests/unit/test_mods_sdk_finder.py -v`
Expected: all PASS. Each `test_mods_pyc_finder` case runs twice, `[conftest]` and `[mission_harness]`.

- [ ] **Step 11: Run the whole pytest suite** to prove the source path is unchanged for every SDK and mod `.py`:

Run: `uv run pytest -q`
Expected: no new failures. The suite takes several minutes and needs ~290 MB.

- [ ] **Step 12: Commit**

```bash
git add tools/mission_harness.py tests/conftest.py tests/unit/test_sdk_finder_twins_stay_in_sync.py tests/unit/test_mods_pyc_finder.py
git commit -m "feat(mods): SDK finders load a mod's .pyc-only module through engine.py15

Both twins: _mod_override_spec tries .pyc after .py and /__init__.py, the
bare-name mod-index branch accepts a .pyc leaf, and _SDKLoader gets its
tree from the shared _module_tree(), so a lifted module takes exactly the
source pipeline from _MoveGlobalsToTop on. Stock lookups are unchanged.
The twin-parity test now covers _module_tree.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The LC Intrepid's torpedoes, end to end

**Files:**
- Test: `tests/unit/test_lc_intrepid_pyc_projectiles.py`
- Modify: `engine/appc/weapon_subsystems.py:351-356` (`_resolve_projectile_module` docstring only)
- Modify: `tests/unit/test_torpedo_script_fallback.py:3-7` (module docstring only)

**Interfaces:**
- Consumes: Task 4's wiring; `weapon_subsystems._resolve_projectile_module`, `weapon_subsystems._reset_projectile_module_cache`, `ships._resolve_torpedo_ammo(ts_prop, slot)`, `TorpedoAmmoType.GetTorpedoScript()/GetAmmoName()/_launch_speed`, `projectiles._active: list[Torpedo]`, and the `Torpedo` fields `_damage`, `_guidance_lifetime`, `_max_angular_accel`, `_ttl`.
- Produces: nothing new.

- [ ] **Step 1: Write the test** at `tests/unit/test_lc_intrepid_pyc_projectiles.py`:

```python
"""The LC Intrepid's own torpedoes load from their Python 1.5 .pyc.

The pack ships ZZ_VoyPhoton and ZZ_Tricobalt ONLY as .pyc (magic 0x4E99).
They used to fall back to the stock photon; engine/py15 now lifts them.

Reads the pack from the project's gitignored mods/ and skips without it.
Every assertion compares against the MOD MODULE'S OWN getters, never a
literal: no value derived from mod content may be committed to this repo.
Spec: docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md §7 T5.
"""
import importlib
import sys

import pytest

import App  # noqa: F401  (SDK shim import order)
from engine import mods
from engine.appc import projectiles, weapon_subsystems
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from tests.helpers.bc_assets import PROJECT_ROOT

PACK = PROJECT_ROOT / "mods" / "LC Intrepid Pack"
SCRIPTS = ["Tactical.Projectiles.ZZ_VoyPhoton",
           "Tactical.Projectiles.ZZ_Tricobalt"]


@pytest.fixture(autouse=True)
def intrepid_index():
    probe = PACK / "scripts" / "Tactical" / "Projectiles" / "ZZ_VoyPhoton.pyc"
    if not probe.is_file():
        pytest.skip("LC Intrepid Pack not installed in mods/")
    mods.configure(mods.build_index(PROJECT_ROOT / "mods"))
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()
    yield
    for name in SCRIPTS:
        sys.modules.pop(name, None)
    weapon_subsystems._reset_projectile_module_cache()
    projectiles._active.clear()
    mods.configure(None)


def _armed_tube(script) -> TorpedoTube:
    from engine.appc.ships import ShipClass_Create

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship._target = None
    ship._target_subsystem = None

    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, script)
    system.SetProperty(prop)
    system._parent_ship = ship
    ship._torpedo_system = system

    tube = TorpedoTube("Forward Torpedo 1")
    tube._reload_delay = 40.0
    tube._immediate_delay = 0.25
    tube._max_ready = 1
    tube._num_ready = 1
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return tube


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_mod_projectile_loads_from_its_pyc(name, capsys):
    mod = importlib.import_module(name)
    origin = mod.__spec__.origin
    assert origin.lower().endswith(".pyc")
    assert str(PACK) in origin
    assert "[sdk-loader]" not in capsys.readouterr().out
    # ...and the launch resolver hands back THIS module, not the photon.
    assert weapon_subsystems._resolve_projectile_module(name) is mod


@pytest.mark.parametrize("name", SCRIPTS)
def test_its_ammo_type_comes_from_the_mod_module(name):
    from engine.appc.ships import _resolve_torpedo_ammo

    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, name)
    ammo = _resolve_torpedo_ammo(prop, 0)
    mod = importlib.import_module(name)
    assert ammo.GetTorpedoScript() == name
    assert ammo.GetAmmoName() == mod.GetName()
    assert ammo._launch_speed == float(mod.GetLaunchSpeed())


@pytest.mark.parametrize("name", SCRIPTS)
def test_a_fired_torpedo_carries_the_mod_modules_values(name):
    tube = _armed_tube(name)
    assert tube.Fire(target=None, offset=None) is True
    assert len(projectiles._active) == 1
    torp = projectiles._active[0]
    mod = importlib.import_module(name)
    assert torp._damage == float(mod.GetDamage())
    assert torp._guidance_lifetime == float(mod.GetGuidanceLifetime())
    assert torp._max_angular_accel == float(mod.GetMaxAngularAccel())
    assert torp._ttl == float(mod.GetLifetime())
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/unit/test_lc_intrepid_pyc_projectiles.py -v`
Expected: 6 PASS (Task 4 already did the work). If they SKIP, the Setup `mods/` copy is missing: fix that, don't accept the skip.

- [ ] **Step 3: Prove it guards the bug.** Back up conftest, remove the `.pyc` arms, watch the test fail, restore, and prove the restore:

```bash
cp tests/conftest.py /tmp/conftest_bak
```

In `tests/conftest.py` `_mod_override_spec`, delete `(".pyc", False), ("/__init__.pyc", True)` from the suffix tuple.

Run: `uv run pytest tests/unit/test_lc_intrepid_pyc_projectiles.py -q`
Expected: FAILs. The modules don't import, the ammo has no script, and the torpedo carries the photon's values.

```bash
cp /tmp/conftest_bak tests/conftest.py
diff tests/conftest.py /tmp/conftest_bak && echo RESTORED
uv run pytest tests/unit/test_lc_intrepid_pyc_projectiles.py -q
```

Expected: `RESTORED`, then 6 PASS.

- [ ] **Step 4: Correct the stale docstring in `engine/appc/weapon_subsystems.py`** (`_resolve_projectile_module`). Replace

```
    Community ship mods routinely ship projectile modules as Python 1.5
    `.pyc` with NO source — the LC Intrepid pack's ZZ_VoyPhoton and
    ZZ_Tricobalt are both magic 0x4E99, the Python `stbc.exe` embeds — and
    CPython cannot load those. The mod overlay does index the `.pyc`, but the
    SDK finders only ever look for `.py` / `/__init__.py`, so the import
    raises either way.
```

with

```
    Community ship mods can ship projectile modules as Python 1.5 `.pyc`
    with NO source — the LC Intrepid pack's ZZ_VoyPhoton and ZZ_Tricobalt
    are magic 0x4E99, the Python `stbc.exe` embeds. Those now load: both SDK
    finders take a mod `.pyc` and engine/py15 lifts straight-line 1.5
    bytecode into the AST its source would have parsed to. What still lands
    here is bytecode the lifter refuses (it prints one `[sdk-loader]` line
    naming the module) or any other import failure.
```

Leave the rest of the docstring (the DELIBERATE INFIDELITY paragraph onward) as it is.

- [ ] **Step 5: Correct the stale docstring in `tests/unit/test_torpedo_script_fallback.py`.** Replace

```
Community ship mods routinely ship their projectile modules as Python 1.5
`.pyc` with no source — the LC Intrepid pack's `ZZ_VoyPhoton` and
`ZZ_Tricobalt` are both magic 0x4E99, the Python that `stbc.exe` embeds.
CPython cannot load those, so `import_module` raises and the tube used to
`return` out of `_spawn_torpedo` in silence.
```

with

```
Community ship mods can ship their projectile modules as Python 1.5 `.pyc`
with no source. engine/py15 now loads the straight-line ones (the LC Intrepid
pack's `ZZ_VoyPhoton` and `ZZ_Tricobalt`; see
tests/unit/test_lc_intrepid_pyc_projectiles.py), but a module it refuses --
or any other unimportable script -- still makes `import_module` raise, and
the tube used to `return` out of `_spawn_torpedo` in silence.
```

- [ ] **Step 6: Run the touched tests**

Run: `uv run pytest tests/unit/test_lc_intrepid_pyc_projectiles.py tests/unit/test_torpedo_script_fallback.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_lc_intrepid_pyc_projectiles.py engine/appc/weapon_subsystems.py tests/unit/test_torpedo_script_fallback.py
git commit -m "test(mods): the LC Intrepid's .pyc-only torpedoes load as themselves

ZZ_VoyPhoton and ZZ_Tricobalt import from the pack's .pyc. The launch
resolver and the ammo type use them, and a fired torpedo carries the
module's own damage, guidance, turn rate and lifetime. Assertions read the
module's getters, never mod-derived literals. Fallback docstrings now say
the photon is for refused bytecode only.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Reference row, and the gate

**Files:**
- Modify: `CLAUDE.md` (append one row to the "Key reference material" table, after the "Quick Battle setup + group spawning" row)

**Interfaces:** none.

- [ ] **Step 1: Add the CLAUDE.md row** directly after the line that starts `| Quick Battle setup + group spawning |`:

```markdown
| **`.pyc`-only mod scripts — Python 1.5 bytecode lifted in the SDK loader** | `engine/py15/`, `_module_tree` + `_mod_override_spec` in `tools/mission_harness.py` AND `tests/conftest.py`, `docs/superpowers/specs/2026-10-15-pyc-only-mod-modules-design.md` | A mod module shipped only as 1.5 `.pyc` (the LC Intrepid's `ZZ_VoyPhoton`/`ZZ_Tricobalt`) is lifted in memory to the Python 3 AST its source would parse to, then takes the SAME transform pipeline. **Mod files only**: stock always loads from SDK `.py`. Per layer `.py` → `/__init__.py` → `.pyc` → `/__init__.pyc`. Straight-line subset only (no jumps, classes, nested/variadic defs); anything else raises `Py15Unsupported`, prints ONE `[sdk-loader]` line, and projectiles fall back to the photon. ⚠️ The subset grows only with a stock-corpus case in `tests/unit/test_py15_stock_oracle.py` (floor 514 of 1201, 0 mismatches). ⚠️ Never write lifted or decompiled mod text anywhere, and never commit a mod-derived value in a test. ⚠️ uncompyle6 is NOT a fallback: it silently mis-decompiles 1.5 (`import a.b` → `import a`). |
```

- [ ] **Step 2: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, with no failure or skip outside `tests/known_failures.txt`. A failure is a regression this branch introduced. Fix it; never baseline it.

- [ ] **Step 3: Confirm nothing mod-derived is staged or tracked**

```bash
git status --short
git ls-files | grep -iE "\.pyc$" || echo NO_PYC_TRACKED
git grep -n "ZZ_VoyPhotonCore\|ZZ_VoyPhotonGlow\|ZZ_Tricobaltglow" -- tests engine tools native || echo NO_MOD_VALUES
```

Expected: only `CLAUDE.md` modified, then `NO_PYC_TRACKED` and `NO_MOD_VALUES`. The test files *name* the two Intrepid modules, but no tracked file may hold a value or texture path read out of them. (The texture names are the sentinel: they appear nowhere in the tree today.)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): .pyc-only mod scripts reference row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand over for the live check (Mark).** Phase 1's live check (spec §7): run Quick Battle with an LC Intrepid as player and as AI. The torpedoes should show the mod's own `ZZ_*` visuals, no `[sdk-loader] … cannot load` line should appear for the two modules, and the AI should still reach its phasers. Mark live-tests **in this worktree** (memory `feedback_live_test_in_worktree`): make sure `build/` is current, then give him the command `cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/pyc-mod-loading && ./build/dauntless --developer` and wait. Do not launch the game yourself, and do not move the branch into the main checkout.
