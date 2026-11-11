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

## 3. Part 2: bytecode control flow

_To be written with the lifter change._
