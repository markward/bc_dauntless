# Mod Overlay — Design

**Status:** approved, not yet implemented
**Date:** 2026-09-08
**Line citations verified at:** `e1bd950e` (they drift between branches —
re-check before relying on one)
**Builds on:** `docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md`
(this spec adds a layer *above* the roots that one resolves)
**Followed by:** Spec 2 — mod management mode (not yet written);
Spec 3 — Foundation compatibility surface (not yet written)

## Problem

Bridge Commander mods are distributed as a folder you paste over your
install, overwriting whatever is already there. That is destructive and
unrevertable: the player has no record of which files came from where, no
way to disable a mod, and no way back to stock short of reinstalling.

We can do better, because we own the resolution path. `game/` and `sdk/`
are already resolved through one authority (`engine/paths.py`), so a layer
that answers "who provides this file?" before the stock roots are consulted
gives non-destructive install for free — mods stay in their own folders and
nothing is ever overwritten.

The overlay has to reach three independent consumers:

| Consumer | Resolves via | Sites |
|---|---|---|
| Python asset paths | `paths.game_asset(rel)` — `engine/paths.py:386` | ~30 |
| SDK Python imports | `_SDKFinder`, **duplicated** — `tools/mission_harness.py:458`, `tests/conftest.py:487` | 2 copies |
| C++ asset paths | `renderer::resolve_asset_path` — `native/src/renderer/asset_path.cc:35` | ~10 literals |

## Goal

Scan `mods/`, and make every enabled mod's files win over stock content in
all three consumers, without copying, symlinking, or mutating anything on
disk. A mod that provides a file the stock install also provides shadows it;
a mod that provides a new file adds it. Disabling a mod restores stock
exactly, because stock was never touched.

## Non-goals

- **Foundation and FoundationTech compatibility.** Deferred to Spec 3. This
  spec makes their absence *visible* (see "Framework detection") rather than
  a silent failure, and the report it produces is Spec 3's requirements
  input.
- **A mod management UI.** Deferred to Spec 2. Everything discovered is
  enabled in v1. The index is designed so the screen has something to render.
- **Live enable/disable.** Management happens before the game loop exists
  (see "Why there is no restart-to-apply"), so this never arises.
- **Archive import** (`.zip` / `.rar`). The player extracts into `mods/`.
- **Conflict *resolution*.** Conflicts are detected and reported; ordering is
  alphabetical and arbitrary until Spec 2 provides explicit ordering.
- **Mod-authored content in our own formats.** Only BC-shaped trees.

## Licensing constraint (why `mods/` is gitignored)

Community mod packages carry unclear terms or none at all. Two data points
from the packages examined for this design:

- **Foundation** (Dasher42, 2002) — "All rights reserved." Permission is
  granted only *"as a component of Bridge Commander under the terms of the
  Activision SDK license"*, and LGPL appears solely as a copyleft obligation
  on modifications, not as a grant of the original. This is **not** a GPL
  release, and the grant is conditioned on a licence dauntless does not
  operate under.
- **Foundation Technologies 20051126** (MLeo Daalder) — no licence text at
  all, in the readme or the sources. All rights reserved by default.

This tree is public GPLv3. `mods/*` is therefore gitignored with
`!mods/.gitkeep` keeping the directory itself tracked. The ignore block sits
*below* the existing `!**/.gitkeep` exception because later `.gitignore`
rules win, and it repeats the negation so the pair is order-independent.

**Consequence for tests:** no test may depend on a real mod. All fixtures
are synthetic trees built in `tmp_path`.

## What a mod is

Each immediate subdirectory of the mods root is one mod; the directory name
is its identity. **No manifest is required** — we do not control how
community packages are built, and requiring a manifest means no existing mod
works.

### Finding the content root

