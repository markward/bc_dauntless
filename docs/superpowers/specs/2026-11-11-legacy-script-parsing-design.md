# Legacy script parsing: Python 1.5 source and bytecode

**Status:** in progress on `feat/legacy-script-parsing`. Part 1 (source) done; part 2 (bytecode control flow) in progress.
**Date:** 2026-11-11
**Related:** `2026-10-15-pyc-only-mod-modules-design.md` (this extends its §9 "control flow" and supersedes its D2), `2026-09-08-mod-overlay-design.md`

## 1. Why

A review of the Kobayashi Maru 2011.10 mod pack (2,556 `.py`, 641 bytecode-only modules) found that the SDK loader failed on Python 1.5 that the original game ran without complaint:

- **243 of 2,556 KM scripts did not parse** (stock: 1 of 1,234, `string.py`). 221 of them were indentation: the loader expanded tabs to **4** columns, Python 1.5's tokenizer to **8**.
- **The `print` rewrite swallowed trailing comments** (`print "x"  ###` became `print("x"  ###)`, an unclosed bracket), and only handled `print` at a line start, not after `if x:` or `;`.
- **The octal rewrite reached into strings.** Stock `MainMenu/mainmenu.py` and the multiplayer menus displayed `'3945 0o62'` for the LCARS text `'3945 062'`.
- **The `raise X, v` rewrite split at commas inside the message string.**
- **The bytecode lifter (`engine/py15`) took straight-line code only**: 4 of KM's 479 bytecode-only ship scripts and hardpoints lifted.

The goal is general compatibility with BC-era scripts, not KM specifically. KM, the extracted mods in `bc_mod_tools`, `mods/` and the stock SDK are the measurement corpus.

## 2. Part 1: source (`engine/py15/source.py`)

One implementation, called by both SDK loaders (`tools/mission_harness.py` and `tests/conftest.py`) and by the lifter's stock oracle. The two loaders previously each carried a copy of the regexes.

`fix_source(text)` = 1.5 indentation, then `fix_syntax`. Every rewrite runs over a scan that separates code, string literals and comments, so no rewrite reaches into a string or a comment:

| Rule | Python 1.5 behaviour reproduced |
|---|---|
| Indentation | a tab in leading whitespace advances to the next multiple of 8; tabs elsewhere (strings) are kept |
| Numbers | `10L` / `0xffL` drop the long suffix; `0755` is octal |
| String escapes (non-raw) | `\N`, `\u`, `\U` are not escapes in 1.5 and stay literal; `\x` takes every following hex digit and keeps the low byte; octal escapes keep the low byte; `\x` with no hex digit stays literal |
| Operators | `<>` → `!=`; backticks → `repr()`; `.has_key(` → `.__contains__(` |
| Statements | `print`, `print >>f`, `raise X, v`, `exec c in g, l`, `except X, e:`: recognised at statement level, after `;` or a compound header's colon as well as at a line start, ending before a `;` or a comment |

Kept as before, on purpose: `print a,` prints its newline (`print(a,)`), and `print (x)` stays a call.

**Measured result** (parse success through the loader's pipeline):

| Corpus | Before | After |
|---|---|---|
| Stock SDK | 1,233 / 1,234 | **1,234 / 1,234** |
| KM 2011.10 | 2,313 / 2,556 | **2,554 / 2,556** |
| `bc_mod_tools/extracted` | 340 / 340 | 340 / 340 |
| `mods/` | 69 / 69 | 69 / 69 |

KM's two remaining failures are its own copies of `os.py` and `threading.py` (a three-argument `raise` and tuple parameters, which Python 3 cannot express). The loader never loads a mod's copy of a standard-library module (`_mods_may_override`).

**Every AST change to a file that already parsed was checked** (old pipeline vs new, all four corpora). Each one is a correction: the stock menu strings above; one stock docstring and one NanoFX docstring keeping a tab; and eight DJ Galaxy Pack carrier scripts, whose tab-indented lines had fallen out of `__init__` into the class body under 4-column tabs.

Tests: `tests/unit/test_py15_source.py` (no BC content).

### 2.1 Text encoding and 32-bit literals (found by the bytecode oracle)

- **Encoding.** Python 1.5 strings are bytes; BC is a Windows game, so a byte means its cp1252 character. Files are now read with `decode_text`: UTF-8 when the whole file is valid UTF-8 (modern editors, our own SDK companions), else cp1252 byte by byte (latin-1 for the five bytes cp1252 leaves undefined). A `\x`/octal escape in a string means the character `decode_text` gives that byte, and the lifter decodes bytecode string constants the same way, so a byte means one character on every path. Before, files were read as UTF-8 with replacement: stock `MainMenu/mainmenu.py`'s credit **"Siôn Rodriguez Y Gibson" displayed as "Si�n"**.
- **32-bit literals.** A plain (not `L`) hex or octal literal from 2³¹ to 2³² is a negative C long in 1.5: `0xFFFFFFFF` is -1. Stock `QuickBattle/QuickBattle.py` sets its unlock masks to `0xFFFFFFFF` and defines `TRANSPORT = 0x80000000`; the retail bytecode holds -1 and -2147483648. The source path now writes `(-1)`. Nothing in the engine relied on the positive values; the Quick Battle tests pass.
- **Floats are deliberately NOT rounded.** 1.5's marshal writes floats as `%.12g` text, so the retail `.pyc` holds 12 significant digits where some SDK sources carry more. Rounding source floats would shift hardpoint values and the bit-exact A/B baselines for a 1e-12 difference. The oracle compares floats at 12 digits instead (§3.3); a lifted mod `.pyc` keeps exactly the values BC ran with.

## 3. Part 2: bytecode control flow (`engine/py15/lift.py`)

### 3.1 Approach

Python 1.5's compiler has no optimiser: each statement compiles to one fixed instruction shape (CPython 1.5.2 `Python/compile.c`). The lifter folds `SET_LINENO` into a per-instruction line, then recognises those shapes by recursive descent over instruction ranges, with a value stack for expressions:

| Shape | Recognised by |
|---|---|
| `if`/`elif`/`else` | `JUMP_IF_FALSE t; POP_TOP; <body>; JUMP_FORWARD end; t: POP_TOP; <else>` |
| `and` / `or` | a conditional jump whose target is not that `if` shape: the value stays on the stack |
| `while` [`else`] | `SETUP_LOOP; top: <cond>; JUMP_IF_FALSE x; ...; JUMP_ABSOLUTE top; x: POP_TOP; POP_BLOCK` |
| `for` [`else`] | `SETUP_LOOP; <seq>; LOAD_CONST 0; FOR_LOOP x; <target>; ...; JUMP_ABSOLUTE; x: POP_BLOCK` |
| `break` / `continue` | `BREAK_LOOP` / `JUMP_ABSOLUTE` to the innermost loop's top |
| `try`/`except`/`else` | `SETUP_EXCEPT`, `DUP_TOP ... COMPARE_OP exception-match` clauses, bare clause, `END_FINALLY` |
| `try`/`finally` | `SETUP_FINALLY f; ...; POP_BLOCK; LOAD_CONST None; f: ...; END_FINALLY` |
| `assert` | `LOAD_GLOBAL __debug__; JUMP_IF_FALSE` ... `RAISE_VARARGS 1|2` |
| classes | `BUILD_CLASS` over a body code object ending `LOAD_LOCALS; RETURN_VALUE` |
| assignment | `a = b = v` (`DUP_TOP` chains), `a, [b, c] = v` (`UNPACK_*`), `for`/`except` targets, by pending target slots |
| also | `from` imports, lambdas, nested defs, `*args`/`**kwargs`, slices, `del`, `raise` forms, backticks |

Refused by name, never guessed: `exec` statements, `print` to the interactive prompt, extended slices, chained comparisons, tuple parameters, `raise` with a traceback. None occurs in the stock or mod corpus.

### 3.2 Where two sources compile to the same bytecode

The lifter picks one; the program is the same either way.

- `a and (b and c)` and `a and b and c`: lifted flat.
- `import a; import b` on one line and `import a, b`: lifted as one statement (and `del` likewise).
- `print "a", f()`: 1.5 writes `a` before calling `f`; the source path's `print("a", f())` calls `f` first. The lifter matches the source path (the old "print item evaluated after output began" refusal is gone).
- A bare `return` is `LOAD_CONST None` and lifts bare; `return None` loads the *name* `None` and lifts as written.

### 3.3 Proof: the stock oracle

`tests/unit/test_py15_stock_oracle.py` lifts every retail `.pyc` (1,201) and compares it with its SDK source through `fix_source`. Result: **1,201 of 1,201 accepted (was 514), 0 mismatches.** Its closed normalisation now applies each item at any depth and gained three items, each something bytecode cannot carry: a `global` anywhere in a function (the loader's `_MoveGlobalsToTop` hoists them anyway) and at module/class level (compiles to nothing); a trailing same-operator `BoolOp` flattened (§3.2); floats at 12 significant digits (§2.1). `_SOURCE_DIFFERS` names the one retail module compiled from a different source than the SDK ships (`TimingGraph.py`, with the evidence); it must still lift.

Synthetic fixtures for every shape, assembled to `compile.c`'s layout with no BC content: `tests/unit/test_py15_lift_control_flow.py` (the assembler gained labels). A mutation check (`and`/`or` swapped) fails four of them.

### 3.4 Result on mods

| Corpus | bytecode-only modules lifted, before → after |
|---|---|
| KM 2011.10 | 4 of 641 → **641 of 641** (264 ships, 215 hardpoints, 121 projectiles, 39 multiplayer, 2 other) |

KM's recompiled stock ships, lifted and diffed against stock source, differ only by KM's own content changes (rebalanced hardpoints, torpedo visuals, model paths). No mod-derived value is committed.

### 3.5 Unchanged

Decision D1 of the 2026-10-15 spec stands: an unliftable mod `.pyc` that replaces a stock module is an `ImportError`, not a fall-through to stock. With every corpus module lifting, it now only sets policy for unusual bytecode.