Archives are inconsistent: some extract to `<mod>/{Data,Scripts}`, others add
a redundant nesting level, `<mod>/<name>/{Data,Scripts}`. From the mod
directory, descend while the current directory contains no recognised BC
top-level directory (`data`, `scripts`, matched case-blind) **and** has
exactly one subdirectory. Cap the descent at 3 levels.

A mod with no content root found is recorded and reported as unrecognised —
never skipped silently.

### Ignored files

Package junk at any level: `.DS_Store`, `Thumbs.db`, and readme/document
files at the content root (`*.txt`, `*.html`, `*.pdf`, `*.rtf`, `*.doc`).
Ignored files are **counted**, so "3 files not placed" is visible rather
than mysterious.

## The index

One pass over each mod's content root builds a flat map:

```
key    case-folded path relative to the target root
       e.g. "data/models/ships/steamrunner_aad/fsteamr.nif"
value  ModFile(absolute_path, owning_mod, target_root, shadow_class)
```

Stock content is **never indexed**. The cost is O(mod files), not O(install
files) — mods are small (the reference mod is 45 files), the BC install is
not. This is the central reason for choosing an index over either a
search-path stack or a materialised symlink farm.

`engine/mods.py` owns it, using `paths.py`'s own `configure()` / `current()`
cache pattern so nothing is captured at import — the same discipline the
path-resolution spec enforces, and for the same reason (a management screen
runs after import and changes the answer).

`paths.game_asset()` imports `engine.mods` **lazily inside the function**,
the trick `paths.resolve()` already uses for `settings_store`. There is no
cycle: building the index needs the mods root and nothing else from `paths`.

## Two roots, and case

A BC mod tree straddles both of our roots, because BC had one install
directory where we have two. The content root's children map by name:

| mod directory | target |
|---|---|
| `Data/` | `game_root()/data/…` |
| `Scripts/` | `sdk_scripts()/…` |
| anything else | not placed; recorded and reported |

### Case-folding is load-bearing

BC's original engine ran on a case-insensitive Windows filesystem, so mod
authors were never forced to be consistent, and overwhelmingly are not. The
single reference mod contains **three independent** case collisions:

| On disk (mod) | Expected | Where |
|---|---|---|
| `Data/` | `data/` | BC install root |
| `Scripts/Ships/` | `ships/` (verified lowercase in the SDK) | SDK scripts |
| `Fsteamr.NIF` | `Fsteamr.nif` as written in its own `GetShipStats()` | the mod's own script |

On case-insensitive APFS these work by luck. On Linux they fail. Folding at
index-build time makes resolution correct on every platform, and costs
nothing at lookup.

Collapsing `Ships` and `ships` to one key is **faithful**, not a
compromise: on BC's filesystem they were one directory.

Python module names *are* case-sensitive, so `_SDKFinder` performs the same
folded lookup — a mod's `Scripts/Ships/Fsteamr.py` then resolves for both
`import Ships.Fsteamr` and `import ships.Fsteamr`, again matching BC.

**Safety of folding:** no two stock files may differ only by case, or folding
would merge them. This holds by construction — BC content ships from a
case-insensitive Windows filesystem, where such a pair cannot exist. See
risk 1 for the evidence and the residual case.

## Resolution

### Python assets

`paths.game_asset(rel)` folds `rel`, looks it up, and returns the hit's
absolute path; on a miss it returns `game_root() / rel` exactly as today.
One dict lookup on the fast path — no stat, no per-layer walk.

**With zero mods installed the returned path must be byte-identical to
today's.** A modless boot may not shift at all; this is an explicit test.

Three Python-side consumers currently take a *directory* from `game_asset()`
and immediately join a filename onto it — `engine/ui/ship_icons.py`,
`weapon_icons.py`, `damage_icons.py`. These become single relative-path
lookups through the index, which is simpler than what is there now.

`host_loop.py:4347` `_ship_texture_search` is the one consumer that
genuinely hands C++ a directory list. It **already returns a list**; mod
directories that provide textures for that ship are appended.

### SDK imports

Both `_SDKFinder` copies check the index before `sdk_scripts()`. Mods can
therefore override stock SDK modules, which is required, not incidental:
Foundation-style mods deliberately replace `loadspacehelper.py`,
`QuickBattle.py` and `Registry.py`.

**Both copies must change together** — `tools/mission_harness.py` and
`tests/conftest.py` are a known duplicate-transform trap in this codebase.

### C++ assets

*This section is separable. Cutting it leaves mods able to override
everything Python resolves — every ship, texture, icon and script — and
leaves only engine chrome unmoddable.*

Only index entries targeting the **game** root can reach C++. Python pushes
them once at boot, alongside the existing `r.set_game_root(...)`:

```python
r.set_asset_overrides({folded_rel: abs_path, ...})
```

`resolve_asset_path` folds the incoming path, checks the map, and returns
the hit; otherwise it behaves exactly as today, including the existing
`"game/"`-prefix strip warning. Touches `asset_path.cc` and
`host_bindings.cc`, so it requires a `dauntless` rebuild.

Register the binding in `_REQUIRED_BINDINGS` rather than `hasattr`-guarding
it: the house convention is that a missing binding means a stale binary to
rebuild, not a case Python should paper over.

What this buys: the paths C++ resolves internally are all chrome —
`data/Textures/spacedust.tga`, the target reticle, damage frames, subsystem
pin glyphs. BC mods do replace HUD art.

## Load order, shadowing, and conflicts

Order is **alphabetical by mod directory name** in v1 — deterministic and
stateless. Later wins, matching paste-over-install semantics.

Alphabetical means *which* mod wins a conflict is arbitrary. That is not
fixable without the ordering UI in Spec 2, so the mitigation is that a
conflict is **never silently resolved**. Every entry is classified:

| Class | Meaning | Report level |
|---|---|---|
| `addition` | Provides a path nothing else does | none (counted) |
| `stock_override` | Shadows a real file under the game or SDK root | info |
| `mod_conflict` | Two mods claim one path | **warn**, naming both and the winner |

Detecting `stock_override` costs one stat **per mod key** — never a walk of
the install.

## Framework detection

Mod scripts are scanned for imports that resolve to neither stdlib, the
project, the SDK, nor another mod — principally `Foundation` and
`FoundationTech`. These are recorded per mod.

Mod scripts are Python 1.5 era and may not parse with `ast` (backtick-repr,
`has_key`). Fall back to a regex scan when `ast` raises, the same posture
`tests/unit/test_path_indirection.py` already takes for `tools/probes/`.

This makes a partially-supported mod legible instead of mysterious. The
reference mod is a precise example: its `Scripts/Ships/*.py` and `Data/**`
halves are stock-shaped and work through the overlay alone, while its
`Scripts/Custom/Ships/*.py` half calls `Foundation.FedShipDef` and
`RegisterQBShipMenu` — and the SDK ships `Custom/` with an `__init__.py` but
**no `Custom/Ships/`**, while the mod supplies no `__init__.py` of its own.
Without Foundation, `Custom.Ships` is not an importable package at all. The
ship loads; it does not appear in the QuickBattle menus.

Per-mod status is the output, and it is what Spec 2's screen renders:

```
Steamrunner Aad     45 files → 42 placed, 3 ignored (.DS_Store)
                    0 stock overrides, 0 conflicts
                    requires: Foundation, FoundationTech  (unsupported)
```

The aggregate of these `requires:` lines across a mod corpus is Spec 3's
requirements document.

## Where `mods/` lives

Default `PROJECT_ROOT/mods`, overridable by `--mods-dir` and
`DAUNTLESS_MODS_DIR`, following the precedence discipline `paths.py` already
establishes: the highest **set** source wins even when invalid, because
falling through would silently run a different mod set than the one asked
for.

This is not speculative generality — a git worktree and the main checkout
each get their own `mods/` (the directory is gitignored and does not
propagate), which is exactly the situation the flag resolves. Cheap now,
awkward to retrofit.

## Boot sequence

The overlay slots into one existing seam in `engine/host_loop.py`:

```
_paths.resolve()
  → [first-run screen if roots unresolved]             (~:7126)
  → _paths.configure(resolution)                       (~:7132)
  → mods.configure(mods.build_index(...))              ← NEW
  → r.set_game_root(...) + r.set_asset_overrides(...)  (~:7263)
  → _SDKFinder installed
  → mission load
```

The index must be built after `configure()`, because mapping `Data/` and
`Scripts/` to their targets requires the resolved roots.

### Why there is no restart-to-apply

Mod management (Spec 2) runs **before the game loop exists**, in the same
pre-loop CEF pump `_run_first_run_screen` already implements
(`host_loop.py:6974` — hologram-only mode, mouse forwarding, the load-end
handler). The player toggles, then boot proceeds into a world where the
answer was always that.

This dissolves the hardest problem in the feature. A mid-session toggle
would need `_SDKFinder` cache purging, GPU resource eviction, and live
instance rebuild; running before the loop means none of it exists. Spec 2
should reuse that pump rather than invent a second one.

## Testing

Fixtures are **synthetic** mod trees in `tmp_path` (see the licensing
constraint above).

**Index construction**
- content-root descent: flat, nested once, none found, depth cap exceeded
- case folding: all three real collisions above
- two-root mapping; unknown top-level directory recorded, not dropped
- junk files ignored but counted

**Classification**
- `addition` / `stock_override` / `mod_conflict` each detected
- ordering is deterministic across runs

**Resolution**
- `game_asset()` returns the mod path when indexed, stock otherwise
- **zero mods ⇒ byte-identical stock path** (regression guard)
- `_SDKFinder`: mod module beats SDK module; `Ships.X` and `ships.X` both
  resolve — asserted against **both** copies

**C++**
- a `renderer_tests` case for `resolve_asset_path` with overrides set and
  cleared

**Guards**
- `tests/unit/test_path_indirection.py` picks up `engine/mods.py`
  automatically: it must spell neither root as a path segment nor capture a
  path at import

Gate is `scripts/check_tests.sh` (builds C++ and runs both suites), never
`run_tests.sh`.

## Risks and open questions

1. **Case-folding collapse.** If two stock files differ only by case, folding
   merges them. A scan of the reference install found 0 collisions across
   14,522 game files and 1,319 SDK files — but that scan ran on **APFS,
   which is case-insensitive**, where such a pair cannot coexist at all, so
   it was guaranteed to return zero and is weak evidence by itself.

   The load-bearing argument is structural rather than empirical: BC content
   is distributed from a case-insensitive Windows filesystem, so case-only
   duplicates cannot exist in the original content by construction. The same
   reasoning covers mods, which were authored against that same filesystem.

   *Residual risk:* content assembled on a case-sensitive filesystem — a
   Linux-authored mod, or an install repacked there. Not possible for stock
   BC content. If it ever bites, the index should detect two mod files
   folding to one key within a single mod and report it as a packaging
   error. *(Downgraded from open; re-run the scan on a Linux install if one
   becomes available.)*
2. **The index is a boot snapshot.** Editing a mod mid-session has no effect
   until relaunch. Accepted — management is pre-boot by design. A dev-mode
   rescan is cheap if it is ever wanted.
3. **Arbitrary conflict winner in v1.** Alphabetical order decides. Mitigated
   by loud reporting; resolved by Spec 2.
4. **Mods that patch stock scripts by overwrite.** Supported by construction
   (the SDK finder consults the index first), but a mod overriding a module
   we have *reimplemented in C++ or in `engine/`* rather than loaded from the
   SDK will appear to do nothing. Not detectable from the index alone.
   *(Open — needs a list of SDK modules we shadow.)*
