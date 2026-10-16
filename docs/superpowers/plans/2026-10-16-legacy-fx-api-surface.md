# Legacy FX API Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mods written against NanoFX 2.0's API work in Dauntless without NanoFX
installed. A real NanoFX install is blocked, Foundation's bundled infrastructure
files are refused, and NanoFX texture paths resolve to a Dauntless sprite library.

**Architecture:** Four layers, each its own tasks.

- **Mod policy.** A pure policy module filters mod files before they enter the
  mod index.
- **Missing names.** A few Foundation and Appc names are added (`MutatorDef`,
  glow-map flags, `DisableGlowAlphaMaps`, `NiPoint3`,
  `DebrisParticleController_Create`, `g_kTextureAnimManager`).
- **The `Custom.NanoFXv2` package.** A claimed-namespace rule in both
  `_SDKFinder`s serves `Custom.NanoFXv2` from `engine/compat/fx_api/`.
- **Sprite library.** A manifest plus legacy aliases resolves texture paths at
  `CreateTarget`, with new particle playback/pivot/orient fields, a native
  shockwave kind, and a Pillow prep tool that turns generated sheets into
  committed PNGs.

**Tech Stack:** Python 3.11 (engine shim, tools, pytest), C++20 + GLSL 410
(renderer, gtest/ctest), pybind11 bindings, Pillow.

**Spec:** `docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md`. Read it
before any task; every task argues from it.

## Global Constraints

**Production and shared code:**

- **Production VFX stay byte-identical.** Stock `App` controller behaviour is NOT
  changed. `TGModelUtils_CastNodeToAVObject`, `ExplosionPlumeController_Create`,
  `SetTargetAlphaBlendModes` (any call → additive), `SetGravity` and
  `SetDetachEmitObject` keep today's behaviour (spec §8.4). Task 9's guard test
  enforces this.
- **Twin finders.** `tools/mission_harness.py` and `tests/conftest.py` each own
  an `_SDKFinder.find_spec`, and `tests/unit/test_sdk_finder_twins_stay_in_sync.py`
  requires identical logic. Change both identically.

**Paths, licence and naming:**

- **Paths resolve at use, never at import.** No module-level path constants.
  Never spell `game`/`sdk` as a path segment; kind-label literals carry
  `# paths-guard: kind label`.
- **No NanoFX or Foundation code or assets are copied.**
  - NanoFX legacy texture *paths* appear only as alias keys.
  - NanoFX default config values and race colours are data facts.
- **Naming.** Nothing we name contains "nanofx". The exceptions are the import
  names mods require (`Custom.NanoFXv2`, `NanoFX_Lib.py`,
  `NanoFX_ScriptActions.py`, `NanoFX_Config.py`) and the legacy path strings
  used as alias keys.
- **Sprite output format.** Sprite art is PNG output, committed under
  `native/assets/sprites/` (sources in `src/<id>/`), regenerated only by
  `tools/sprites/prep.py`. Never hand-edit an output PNG.

**Git and the fixture mod:**

- **Banned git** (shared checkout): `git checkout -- <path>`, `git restore`,
  `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`.
  Always stage with explicit pathspecs.
- **Fixture mod.** The live-test fixture mod lives in the gitignored `mods/`
  and is never committed.

**Commits:**

- End every commit message with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Path spelling.** A mod passes a legacy texture path with backslashes, a
   `./` prefix or mixed case (`scripts\Custom\NanoFXv2\ExplosionFX\Gfx\Explosions\Exp_Nano3.TGA`).
   It must resolve to the same sprite as the canonical spelling. Pinned in
   Task 10 (`test_alias_resolution_is_spelling_blind`).
2. **Refused winner.** A mod whose refused Foundation copy of
   `LoadTacticalSounds.py` would have won over an earlier mod's plain copy. The
   earlier mod's file must survive, with no conflict recorded. Pinned in Task 2
   (`test_refused_file_does_not_displace_earlier_mod`).
3. **Stub emit source.** `CreateControllerFX` is called the NanoFX way:
   `pEmitFrom = App.TGModelUtils_CastNodeToAVObject(ship.GetNode())` (a stub)
   and `vEmitPos = App.NiPoint3(x, y, z)`. The effect must anchor to the ship at
   that body offset, not the world origin. Pinned in Task 13
   (`test_stub_emit_source_anchors_to_attach_owner`).
4. **Unprovided module.** A mod imports a deep NanoFX module we don't provide
   (`Custom.NanoFXv2.WarpFX.AI.NanoWarp`) and calls a function on it. The import
   must succeed, the call return `None`, and it must be logged once. Pinned in
   Task 6 (`test_unprovided_submodule_imports_and_logs_once`).
5. **Unreadable sprite data.** A missing or corrupt
   `native/assets/sprites/manifest.json` must never crash `CreateTarget`.
   Legacy paths pass through unchanged and every caller keeps its own texture
   path. In that degraded state the stock sheets lose their grid and
   brightness (they now live in the manifest), which the boot log names via
   the `[sprites] ... unreadable` line. Pinned in Task 10
   (`test_unreadable_manifest_passes_paths_through`).

---

## File Structure

**Create**

| Path | Responsibility |
|---|---|
| `engine/mod_policy.py` | Pure decisions: block standalone NanoFX, refuse bundled NanoFX and Foundation infrastructure files |
| `engine/foundation/mutator.py` | Inert always-on `MutatorDef` with Foundation's four standard instances |
| `engine/foundation/race.py` | `Race(str)` with `.name` long form |
| `engine/appc/glow_maps.py` | Global glow/specular flags + per-object glow disable (epoch scheme) |
| `engine/appc/texture_anim.py` | `g_kTextureAnimManager`: records frame rects, infers regular grids |
| `engine/compat/__init__.py` | Package marker |
| `engine/compat/claimed.py` | Claimed-namespace finder helper + unsupported-module loader |
| `engine/compat/fx_api/__init__.py` | `Custom.NanoFXv2` package |
| `engine/compat/fx_api/NanoFX_Config.py` | Read-only NanoFX default settings |
| `engine/compat/fx_api/NanoFX_Lib.py` | Public helper API on Dauntless systems |
| `engine/compat/fx_api/NanoFX_ScriptActions.py` | Script actions + `CreateControllerFX` / `SetupController` |
| `engine/sprites.py` | Sprite library runtime: manifest + aliases → `SpriteRef` |
| `native/assets/sprites/manifest.json` | Sprite entries (runtime + prep fields) |
| `native/assets/sprites/legacy_aliases.json` | Folded legacy path / prefix → sprite id |
| `native/assets/sprites/src/<id>/black.jpeg`, `green.jpeg` | Generated source sheets |
| `native/assets/sprites/<id>.png` | Prep-tool outputs |
| `native/assets/planets/atmosphere_classes.json` | Planet-class atmosphere presets |
| `tools/sprites/__init__.py`, `tools/sprites/prep.py` | Sheet → PNG prep tool |
| `tests/fixtures/mod_layouts/nanofx_2_0_beta.txt` | Path-only listing of the real NanoFX 2.0 layout |
| `tests/fixtures/stock_particle_descriptors.json` | Golden stock particle descriptors (Task 9) |
| `native/tests/renderer/fixtures/sprite_4x4.png` | Tiny PNG for the particle-pass decode test |
| Tests listed per task | |

**Modify**

| Path | Change |
|---|---|
| `engine/mods.py` | `ModStatus.blocked/refused`; `build_index` consults policy per mod; `describe()` reports |
| `engine/ui/mods_screen.py`, `engine/ui/mods_screen_panel.py`, `native/assets/ui-cef/index.html`, `native/assets/ui-cef/js/mods_screen.js`, `native/assets/ui-cef/css/mods_screen.css` | Blocked-mods notice |
| `engine/foundation/__init__.py`, `engine/foundation/shipdef.py` | Export `MutatorDef`; `race` → `Race` |
| `engine/appc/lod_models.py` | Glow/specular flag methods |
| `engine/appc/objects.py` | `DamageableObject.DisableGlowAlphaMaps` |
| `engine/appc/running_lights.py` | Level 0 for glow-disabled ships |
| `engine/host_loop.py` | `_emissive_scale_for`; clear mod-requested atmospheres at session teardown |
| `tools/mission_harness.py`, `tests/conftest.py` | Claimed-namespace check in both finders; conftest resets |
| `engine/planets/atmosphere.py` | Mod-requested atmosphere layer + class presets |
| `engine/appc/particles.py` | Library-aware `CreateTarget`, new descriptor keys, `EffectAction` routing, `DebrisParticleController` |
| `engine/appc/shockwaves.py` | `tint` |
| `App.py` | `NiPoint3`, `DebrisParticleController_Create`, `g_kTextureAnimManager` |
| `native/src/renderer/include/renderer/frame.h` | Particle `playback/fps/pivot/orient`; shockwave `tint` |
| `native/src/renderer/include/renderer/particle_math.h` | `atlas_cell()` |
| `native/src/renderer/particle_pass.cc`, `include/renderer/particle_pass.h` | `decode_image`; atlas_cell; pivot; orient; `loaded_texture_count()` |
| `native/src/renderer/hit_vfx_pass.cc` | Reset `u_pivot` |
| `native/src/renderer/shaders/hit_vfx.vert` | `u_pivot` |
| `native/src/renderer/shockwave_pass.cc`, `shaders/shockwave.frag` | `u_tint` |
| `native/src/host/host_bindings.cc` | New particle + shockwave dict keys |
| `native/tests/renderer/particle_math_test.cc`, `particle_pass_test.cc` | New tests |
| `docs/engine/foundation-api-surface.md`, `CLAUDE.md`, spec §8.3 | Docs |

---

## Task 0: Workspace setup (no commit)

The worktree is `.claude/worktrees/nanofx-surface` on `feat/nanofx-surface`.
`settings.json` and `mods/` are already copied in. The venv and build tree are
not yet set up.

- [ ] **Step 1: Python env**

Run: `uv sync --extra dev`
Expected: completes; `.venv/bin/pytest` exists.

- [ ] **Step 2: Configure and build C++** (Debug, pinned uv Python 3.11, never Homebrew)

```bash
U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none
cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION
cmake --build build -j
```

Expected: `build/dauntless` and `build/python/_dauntless_host.cpython-311-*.so`
exist. If that `cpython-3.11.*` directory name differs, use the one under
`~/.local/share/uv/python/` and check `_Python3_INCLUDE_DIR` in
`build/CMakeCache.txt` names it.

- [ ] **Step 3: Baseline gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. If not, STOP and report the failures (don't proceed on a red
baseline).

---

## Task 1: Mod policy (pure decisions)

**Files:**
- Create: `engine/mod_policy.py`
- Create: `tests/fixtures/mod_layouts/nanofx_2_0_beta.txt`
- Test: `tests/unit/test_mod_policy.py`

**Interfaces:**
- Produces:
  - `mod_policy.PolicyFile(target: str, rel: str)` (frozen dataclass; `rel`
    is the folded index key — sdk keys have no `scripts/` prefix)
  - `mod_policy.PolicyDecision(blocked: Optional[str], refused: dict[str, str])`
  - `mod_policy.needs_imports(f: PolicyFile) -> bool`
  - `mod_policy.decide(files: list[PolicyFile], imports: dict[str, set]) -> PolicyDecision`
  - Constants: `REASON_NANOFX_BLOCKED`, `REASON_NANOFX_BUNDLED`,
    `REASON_FOUNDATION`, `SDK`, `GAME`

- [ ] **Step 1: Generate the path-only NanoFX layout fixture**

```bash
mkdir -p tests/fixtures/mod_layouts
( cd "/Users/mward/Documents/Projects/bc_mod_tools/extracted/NanoFX_2.0 BETA" && find . -type f ! -name .DS_Store | sed 's|^\./||' | LC_ALL=C sort ) > tests/fixtures/mod_layouts/nanofx_2_0_beta.txt
wc -l tests/fixtures/mod_layouts/nanofx_2_0_beta.txt
```

Expected: about 440 lines (one per file NanoFX 2.0 ships, `.DS_Store`
excluded). The first lines start with `data/Movies/`, and
`scripts/Custom/NanoFXv2/NanoFX_Lib.py` is present. The file holds paths only,
never content.

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_mod_policy.py
"""engine/mod_policy: which mod files Dauntless refuses, which mods it blocks.
Spec docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §5."""
from pathlib import Path

from engine import mod_policy as P

_LAYOUT = Path(__file__).resolve().parents[1] / "fixtures" / "mod_layouts" / "nanofx_2_0_beta.txt"


def _pf(raw: str) -> P.PolicyFile:
    """A mod-relative path as build_index keys it: data/ and sfx/ keep their
    top segment (game target); scripts/ drops it (sdk target)."""
    parts = raw.replace("\\", "/").strip("/").split("/")
    top = parts[0].lower()
    if top == "scripts":
        return P.PolicyFile(P.SDK, "/".join(parts[1:]).lower())
    return P.PolicyFile(P.GAME, "/".join(parts).lower())


def _nanofx_files():
    return [_pf(line) for line in _LAYOUT.read_text().splitlines() if line.strip()]


def test_standalone_nanofx_is_blocked_whole():
    d = P.decide(_nanofx_files(), {})
    assert d.blocked == P.REASON_NANOFX_BLOCKED
    assert d.refused == {}


def test_nanofx_bundled_in_a_pack_skips_only_its_own_files():
    files = _nanofx_files() + [_pf("scripts/ships/MyShip.py"),
                               _pf("data/Models/Ships/MyShip/MyShip.nif")]
    d = P.decide(files, {})
    assert d.blocked is None
    assert d.refused["custom/nanofxv2/nanofx_lib.py"] == P.REASON_NANOFX_BUNDLED
    assert d.refused["custom/autoload/loadnanofx.py"] == P.REASON_NANOFX_BUNDLED
    assert "ships/myship.py" not in d.refused
    # ATP is used by other mods in its own right: never refused.
    assert not any(r.startswith("custom/advancedtechnologies/") for r in d.refused)
    # Foundation's own files in the same pack are refused under rule B.
    assert d.refused["foundation.py"] == P.REASON_FOUNDATION
    assert d.refused["fixes20030217.py"] == P.REASON_FOUNDATION


def test_nanofx_texture_files_without_a_marker_are_left_alone():
    files = [_pf("scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga"),
             _pf("scripts/ships/Hardpoints/MyShipHP.py")]
    d = P.decide(files, {})
    assert d.blocked is None and d.refused == {}


def test_foundation_always_refused_files():
    names = ["scripts/Foundation.py", "scripts/FoundationMenu.py",
             "scripts/FoundationTriggers.py", "scripts/Fixes20030217.py",
             "scripts/Custom/Autoload/000-Fixes20030221.py",
             "scripts/Custom/Autoload/000-Utilities-GetFileNames-20030402.py"]
    d = P.decide([_pf(n) for n in names] + [_pf("scripts/ships/A.py")], {})
    assert set(d.refused) == {_pf(n).rel for n in names}
    assert set(d.refused.values()) == {P.REASON_FOUNDATION}


def test_conditional_files_refused_only_when_they_import_foundation():
    lts = _pf("scripts/LoadTacticalSounds.py")
    qb = _pf("scripts/QuickBattle/QuickBattle.py")
    mm = _pf("scripts/MainMenu/mainmenu.py")
    for f in (lts, qb, mm):
        assert P.needs_imports(f)
    d = P.decide([lts, qb, mm], {lts.rel: {"App", "Foundation"},
                                 qb.rel: {"App", "FoundationMenu"},
                                 mm.rel: {"App"}})
    assert d.refused == {lts.rel: P.REASON_FOUNDATION, qb.rel: P.REASON_FOUNDATION}


def test_needs_imports_is_false_for_everything_else():
    assert not P.needs_imports(_pf("scripts/ships/A.py"))
    assert not P.needs_imports(_pf("data/LoadTacticalSounds.py"))


def test_a_plain_ship_pack_is_untouched():
    d = P.decide([_pf("scripts/ships/A.py"), _pf("data/Models/A.nif")], {})
    assert d.blocked is None and d.refused == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mod_policy.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'engine.mod_policy'`.

- [ ] **Step 4: Implement**

```python
# engine/mod_policy.py
"""Which mod files Dauntless refuses, and which mods it blocks outright.

Spec: docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §5

Pure -- no I/O. engine/mods.build_index consults decide() per mod BEFORE any of
that mod's files enter the index, so every consumer (both _SDKFinders, the
asset overlay, the C++ override map) skips a refused file with no second
filter, and a refused file can never displace an earlier mod's copy.

Rule A -- NanoFX. Dauntless provides NanoFX's API itself (Custom.NanoFXv2,
engine/compat/fx_api). A mod that is nothing but NanoFX's distribution is
blocked whole; NanoFX bundled inside a bigger pack has only its own files
skipped.

Rule B -- Foundation infrastructure. Dauntless provides Foundation
(engine/foundation). Foundation's own modules are refused in any mod; three
engine-owned SDK modules are refused only when the mod's copy is Foundation's
rewrite (it imports Foundation/FoundationMenu), so a pre-Foundation mod that
edits LoadTacticalSounds.py directly keeps working.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

SDK = "sdk"    # paths-guard: kind label, mirrors engine/mods._TARGET_FOR
GAME = "game"  # paths-guard: kind label, mirrors engine/mods._TARGET_FOR

REASON_NANOFX_BLOCKED = "incompatible: NanoFX (Dauntless provides its API)"
REASON_NANOFX_BUNDLED = "bundled NanoFX skipped (Dauntless provides its API)"
REASON_FOUNDATION = "Foundation infrastructure (Dauntless provides Foundation)"

_NANOFX_MARKERS = frozenset({
    "custom/nanofxv2/nanofx_lib.py",
    "custom/autoload/loadnanofx.py",
})
_NANOFX_OWN_PREFIX = "custom/nanofxv2/"
_NANOFX_OWN_FILES = frozenset({"custom/autoload/loadnanofx.py"})

_FOUNDATION_ALWAYS = frozenset({
    "foundation.py", "foundationmenu.py", "foundationtriggers.py",
})
_FOUNDATION_ALWAYS_RE = re.compile(
    r"^(fixes2003[^/]*\.py"
    r"|custom/autoload/000-fixes[^/]*\.py"
    r"|custom/autoload/000-utilities-[^/]*\.py)$")
_FOUNDATION_CONDITIONAL = frozenset({
    "loadtacticalsounds.py", "quickbattle/quickbattle.py", "mainmenu/mainmenu.py",
})
_FOUNDATION_IMPORTS = frozenset({"Foundation", "FoundationMenu"})

# Everything else NanoFX 2.0's installer ships (tests/fixtures/mod_layouts/
# nanofx_2_0_beta.txt): Foundation's bundled QB/menu support, its 000-*
# autoload add-ons, ATP, the movies and its Damage.tga.
_NANOFX_DIST_SDK_FILES = frozenset({
    "mainmenu/mutatormenu.py", "quickbattle/quickbattlegame.py",
})
_NANOFX_DIST_SDK_PREFIXES = ("custom/advancedtechnologies/",)
_NANOFX_DIST_SDK_RE = re.compile(r"^custom/autoload/000-[^/]*\.py$")
_NANOFX_DIST_GAME_PREFIXES = ("data/movies/",)
_NANOFX_DIST_GAME_FILES = frozenset({"data/textures/effects/damage.tga"})


@dataclass(frozen=True)
class PolicyFile:
    target: str   # SDK or GAME
    rel: str      # folded index key; sdk keys carry no "scripts/" prefix


@dataclass
class PolicyDecision:
    blocked: Optional[str] = None
    refused: dict = field(default_factory=dict)   # rel -> reason


def _is_nanofx_own(f: PolicyFile) -> bool:
    return f.target == SDK and (f.rel.startswith(_NANOFX_OWN_PREFIX)
                                or f.rel in _NANOFX_OWN_FILES)


def _is_foundation_file(f: PolicyFile) -> bool:
    return f.target == SDK and (f.rel in _FOUNDATION_ALWAYS
                                or bool(_FOUNDATION_ALWAYS_RE.match(f.rel))
                                or f.rel in _FOUNDATION_CONDITIONAL)


def _in_nanofx_distribution(f: PolicyFile) -> bool:
    if f.target == SDK:
        return (_is_nanofx_own(f) or _is_foundation_file(f)
                or f.rel in _NANOFX_DIST_SDK_FILES
                or f.rel.startswith(_NANOFX_DIST_SDK_PREFIXES)
                or bool(_NANOFX_DIST_SDK_RE.match(f.rel)))
    return (f.rel.startswith(_NANOFX_DIST_GAME_PREFIXES)
            or f.rel in _NANOFX_DIST_GAME_FILES)


def needs_imports(f: PolicyFile) -> bool:
    """True for the files whose verdict depends on what they import."""
    return f.target == SDK and f.rel in _FOUNDATION_CONDITIONAL


def _foundation_reason(f: PolicyFile, imports: dict) -> Optional[str]:
    if f.target != SDK:
        return None
    if f.rel in _FOUNDATION_ALWAYS or _FOUNDATION_ALWAYS_RE.match(f.rel):
        return REASON_FOUNDATION
    if f.rel in _FOUNDATION_CONDITIONAL and (set(imports.get(f.rel, ())) & _FOUNDATION_IMPORTS):
        return REASON_FOUNDATION
    return None


def decide(files: list, imports: dict) -> PolicyDecision:
    decision = PolicyDecision()
    has_nanofx = any(f.target == SDK and f.rel in _NANOFX_MARKERS for f in files)
    if has_nanofx and all(_in_nanofx_distribution(f) for f in files):
        decision.blocked = REASON_NANOFX_BLOCKED
        return decision
    for f in files:
        if has_nanofx and _is_nanofx_own(f):
            decision.refused[f.rel] = REASON_NANOFX_BUNDLED
            continue
        reason = _foundation_reason(f, imports)
        if reason is not None:
            decision.refused[f.rel] = reason
    return decision
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_mod_policy.py tests/unit/test_path_indirection.py -v`
Expected: all PASS. The path-guard test passes, thanks to the `paths-guard`
comments.

- [ ] **Step 6: Commit**

```bash
git add engine/mod_policy.py tests/unit/test_mod_policy.py tests/fixtures/mod_layouts/nanofx_2_0_beta.txt
git commit -m "feat(mods): mod policy — block standalone NanoFX, refuse Foundation infrastructure

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire the policy into the mod index and boot report

**Files:**
- Modify: `engine/mods.py` (`ModStatus` ~L204-233, `build_index` ~L300-351,
  `describe` ~L679-716)
- Test: `tests/unit/test_mods_policy_index.py`

**Interfaces:**
- Consumes: `mod_policy.decide`, `mod_policy.needs_imports`, `mod_policy.PolicyFile` (Task 1)
- Produces:
  - `ModStatus.blocked: Optional[str]`
  - `ModStatus.refused: list[tuple[str, str]]` (`raw_rel`, reason)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_mods_policy_index.py
"""build_index applies engine/mod_policy per mod, before files enter the index
(spec 2026-10-16 §5)."""
from pathlib import Path

import pytest

from engine import mod_policy, mods

_LAYOUT = Path(__file__).resolve().parents[1] / "fixtures" / "mod_layouts" / "nanofx_2_0_beta.txt"


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


def _touch(p: Path, body: str = "x = 1\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _install_nanofx(mod_dir: Path) -> None:
    for line in _LAYOUT.read_text().splitlines():
        if line.strip():
            _touch(mod_dir / line)


def _status(idx, name):
    return {m.name: m for m in idx.mods}[name]


def test_standalone_nanofx_mod_contributes_nothing(tmp_path):
    _install_nanofx(tmp_path / "NanoFX_2.0 BETA")
    idx = mods.build_index(tmp_path)
    st = _status(idx, "NanoFX_2.0 BETA")
    assert st.blocked == mod_policy.REASON_NANOFX_BLOCKED
    assert st.placed == 0
    assert not any(mf.mod_name == "NanoFX_2.0 BETA" for mf in idx.files.values())


def test_bundled_nanofx_files_skipped_rest_loads(tmp_path):
    pack = tmp_path / "BigPack"
    _install_nanofx(pack)
    _touch(pack / "scripts" / "ships" / "MyShip.py")
    idx = mods.build_index(tmp_path)
    st = _status(idx, "BigPack")
    assert st.blocked is None
    assert idx.lookup("ships/MyShip.py") is not None
    assert idx.lookup("Custom/NanoFXv2/NanoFX_Lib.py") is None
    assert idx.lookup("Foundation.py") is None
    assert idx.lookup("Custom/AdvancedTechnologies/Data/ATP_Lib.py") is not None
    reasons = {reason for _rel, reason in st.refused}
    assert reasons == {mod_policy.REASON_NANOFX_BUNDLED, mod_policy.REASON_FOUNDATION}


def test_refused_file_does_not_displace_earlier_mod(tmp_path):
    # "A" sorts before "B": B would normally win. B's copy is Foundation's.
    _touch(tmp_path / "A" / "scripts" / "LoadTacticalSounds.py", "import App\n")
    _touch(tmp_path / "B" / "scripts" / "LoadTacticalSounds.py",
           "import App\nimport Foundation\n")
    idx = mods.build_index(tmp_path)
    hit = idx.lookup("LoadTacticalSounds.py")
    assert hit is not None and hit.mod_name == "A"
    assert not idx.conflicts
    assert _status(idx, "B").refused == [("LoadTacticalSounds.py", mod_policy.REASON_FOUNDATION)]


def test_plain_load_tactical_sounds_still_overrides(tmp_path):
    _touch(tmp_path / "A" / "scripts" / "LoadTacticalSounds.py", "import App\n")
    idx = mods.build_index(tmp_path)
    assert idx.lookup("LoadTacticalSounds.py").mod_name == "A"


def test_describe_reports_block_and_refusals(tmp_path):
    _install_nanofx(tmp_path / "NanoFX_2.0 BETA")
    _touch(tmp_path / "Pack" / "scripts" / "Foundation.py")
    _touch(tmp_path / "Pack" / "scripts" / "ships" / "A.py")
    text = mods.describe(mods.build_index(tmp_path))
    assert "NanoFX_2.0 BETA: not loaded -- " + mod_policy.REASON_NANOFX_BLOCKED in text
    assert "refused 1 file(s) -- " + mod_policy.REASON_FOUNDATION + ": Foundation.py" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mods_policy_index.py -v`
Expected: FAIL. `ModStatus` has no `blocked`, or the NanoFX files are present
in the index.

- [ ] **Step 3: Implement**

In `engine/mods.py`:

1. Add the import next to `from engine import paths`:

```python
from engine import mod_policy, paths
```

(replace the existing `from engine import paths` line).

2. In `ModStatus`, after `replaces_ships: list = None`, add:

```python
    # Whole-mod block reason (engine/mod_policy, spec 2026-10-16 §5): the mod
    # contributed NO files. None for every normally-loaded mod.
    blocked: Optional[str] = None
    # Files refused by engine/mod_policy: [(raw_rel, reason), ...].
    refused: list = None
```

and in `__post_init__` add:

```python
        if self.refused is None:
            self.refused = []
```

3. Replace the per-candidate body of `build_index`. That's everything from
   `try:` through `status.read_error = True` inside the `for candidate in
   discover_mods(root):` loop. The new body:

```python
        pending: list = []   # (path, target, raw_rel, rel) for this mod
        try:
            for path in _walk_files(candidate.content_root, status):
                if not path.is_file():
                    continue
                if _is_ignored(path, candidate.content_root):
                    status.ignored += 1
                    continue
                rel_parts = path.relative_to(candidate.content_root).parts
                top = rel_parts[0].lower()
                target = _TARGET_FOR.get(top)
                if target is None:
                    if rel_parts[0] not in status.unplaced:
                        status.unplaced.append(rel_parts[0])
                    continue
                # Under "scripts" the target root IS the scripts dir, so the
                # segment itself is dropped; under "data" it is kept, because
                # game_asset() is called with "data/..." paths.
                keep = rel_parts if target == "game" else rel_parts[1:]  # paths-guard: kind label
                raw_rel = "/".join(keep)
                pending.append((path, target, raw_rel, fold(raw_rel)))
        except OSError:
            # Belt and braces: _walk_files() already routes every directory
            # read failure to status.read_error, so this catches only a
            # failure in the per-file work above.
            status.read_error = True

        # Policy BEFORE insertion (spec 2026-10-16 §5): a refused file must
        # never displace an earlier mod's copy of the same path.
        decision = _policy_decision(pending)
        if decision.blocked:
            status.blocked = decision.blocked
            continue
        for path, target, raw_rel, rel in pending:
            reason = decision.refused.get(rel)
            if reason is not None:
                status.refused.append((raw_rel, reason))
                continue
            existing = files.get(rel)
            if existing is not None and existing.mod_name != candidate.name:
                conflicts.append((rel, existing.mod_name, candidate.name))
            files[rel] = ModFile(abs_path=path, mod_name=candidate.name,
                                 target=target, rel=rel, raw_rel=raw_rel)
            status.placed += 1
```

4. Add this helper directly after `build_index`:

```python
def _policy_decision(pending: list) -> "mod_policy.PolicyDecision":
    """engine/mod_policy's verdict for one mod's files. Reads only the few
    files whose verdict depends on their imports."""
    files = [mod_policy.PolicyFile(target, rel) for _p, target, _r, rel in pending]
    imports: dict = {}
    for path, target, _raw, rel in pending:
        if mod_policy.needs_imports(mod_policy.PolicyFile(target, rel)):
            try:
                imports[rel] = _imported_names(path.read_text(errors="replace"))
            except OSError:
                imports[rel] = set()
    return mod_policy.decide(files, imports)
```

5. In `describe()`, inside the loop directly after the
   `if status.content_root is None:` block, add:

```python
        if status.blocked:
            lines.append(f"  {status.name}: not loaded -- {status.blocked}")
            continue
```

and directly before `if status.read_error:` add:

```python
        if status.refused:
            by_reason: dict = {}
            for raw_rel, reason in status.refused:
                by_reason.setdefault(reason, []).append(raw_rel)
            for reason, rels in by_reason.items():
                shown = ", ".join(rels[:4])
                if len(rels) > 4:
                    shown += f" (+{len(rels) - 4} more)"
                line += f", refused {len(rels)} file(s) -- {reason}: {shown}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_mods_policy_index.py tests/unit/test_mods_index.py tests/unit/test_mods_report.py tests/unit/test_mods_frameworks.py tests/unit/test_mods_sdk_finder.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/mods.py tests/unit/test_mods_policy_index.py
git commit -m "feat(mods): apply mod policy before indexing; report blocked/refused files

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Blocked mods on the Mods screen

**Files:**
- Modify: `engine/ui/mods_screen_panel.py` (`ModsScreenPanel.__init__` ~L49,
  `_snapshot` return dict ~L311)
- Modify: `engine/ui/mods_screen.py` (`_build_panel` ~L39)
- Modify: `native/assets/ui-cef/index.html` (after line 99 `ms-error`),
  `native/assets/ui-cef/js/mods_screen.js` (`msRender` after the `ms-error`
  block ~L97), `native/assets/ui-cef/css/mods_screen.css` (after `.ms-error`)
- Test: `tests/unit/test_mods_screen_blocked.py`

**Interfaces:**
- Consumes: `ModStatus.blocked` (Task 2)
- Produces:
  - `ModsScreenPanel(..., blocked: list[tuple[str, str]] = ())`
  - payload key `"blocked": [{"name": str, "reason": str}]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mods_screen_blocked.py
"""The Mods screen lists mods Dauntless refused to load (spec 2026-10-16 §5.3)."""
import json

from engine import mod_policy, mods
from engine.ui import mods_screen
from engine.ui.mods_screen_panel import ModsScreenPanel


def _payload(panel):
    script = panel.render_payload()
    return json.loads(script[len("setModsScreen("):-2])


def test_panel_payload_carries_blocked_mods():
    panel = ModsScreenPanel("home", [], [], species=[], stock_classes={},
                            blocked=[("NanoFX_2.0 BETA", mod_policy.REASON_NANOFX_BLOCKED)])
    assert _payload(panel)["blocked"] == [
        {"name": "NanoFX_2.0 BETA", "reason": mod_policy.REASON_NANOFX_BLOCKED}]


def test_panel_payload_blocked_defaults_empty():
    panel = ModsScreenPanel("home", [], [], species=[], stock_classes={})
    assert _payload(panel)["blocked"] == []


def test_build_panel_reads_blocked_from_the_live_index(monkeypatch):
    st = mods.ModStatus(name="NanoFX_2.0 BETA", content_root=None,
                        blocked=mod_policy.REASON_NANOFX_BLOCKED)
    monkeypatch.setattr(mods, "current", lambda: mods.ModIndex(files={}, mods=[st]))
    panel = mods_screen._build_panel("home")
    assert _payload(panel)["blocked"][0]["name"] == "NanoFX_2.0 BETA"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_mods_screen_blocked.py -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'blocked'`.

- [ ] **Step 3: Implement**

`engine/ui/mods_screen_panel.py`:

- Add `blocked=()` to the keyword-only parameters, after `error: str = ""`.
- In the body after `self._error = error`, add `self._blocked = list(blocked)`.
- In `_snapshot`'s returned dict, after `"error": self._error,`, add:

```python
            "blocked": [{"name": n, "reason": r} for n, r in self._blocked],
```

`engine/ui/mods_screen.py` `_build_panel`: pass the blocked list. Change the
`return ModsScreenPanel(...)` call to end with:

```python
                           stock_classes=stock, writer=_write_rows, error=error,
                           blocked=[(s.name, s.blocked) for s in mods.current().mods
                                    if s.blocked])
```

`native/assets/ui-cef/index.html`: after
`<div class="ms-error" id="ms-error"></div>`, add:

```html
                <div class="ms-blocked" id="ms-blocked"></div>
```

`native/assets/ui-cef/js/mods_screen.js`: in `msRender()`, directly after
`err.style.display = p.error ? 'block' : 'none';`, add:

```js
    var blk = document.getElementById('ms-blocked');
    var bl = p.blocked || [];
    blk.innerHTML = bl.map(function (b) {
        return '<div>' + msEsc(b.name) + ' — not loaded: ' + msEsc(b.reason) + '</div>';
    }).join('');
    blk.style.display = bl.length ? 'block' : 'none';
```

`native/assets/ui-cef/css/mods_screen.css`: after the `.ms-error` rule, add:

```css
.ms-blocked { display: none; color: #fff; background: rgb(70, 52, 16); border: 1px solid rgb(216, 160, 43); padding: 6px 10px; margin-bottom: 8px; }
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_mods_screen_blocked.py tests/unit/test_mods_screen_panel.py tests/unit/test_mods_screen_orchestration.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/mods_screen_panel.py engine/ui/mods_screen.py native/assets/ui-cef/index.html native/assets/ui-cef/js/mods_screen.js native/assets/ui-cef/css/mods_screen.css tests/unit/test_mods_screen_blocked.py
git commit -m "feat(ui): Mods screen lists mods Dauntless refused to load

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Foundation `MutatorDef` and `race.name`

**Files:**
- Create: `engine/foundation/mutator.py`, `engine/foundation/race.py`
- Modify: `engine/foundation/__init__.py` (imports at top, after the
  `from engine.foundation.shipdef import ...` line)
- Modify: `engine/foundation/shipdef.py` (`self.race = race` ~L96)
- Modify: `docs/engine/foundation-api-surface.md` (the `*Def` table's
  `MutatorDef` row + a new "Implemented in Dauntless" note)
- Test: `tests/unit/test_foundation_mutatordef.py`

**Interfaces:**
- Produces:
  - `Foundation.MutatorDef(name=None, dict=None)`, with `.name`,
    `IsEnabled() -> 1`, and no-op `Enable`, `Disable`, `Activate`, `Deactivate`
  - Class attributes `Stock`, `StockSounds`, `StockShips`, `QuickBattle`
  - `engine.foundation.race.Race(str)` with `.name`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_foundation_mutatordef.py
"""Inert, always-on MutatorDef + Race.name (spec 2026-10-16 §6.1, §8.6)."""
import pytest

import Foundation
from engine import foundation


@pytest.fixture(autouse=True)
def _reset():
    foundation.reset()
    yield
    foundation.reset()


def test_mutatordef_is_always_enabled():
    m = Foundation.MutatorDef("My Mod")
    assert m.name == "My Mod"
    assert m.IsEnabled() == 1
    m.Disable()
    m.Deactivate()
    assert m.IsEnabled() == 1


def test_standard_instances_exist():
    for attr in ("Stock", "StockSounds", "StockShips", "QuickBattle"):
        assert isinstance(getattr(Foundation.MutatorDef, attr), Foundation.MutatorDef)


def test_mods_may_attach_attributes():
    mode = Foundation.MutatorDef("NanoFX v2.0 BETA")
    Foundation.MutatorDef.SomeMod = mode
    mode.bBase = 1
    assert Foundation.MutatorDef.SomeMod.bBase == 1
    del Foundation.MutatorDef.SomeMod


def test_mode_dict_accepted_by_defs():
    mode = Foundation.MutatorDef("X")
    d = Foundation.FedShipDef("Foo", 1, {"name": "Foo"}, {"modes": [mode]})
    assert d.race == "Fed"


def test_race_name_long_form():
    d = Foundation.FedShipDef("Foo", 1, {"name": "Foo"})
    assert d.race == "Fed" and d.race.name == "Federation"
    k = Foundation.KlingonShipDef("Bar", 1, {"name": "Bar"})
    assert k.race.name == "Klingon"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_foundation_mutatordef.py -v`
Expected: FAIL. `AttributeError: MutatorDef` (`engine.foundation.__getattr__`
raises for it).

- [ ] **Step 3: Implement**

```python
# engine/foundation/mutator.py
"""Foundation's MutatorDef, inert and always on (spec 2026-10-16 §6.1).

Dauntless has no mutator menu: every installed mod is on. A mutator is a named
label mods hang definitions on ({'modes': [mode]}) and attach attributes to
(Foundation.MutatorDef.NanoFX = mode; mode.bBase = 1). Enable/Disable/
Activate/Deactivate are accepted and ignored, logged once each, so the many
Autoload scripts that open with `mode = Foundation.MutatorDef("My Mod")` load.

Names from call sites and Foundation's own interface; no Foundation code.
"""
from __future__ import annotations

import sys

_noted: set = set()


def _note(op: str) -> None:
    if op in _noted:
        return
    _noted.add(op)
    print("[foundation] MutatorDef.%s ignored: every installed mod is always on"
          % op, file=sys.stderr)


class MutatorDef:
    def __init__(self, name=None, dict=None):   # `dict` is Foundation's keyword
        self.name = name

    def IsEnabled(self):
        return 1

    def Enable(self):
        _note("Enable")

    def Disable(self):
        _note("Disable")

    def Activate(self):
        _note("Activate")

    def Deactivate(self):
        _note("Deactivate")


# Foundation's four standard instances.
MutatorDef.Stock = MutatorDef("Stock Systems")
MutatorDef.StockSounds = MutatorDef(None)
MutatorDef.StockShips = MutatorDef("Stock Ships")
MutatorDef.QuickBattle = MutatorDef("Extra Ships and Mods")
```

```python
# engine/foundation/race.py
"""ShipDef.race: the factory's short label, plus Foundation's long `.name`
(spec 2026-10-16 §8.6). Only "Fed" is evidenced in the corpus (FedShipDef);
every other synthesised race label is already its long name."""
from __future__ import annotations

_LONG = {"Fed": "Federation"}


class Race(str):
    @property
    def name(self) -> str:
        return _LONG.get(str(self), str(self))
```

`engine/foundation/__init__.py`: directly after
`from engine.foundation.shipdef import ShipDefinition, ShipList, _ShipDefNamespace`, add:

```python
from engine.foundation.mutator import MutatorDef  # noqa: F401  (spec 2026-10-16 §6.1)
```

`engine/foundation/shipdef.py`: replace `self.race = race` with:

```python
        from engine.foundation.race import Race
        self.race = Race(race) if race is not None else None
```

`docs/engine/foundation-api-surface.md`: change the `MutatorDef` table row's
tier cell from `A, C` to `A, C — **implemented** (inert, always on;
engine/foundation/mutator.py)`. After the `*Def` table, add this line:

```markdown
`MutatorDef.Stock`, `.StockSounds`, `.StockShips`, `.QuickBattle` exist as the
four standard instances (spec 2026-10-16 §6.1). `OverrideDef`/`TriggerDef`
remain unimplemented.
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_foundation_mutatordef.py tests/unit/test_foundation_shim.py tests/unit/test_foundation_shipdef.py tests/unit/test_foundation_shipdef_metadata.py tests/unit/test_foundation_report.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/foundation/mutator.py engine/foundation/race.py engine/foundation/__init__.py engine/foundation/shipdef.py docs/engine/foundation-api-surface.md tests/unit/test_foundation_mutatordef.py
git commit -m "feat(foundation): inert always-on MutatorDef; ShipDef.race.name

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Glow maps — `DisableGlowAlphaMaps`, global flags, emissive and running lights

**Files:**
- Create: `engine/appc/glow_maps.py`
- Modify: `engine/appc/lod_models.py` (`LODModelManager`, after `Get`)
- Modify: `engine/appc/objects.py` (`DamageableObject`, add method near `AddDamage` ~L990)
- Modify: `engine/appc/running_lights.py` (`level_for` ~L57)
- Modify: `engine/host_loop.py` (imports ~L105; emissive block ~L9443-9449)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`, before its `    yield` ~L1816)
- Test: `tests/unit/test_glow_maps.py`

**Interfaces:**
- Produces:
  - `glow_maps.disable_object(obj)`, `glow_maps.enable_object(obj)`,
    `glow_maps.is_dark(obj) -> bool`
  - `glow_maps.set_glow_enabled(on)`, `glow_maps.glow_enabled() -> bool`
  - `glow_maps.set_specular_enabled(on)`, `glow_maps.specular_enabled() -> bool`
  - `glow_maps.reset()`
  - `host_loop._emissive_scale_for(ship, is_player: bool, hd_boost: float) -> float`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_glow_maps.py
"""DisableGlowAlphaMaps + LODModelManager glow/specular flags
(spec 2026-10-16 §6.2, §6.3)."""
import App
from engine import host_loop
from engine.appc import glow_maps, running_lights


def _ship(name="GlowShip"):
    return App.ShipClass_Create(name)


def test_disable_glow_alpha_maps_darkens_only_that_ship():
    a, b = _ship("A"), _ship("B")
    a.DisableGlowAlphaMaps()
    assert glow_maps.is_dark(a)
    assert not glow_maps.is_dark(b)


def test_global_glow_off_darkens_everything_and_on_clears_disables():
    a, b = _ship("A"), _ship("B")
    a.DisableGlowAlphaMaps()
    App.g_kLODModelManager.SetGlowMapsEnabled(0)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 0
    assert glow_maps.is_dark(a) and glow_maps.is_dark(b)
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 1
    # ASSUMPTION (spec §6.3): re-enabling clears per-object disables.
    assert not glow_maps.is_dark(a)


def test_setting_glow_on_while_on_keeps_disables():
    a = _ship("A")
    a.DisableGlowAlphaMaps()
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    assert glow_maps.is_dark(a)


def test_enable_object_relights_one_ship():
    a = _ship("A")
    a.DisableGlowAlphaMaps()
    glow_maps.enable_object(a)
    assert not glow_maps.is_dark(a)


def test_specular_flag_is_stored():
    assert App.g_kLODModelManager.AreSpecularMapsEnabled() == 1
    App.g_kLODModelManager.SetSpecularMapsEnabled(0)
    assert App.g_kLODModelManager.AreSpecularMapsEnabled() == 0


def test_emissive_scale_for():
    s = _ship("E")
    assert host_loop._emissive_scale_for(s, False, 1.7) == 1.0
    assert host_loop._emissive_scale_for(s, True, 1.7) == 1.7
    s.DisableGlowAlphaMaps()
    assert host_loop._emissive_scale_for(s, True, 1.7) == 0.0


def test_running_lights_go_out_with_glow():
    s = _ship("R")
    assert running_lights.level_for(s, 0.0, 0.0, 0.0) == 1.0
    s.DisableGlowAlphaMaps()
    assert running_lights.level_for(s, 0.0, 0.0, 0.0) == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_glow_maps.py -v`
Expected: FAIL / ERROR (`No module named 'engine.appc.glow_maps'`).

- [ ] **Step 3: Implement `glow_maps`**

```python
# engine/appc/glow_maps.py
"""Glow-map switches (spec 2026-10-16 §6.2, §6.3).

Two stock Appc surfaces:
- DamageableObject.DisableGlowAlphaMaps(): one object's self-illumination
  (hull emissive + glow map) and running lights go dark. Stock BC has no
  Enable counterpart; enable_object() is Dauntless-internal (the legacy FX
  API's flicker uses it).
- g_kLODModelManager.Set/AreGlowMapsEnabled, Set/AreSpecularMapsEnabled:
  global flags. Glow off darkens every object.

ASSUMPTION (spec §6.3, not recovered from the binary): turning global glow
back ON clears every per-object disable -- NanoFX's TurnOnLights toggles glow
off/on precisely to relight ships. Implemented with an epoch: a disable
records the current epoch; an off->on transition bumps it, so every older
disable lapses without a registry of objects.
"""
from __future__ import annotations

_glow_enabled = True
_specular_enabled = True
_epoch = 0
_ATTR = "_glow_disabled_epoch"


def disable_object(obj) -> None:
    obj.__dict__[_ATTR] = _epoch


def enable_object(obj) -> None:
    obj.__dict__.pop(_ATTR, None)


def is_dark(obj) -> bool:
    if not _glow_enabled:
        return True
    # __dict__, never getattr: TGObject.__getattr__ hands back a truthy stub
    # for a missing attribute.
    return getattr(obj, "__dict__", {}).get(_ATTR) == _epoch


def set_glow_enabled(on) -> None:
    global _glow_enabled, _epoch
    on = bool(on)
    if on and not _glow_enabled:
        _epoch += 1
    _glow_enabled = on


def glow_enabled() -> bool:
    return _glow_enabled


def set_specular_enabled(on) -> None:
    global _specular_enabled
    _specular_enabled = bool(on)


def specular_enabled() -> bool:
    return _specular_enabled


def reset() -> None:
    global _glow_enabled, _specular_enabled, _epoch
    _glow_enabled = True
    _specular_enabled = True
    _epoch += 1
```

- [ ] **Step 4: Wire the surfaces**

`engine/appc/lod_models.py`, in `class LODModelManager` after `def Get(...)`:

```python
    # Stock glow/specular switches (spec 2026-10-16 §6.3). The SDK compares
    # the getters with == 1, so they return ints.
    def SetGlowMapsEnabled(self, on) -> None:
        from engine.appc import glow_maps
        glow_maps.set_glow_enabled(on)

    def AreGlowMapsEnabled(self) -> int:
        from engine.appc import glow_maps
        return 1 if glow_maps.glow_enabled() else 0

    def SetSpecularMapsEnabled(self, on) -> None:
        from engine.appc import glow_maps
        glow_maps.set_specular_enabled(on)

    def AreSpecularMapsEnabled(self) -> int:
        from engine.appc import glow_maps
        return 1 if glow_maps.specular_enabled() else 0
```

`engine/appc/objects.py`, in `class DamageableObject`, directly before
`def AddDamage(`:

```python
    def DisableGlowAlphaMaps(self) -> None:
        """Stock surface (SDK App.py:5353; E4M5 calls it on its Kessok ships):
        this object's self-illumination and running lights go dark until
        global glow maps are switched back on. Spec 2026-10-16 §6.2."""
        from engine.appc import glow_maps
        glow_maps.disable_object(self)
```

`engine/appc/running_lights.py`: add `from engine.appc import glow_maps` to
the module's top-level imports. It's a per-frame path, and glow_maps has no
imports of its own, so there's no cycle. Then in `level_for`, directly after
the `if ship.IsDying() or ship.IsDead(): return 0.0` lines, add:

```python
    if glow_maps.is_dark(ship):
        return 0.0
```

`engine/host_loop.py`:

- After `from engine.appc.ship_death import _out_of_action as _oa` (~L105), add:

```python
from engine.appc import glow_maps as _glow_maps
```

- Before the function containing the emissive loop (search for
  `# Destroyed (dying/dead) ships lose self-illumination`), add this module-level
  function:

```python
def _emissive_scale_for(ship, is_player: bool, hd_boost: float) -> float:
    """Per-ship self-illumination scale: 0 for a dead hulk or a ship whose
    glow maps are disabled (spec 2026-10-16 §6.2), the HDR boost for the
    player, else 1."""
    if _oa(ship) or _glow_maps.is_dark(ship):
        return 0.0
    return hd_boost if is_player else 1.0
```

- Replace the six-line block

```python
        if _oa(ship):
            r.set_emissive_scale(iid, 0.0)
        elif ship is player:
            r.set_emissive_scale(iid, _hd_boost)
        else:
            r.set_emissive_scale(iid, 1.0)
```

with

```python
        r.set_emissive_scale(iid, _emissive_scale_for(ship, ship is player, _hd_boost))
```

`tests/conftest.py`: in `_reset_leakable_engine_globals`, immediately before
the fixture's `    yield`, add:

```python
    # Legacy FX API surface (spec 2026-10-16): global glow/specular flags and
    # per-object glow disables.
    try:
        from engine.appc import glow_maps as _glow_maps
        _glow_maps.reset()
    except Exception:
        pass
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/unit/test_glow_maps.py tests/unit/test_lod_model_stub_regression.py tests/unit/test_hot_path_imports_are_module_scope.py -v`
Then: `uv run pytest tests -k "running_light or emissive" -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/glow_maps.py engine/appc/lod_models.py engine/appc/objects.py engine/appc/running_lights.py engine/host_loop.py tests/conftest.py tests/unit/test_glow_maps.py
git commit -m "feat(appc): DisableGlowAlphaMaps + LODModelManager glow/specular flags

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Claimed namespace `Custom.NanoFXv2` in both finders

**Files:**
- Create: `engine/compat/__init__.py`, `engine/compat/claimed.py`
- Create: `engine/compat/fx_api/__init__.py`, `engine/compat/fx_api/NanoFX_Config.py`
- Modify: `tools/mission_harness.py` (`_SDKFinder.find_spec`, after the two
  `_PROJECT_ROOT` checks ~L604)
- Modify: `tests/conftest.py` (`_SDKFinder.find_spec`, after the two
  `PROJECT_ROOT` checks ~L634; plus a reset before `    yield`)
- Test: `tests/unit/test_claimed_namespace.py`

**Interfaces:**
- Produces:
  - `claimed.claimed_spec(fullname: str) -> Optional[ModuleSpec]`
  - `claimed.unsupported_calls() -> list[str]`
  - `claimed.reset()`
- Importable: `Custom.NanoFXv2`, `Custom.NanoFXv2.NanoFX_Config`, and any
  unprovided `Custom.NanoFXv2.*`, which loads as an unsupported module.

> Never import these modules as `engine.compat.fx_api.X`. That would create a
> second copy. Always use `Custom.NanoFXv2.X`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_claimed_namespace.py
"""Custom.NanoFXv2 is Dauntless's, always (spec 2026-10-16 §8.1)."""
import importlib
import sys

import pytest

from engine import mods
from engine.compat import claimed


@pytest.fixture(autouse=True)
def _clean():
    mods.configure(None)
    claimed.reset()
    yield
    for name in [n for n in sys.modules if n.lower().startswith("custom.nanofxv2")]:
        sys.modules.pop(name, None)
    mods.configure(None)
    claimed.reset()


def _touch(p, body="x = 1\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_package_and_config_come_from_dauntless():
    pkg = importlib.import_module("Custom.NanoFXv2")
    cfg = importlib.import_module("Custom.NanoFXv2.NanoFX_Config")
    assert "engine/compat/fx_api" in pkg.__file__.replace("\\", "/")
    assert cfg.sFX_Enabled == 1 and cfg.eFX_LightFlickerFX == "On"


def test_ours_beats_a_mod_copy(tmp_path):
    _touch(tmp_path / "M" / "scripts" / "Custom" / "NanoFXv2" / "NanoFX_Config.py",
           "sFX_Enabled = 0\n")
    mods.configure(mods.build_index(tmp_path))
    cfg = importlib.import_module("Custom.NanoFXv2.NanoFX_Config")
    assert cfg.sFX_Enabled == 1


def test_other_custom_packages_still_resolve_from_mods(tmp_path, _pop):
    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "__init__.py", "")
    _touch(tmp_path / "M" / "scripts" / "Custom" / "Ships" / "ZZTestShip.py", "MARK = 7\n")
    mods.configure(mods.build_index(tmp_path))
    _pop.extend(["Custom.Ships", "Custom.Ships.ZZTestShip"])
    m = importlib.import_module("Custom.Ships.ZZTestShip")
    assert m.MARK == 7


def test_unprovided_submodule_imports_and_logs_once(capsys):
    m = importlib.import_module("Custom.NanoFXv2.WarpFX.AI.NanoWarp")
    assert m.NanoWarp(1, 2) is None
    assert m.NanoWarp() is None
    err = capsys.readouterr().err
    assert err.count("NanoFX effect API not supported: Custom.NanoFXv2.WarpFX.AI.NanoWarp.NanoWarp") == 1
    assert claimed.unsupported_calls() == ["Custom.NanoFXv2.WarpFX.AI.NanoWarp.NanoWarp"]


def test_non_claimed_names_are_not_claimed():
    assert claimed.claimed_spec("Custom.Ships.Foo") is None
    assert claimed.claimed_spec("Custom") is None
    assert claimed.claimed_spec("App") is None


@pytest.fixture
def _pop():
    names = []
    yield names
    for n in reversed(names):
        sys.modules.pop(n, None)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_claimed_namespace.py -v`
Expected: ERROR with `No module named 'engine.compat'`.

- [ ] **Step 3: Implement**

```python
# engine/compat/__init__.py
"""Dauntless-owned implementations of legacy mod APIs (spec 2026-10-16 §8)."""
```

```python
# engine/compat/claimed.py
"""Dotted module names Dauntless claims outright (spec 2026-10-16 §8.1).

Both _SDKFinders (tools/mission_harness.py, tests/conftest.py) call
claimed_spec() after the project-root shims and BEFORE the mod overlay, so a
mod's own copy of a claimed package never loads. Only the claimed prefix is
taken: `Custom` itself and every other `Custom.*` still resolve from mods and
the SDK -- a root-level Custom/__init__.py would have shadowed them all.

A claimed name we do not provide (NanoFX's effect modules, its warp AI, ...)
still imports: it becomes an "unsupported" package whose every function logs
once and returns None. Never a truthy stub object.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# folded dotted prefix -> directory serving it
_CLAIMS = {"custom.nanofxv2": _HERE / "fx_api"}

_noted: list = []


def _note_unsupported(qualname: str) -> None:
    if qualname in _noted:
        return
    _noted.append(qualname)
    print("[legacy-fx] NanoFX effect API not supported: %s" % qualname, file=sys.stderr)


def unsupported_calls() -> list:
    return sorted(_noted)


def reset() -> None:
    _noted.clear()


class _UnsupportedModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        qualname = "%s.%s" % (self.__name__, name)

        def _unsupported(*_args, **_kwargs):
            _note_unsupported(qualname)
            return None

        _unsupported.__name__ = name
        return _unsupported


class _UnsupportedLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return _UnsupportedModule(spec.name)

    def exec_module(self, module):
        module.__path__ = []   # a package, so deeper imports reach us too


def claimed_spec(fullname: str):
    folded = fullname.lower()
    for prefix, base in _CLAIMS.items():
        if folded != prefix and not folded.startswith(prefix + "."):
            continue
        rest = fullname.split(".")[len(prefix.split(".")):]
        target = base.joinpath(*rest)
        init = target / "__init__.py"
        if init.is_file():
            return importlib.util.spec_from_file_location(
                fullname, init, submodule_search_locations=[str(target)])
        module_file = target.with_suffix(".py")
        if rest and module_file.is_file():
            return importlib.util.spec_from_file_location(fullname, module_file)
        return importlib.machinery.ModuleSpec(fullname, _UnsupportedLoader(),
                                              is_package=True)
    return None
```

```python
# engine/compat/fx_api/__init__.py
"""Custom.NanoFXv2 -- Dauntless's implementation of NanoFX 2.0's public API
(spec docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §8).
Served by engine/compat/claimed.py; import it as Custom.NanoFXv2, never as
engine.compat.fx_api. Nothing here is NanoFX's code."""
```

```python
# engine/compat/fx_api/NanoFX_Config.py
"""NanoFX 2.0's default settings, read-only (spec 2026-10-16 §8.4). Mods read
these (e.g. `if NanoFX_Config.sFX_Enabled == 1`); nothing writes them."""
TRUE = 1
FALSE = 0

bFX_Enabled = TRUE
bFX_ExpSparkFXLevel = 3
bFX_DamageSparkFXLevel = 3
bFX_DamageSparkFXDuration = 60.0
bFX_ParticleControl = 200

cFX_Enabled = TRUE
cFX_ViewScreenDefault = 8.0
cFX_ViewScreenMax = 128.0
cFX_AwayDistance = 8.0
cFX_ForwardDistance = 8.0

eFX_Enabled = TRUE
eFX_LightFlickerFX = "On"
eFX_FixBrightGlows = "On"
eFX_ExpSparkFXLevel = 3
eFX_DamageSparkFXLevel = 3
eFX_DamageSparkFXDuration = 60.0
eFX_DebrisFXLevel = 3
eFX_DebrisFXDuration = 30.0
eFX_ParticleControl = 300
eFX_RotationFX = "On"
eFX_SplashRadius = 25.0

sFX_Enabled = TRUE
sFX_AtmosphereGlowFX = "On"
sFX_PlasmaFX = "On"

wFX_Enabled = TRUE
wFX_MaxRandomDistance = 30
```

**Both finders, identical code.** In `tools/mission_harness.py`
`_SDKFinder.find_spec`, directly after the second `return None` (the
`(_PROJECT_ROOT / rel).is_dir() ...` check), insert:

```python
        # Dotted names Dauntless claims outright (spec 2026-10-16 §8.1):
        # after the project-root shims, BEFORE the mod overlay, so a mod's
        # own copy of a claimed package never loads.
        from engine.compat import claimed as _claimed
        _cspec = _claimed.claimed_spec(fullname)
        if _cspec is not None:
            return _cspec
```

In `tests/conftest.py` `_SDKFinder.find_spec`, directly after the second
`return None` (the `(PROJECT_ROOT / rel).is_dir() ...` check), insert exactly
the same seven lines.

In `tests/conftest.py` `_reset_leakable_engine_globals`, before `    yield`, add:

```python
    try:
        from engine.compat import claimed as _claimed
        _claimed.reset()
    except Exception:
        pass
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_claimed_namespace.py tests/unit/test_sdk_finder_twins_stay_in_sync.py tests/unit/test_mods_sdk_finder.py tests/unit/test_mods_pyc_finder.py -v`
Expected: all PASS. The twins test confirms both finders match.

- [ ] **Step 5: Commit**

```bash
git add engine/compat/__init__.py engine/compat/claimed.py engine/compat/fx_api/__init__.py engine/compat/fx_api/NanoFX_Config.py tools/mission_harness.py tests/conftest.py tests/unit/test_claimed_namespace.py
git commit -m "feat(compat): claim Custom.NanoFXv2 in both SDK finders

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `NanoFX_Lib` helpers and the script actions (except the controller)

**Files:**
- Create: `engine/compat/fx_api/NanoFX_Lib.py`, `engine/compat/fx_api/NanoFX_ScriptActions.py`
- Test: `tests/unit/test_fx_api_lib.py`

**Interfaces:**
- Consumes: `glow_maps.disable_object/enable_object` (Task 5);
  `App.g_kLODModelManager.SetGlowMapsEnabled` (Task 5)
- Produces:
  - **`NanoFX_Lib`:**
    - `ControlFlickers(pAction, iNum) -> 0`
    - `CreateRotationSeq(pShip, fRotation=None, fSpeed=None) -> TGSequence`
    - `CreateFlickerSeq(pShip, fTotalTime, fFlickerSpeed=0.2, sStatus="On") -> TGSequence`
    - `CreateSpecialFXSeq(pShip, pEvent, sFXType, bPlay=0) -> None`
    - `GetSpeciesName(pShip) -> str`
    - `GetOverrideColor(pShip, sEffectType) -> tuple | None`
    - `GetRaceTextureColor(sRace) -> tuple`
    - globals `g_FlickerControl`, `g_LightsOff`, `CONST_MAXFLICKERS`
    - `_shipdef_for(leaf) -> ShipDefinition | None`, used by Task 8's tests
  - **`NanoFX_ScriptActions`** (each returns `0`):
    - `DestroyTGSequence(pAction, pSequence)`
    - `SetGameSpeed(pAction, fSpeed)`
    - `TurnOffLights(pAction, pObject)`
    - `TurnOnLights(pAction)`
    - `SetShipGlow(pAction, pShip, iOn)`
    - `NanoDamageShip(pAction, pObject, vEmitPos, fRadius, fDamage)`
    - `SetNanoRotation(pAction, pShip, fRotation, fSpeed)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fx_api_lib.py
"""Custom.NanoFXv2.NanoFX_Lib + script actions on Dauntless systems
(spec 2026-10-16 §8.2, §8.4)."""
import importlib

import pytest

import App
import Foundation
from engine import foundation, ship_catalog
from engine.appc import glow_maps

ACTIONS = "Custom.NanoFXv2.NanoFX_ScriptActions"


@pytest.fixture
def lib():
    m = importlib.import_module("Custom.NanoFXv2.NanoFX_Lib")
    m.g_FlickerControl = 0
    del m.g_LightsOff[:]
    return m


@pytest.fixture
def acts():
    return importlib.import_module(ACTIONS)


@pytest.fixture(autouse=True)
def _foundation():
    foundation.reset()
    yield
    foundation.reset()


class _ScriptedShip:
    """Mirrors the one ShipClass method these helpers read."""
    def __init__(self, script):
        self._script = script

    def GetScript(self):
        return self._script


def _script_steps(seq):
    """(func_name, args, delay) of each TGScriptAction step, in order."""
    return [(s.action._func_name, s.action._args, s.delay) for s in seq._steps]


def test_flicker_ends_on_requested_state_and_caps_concurrency(lib, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    ship = App.ShipClass_Create("F")
    seq = lib.CreateFlickerSeq(ship, 1.0, 0.2, "Off")
    steps = _script_steps(seq)
    glow = [s for s in steps if s[0] == "SetShipGlow"]
    assert glow[-1] == ("SetShipGlow", (ship, 0), 1.0)
    assert {s[1][1] for s in glow[:-1]} == {0, 1}           # it actually flickers
    assert ("ControlFlickers", (-1,), 1.0) in steps
    assert lib.g_FlickerControl == 1
    lib.CreateFlickerSeq(ship, 1.0)
    assert lib.g_FlickerControl == 2
    third = lib.CreateFlickerSeq(ship, 1.0)
    assert third._steps == [] and lib.g_FlickerControl == 2
    assert "F" in lib.g_LightsOff


def test_set_ship_glow_toggles_one_ship(acts):
    ship = App.ShipClass_Create("G")
    assert acts.SetShipGlow(None, ship, 0) == 0
    assert glow_maps.is_dark(ship)
    acts.SetShipGlow(None, ship, 1)
    assert not glow_maps.is_dark(ship)
    assert acts.SetShipGlow(None, None, 0) == 0     # a ship gone mid-sequence


def test_turn_off_and_on_lights(acts):
    ship = App.ShipClass_Create("L")
    acts.TurnOffLights(None, ship)
    assert glow_maps.is_dark(ship)
    acts.TurnOnLights(None)
    assert not glow_maps.is_dark(ship)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 1


def test_set_nano_rotation_sets_spin_magnitude(acts, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: n - 1)
    ship = App.ShipClass_Create("Rot")
    acts.SetNanoRotation(None, ship, 90.0, None)
    w = ship.GetAngularVelocityTG()
    mag = (w.x ** 2 + w.y ** 2 + w.z ** 2) ** 0.5
    assert mag == pytest.approx(90.0 * App.HALF_PI / 180.0, rel=1e-4)


def test_rotation_seq_schedules_set_nano_rotation(lib, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    ship = App.ShipClass_Create("RS")
    seq = lib.CreateRotationSeq(ship, 200)
    (name, args, _delay), = _script_steps(seq)
    assert name == "SetNanoRotation" and args == (ship, 2.0, None)


def test_special_fx_seq_returns_none(lib):
    assert lib.CreateSpecialFXSeq(None, None, "PlasmaFX") is None
    assert lib.CreateSpecialFXSeq(None, None, "PlasmaFX", 1) is None


def test_species_from_catalog_then_shipdef(lib, monkeypatch):
    class _E:
        species = "Klingon"
    monkeypatch.setattr(ship_catalog, "entry",
                        lambda sid: _E() if sid == "BirdOfPrey" else None)
    assert lib.GetSpeciesName(_ScriptedShip("ships.BirdOfPrey")) == "Klingon"
    Foundation.ShipDef.ZZFoo = Foundation.FedShipDef("ZZFoo", 1, {"name": "ZZFoo", "shipFile": "ZZFoo"})
    assert lib.GetSpeciesName(_ScriptedShip("ships.ZZFoo")) == "Federation"
    assert lib.GetSpeciesName(_ScriptedShip("ships.Nothing")) == "Default"


def test_override_color_reads_the_shipdef_hook(lib):
    d = Foundation.FedShipDef("ZZBar", 1, {"name": "ZZBar", "shipFile": "ZZBar"})
    Foundation.ShipDef.ZZBar = d
    d.OverrideWarpFXColor = lambda _self: (1.0, 2.0, 3.0)
    ship = _ScriptedShip("ships.ZZBar")
    assert lib.GetOverrideColor(ship, "WarpFX") == (1.0, 2.0, 3.0)
    assert lib.GetOverrideColor(ship, "PlasmaFX") is None


def test_race_texture_colour_table(lib):
    assert lib.GetRaceTextureColor("Federation") == (55.0, 120.0, 255.0)
    assert lib.GetRaceTextureColor("Nobody") == (155.0, 120.0, 255.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_fx_api_lib.py -v`
Expected: FAIL. `Custom.NanoFXv2.NanoFX_Lib` loads as an *unsupported* module,
so calls return `None` and the asserts fail.

- [ ] **Step 3: Implement**

```python
# engine/compat/fx_api/NanoFX_ScriptActions.py
"""Custom.NanoFXv2.NanoFX_ScriptActions on Dauntless systems
(spec 2026-10-16 §8.4). Script-action functions return 0 (BC: "completed").
CreateControllerFX / SetupController are added in a later task."""
import App

from engine.appc import glow_maps


def DestroyTGSequence(pAction, pSequence):
    destroy = getattr(pSequence, "Destroy", None)
    if callable(destroy):
        destroy()
    return 0


def SetGameSpeed(pAction, fSpeed):
    import SimpleAPI
    SimpleAPI.Speed(fSpeed)
    return 0


def TurnOffLights(pAction, pObject):
    pObject.DisableGlowAlphaMaps()
    return 0


def TurnOnLights(pAction):
    # Global glow off then on: relights every ship (spec §6.3 assumption).
    App.g_kLODModelManager.SetGlowMapsEnabled(0)
    App.g_kLODModelManager.SetGlowMapsEnabled(1)
    return 0


def SetShipGlow(pAction, pShip, iOn):
    """Dauntless-internal: one ship's glow on (1) or off (0). Used by
    NanoFX_Lib.CreateFlickerSeq so a flicker never relights other ships."""
    if pShip is None:
        return 0
    if iOn:
        glow_maps.enable_object(pShip)
    else:
        glow_maps.disable_object(pShip)
    return 0


def NanoDamageShip(pAction, pObject, vEmitPos, fRadius, fDamage):
    pObject.AddDamage(vEmitPos, fRadius * 0.4, fDamage)
    return 0


def SetNanoRotation(pAction, pShip, fRotation, fSpeed):
    rnd = App.g_kSystemWrapper.GetRandomNumber
    if fSpeed:
        v = App.TGPoint3()
        v.SetXYZ(fSpeed, fSpeed, fSpeed)
        pShip.SetVelocity(v)
    if fRotation:
        kick = App.TGPoint3()
        kick.SetXYZ((rnd(20001) - 10000) / 10000.0,
                    (rnd(20001) - 10000) / 10000.0,
                    (rnd(20001) - 10000) / 10000.0)
        spin = pShip.GetAngularVelocityTG()
        spin.Add(kick)
        spin.Unitize()
        spin.Scale(fRotation * App.HALF_PI / 180.0)
        pShip.SetAngularVelocity(spin, App.PhysicsObjectClass.DIRECTION_WORLD_SPACE)
    return 0
```

```python
# engine/compat/fx_api/NanoFX_Lib.py
"""Custom.NanoFXv2.NanoFX_Lib -- NanoFX 2.0's public helper API rebuilt on
Dauntless systems (spec 2026-10-16 §8.2). The import name is fixed by the
mods that call it; nothing here is NanoFX's code. CreateAtmosphereFX is
added in a later task."""
import App

_ACTIONS = "Custom.NanoFXv2.NanoFX_ScriptActions"

CONST_MAXFLICKERS = 2
g_FlickerControl = 0
g_LightsOff = []

# NanoFX's race colour table (0-255), as data.
_RACE_RGB = {
    "Federation": (55.0, 120.0, 255.0),
    "Klingon":    (255.0, 20.0, 0.0),
    "Romulan":    (0.0, 248.0, 130.0),
    "Cardassian": (255.0, 200.0, 0.0),
    "Ferengi":    (255.0, 180.0, 0.0),
    "Kessok":     (182.0, 0.0, 201.0),
    "Dominion":   (182.0, 0.0, 201.0),
    "Borg":       (0.0, 248.0, 150.0),
}
_DEFAULT_RGB = (155.0, 120.0, 255.0)

_COLOUR_HOOKS = {
    "ExpFX": "OverrideExpFXColor",
    "PlasmaFX": "OverridePlasmaFXColor",
    "WarpFX": "OverrideWarpFXColor",
}


def ControlFlickers(pAction, iNum):
    global g_FlickerControl
    g_FlickerControl = g_FlickerControl + iNum
    return 0


def _action(func, *args):
    return App.TGScriptAction_Create(_ACTIONS, func, *args)


def CreateRotationSeq(pShip, fRotation=None, fSpeed=None):
    seq = App.TGSequence_Create()
    if fRotation is not None:
        fRotation = (App.g_kSystemWrapper.GetRandomNumber(int(fRotation)) + fRotation) * 0.01
    seq.AddAction(_action("SetNanoRotation", pShip, fRotation, fSpeed))
    return seq


def CreateFlickerSeq(pShip, fTotalTime, fFlickerSpeed=0.2, sStatus="On"):
    """Toggle pShip's glow every fFlickerSpeed s (+0..0.1 s jitter), ending on
    or off per sStatus. At most CONST_MAXFLICKERS run at once; beyond that an
    empty sequence comes back, as NanoFX did."""
    seq = App.TGSequence_Create()
    if g_FlickerControl >= CONST_MAXFLICKERS:
        return seq
    rnd = App.g_kSystemWrapper.GetRandomNumber
    t = 0.0
    while t < fTotalTime - 0.1:
        off_at = t + rnd(100) * 0.001
        seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, 0), off_at)
        seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, 1),
                      off_at + fFlickerSpeed * 0.5)
        t = t + fFlickerSpeed
    final = 0 if sStatus == "Off" else 1
    seq.AddAction(App.TGScriptAction_Create(_ACTIONS, "SetShipGlow", pShip, final),
                  float(fTotalTime))
    name = pShip.GetName() if pShip is not None else None
    if name is not None:
        if final == 0 and name not in g_LightsOff:
            g_LightsOff.append(name)
        if final == 1 and name in g_LightsOff:
            g_LightsOff.remove(name)
    ControlFlickers(None, 1)
    seq.AddAction(App.TGScriptAction_Create(__name__, "ControlFlickers", -1),
                  float(fTotalTime))
    return seq


def CreateSpecialFXSeq(pShip, pEvent, sFXType, bPlay=0):
    """None for every type: NanoFX's own plasma vent returned None on most
    calls, and its other types are effect modules we do not run."""
    return None


def _leaf(pShip):
    try:
        return str(pShip.GetScript()).split(".")[-1]
    except Exception:
        return ""


def _shipdef_for(leaf):
    if not leaf:
        return None
    from engine.foundation.shipdef import all_definitions
    from engine.foundation import shipdef_overrides
    wanted = leaf.lower()
    for d in list(all_definitions()) + list(shipdef_overrides.stock_definitions()):
        if str(getattr(d, "shipFile", "") or "").lower() == wanted:
            return d
    return None


def GetSpeciesName(pShip):
    leaf = _leaf(pShip)
    if not leaf:
        return "Default"
    from engine import ship_catalog
    entry = ship_catalog.entry(leaf)
    if entry is not None and getattr(entry, "species", None):
        return str(entry.species)
    d = _shipdef_for(leaf)
    race = getattr(d, "race", None) if d is not None else None
    if race:
        return getattr(race, "name", str(race))
    return "Default"


def GetOverrideColor(pShip, sEffectType):
    attr = _COLOUR_HOOKS.get(sEffectType)
    d = _shipdef_for(_leaf(pShip))
    if attr is None or d is None:
        return None
    hook = d.__dict__.get(attr)
    if hook is None:
        return None
    return hook(None)


def GetRaceTextureColor(sRace):
    return _RACE_RGB.get(sRace, _DEFAULT_RGB)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_fx_api_lib.py tests/unit/test_claimed_namespace.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/compat/fx_api/NanoFX_Lib.py engine/compat/fx_api/NanoFX_ScriptActions.py tests/unit/test_fx_api_lib.py
git commit -m "feat(compat): NanoFX_Lib helpers + script actions on Dauntless systems

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Mod-requested atmospheres + `CreateAtmosphereFX`

**Files:**
- Create: `native/assets/planets/atmosphere_classes.json`
- Modify: `engine/planets/atmosphere.py` (`_requested` near `_overrides`;
  `resolve_key` ~L234; `resolve` ~L246; new `request`, `clear_requested`,
  `class_preset`)
- Modify: `engine/compat/fx_api/NanoFX_Lib.py` (add `CreateAtmosphereFX`)
- Modify: `engine/host_loop.py` (session teardown, next to
  `_atmosphere.clear_live()` ~L6320)
- Modify: `tests/conftest.py` (reset before `    yield`)
- Modify: spec §8.3, the last bullet ("Mod-requested entries are cleared with
  the set")
- Test: `tests/unit/test_fx_api_atmosphere.py`

**Interfaces:**
- Produces:
  - `atmosphere.request(set_name, obj_name, entry: dict)`
  - `atmosphere.clear_requested()`
  - `atmosphere.class_preset(name: str) -> dict | None`
  - `NanoFX_Lib.CreateAtmosphereFX(pPlanet, sNifPath=..., sTexturePath="Class-M") -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fx_api_atmosphere.py
"""CreateAtmosphereFX -> mod-requested atmosphere; catalogue always wins
(spec 2026-10-16 §8.3)."""
import importlib

import pytest

from engine.planets import atmosphere


class _Set:
    def __init__(self, name):
        self._n = name

    def GetName(self):
        return self._n


class _Planet:
    """Mirrors the two Planet methods CreateAtmosphereFX reads."""
    def __init__(self, set_name, name):
        self._s, self._n = _Set(set_name), name

    def GetContainingSet(self):
        return self._s

    def GetName(self):
        return self._n


@pytest.fixture
def lib():
    return importlib.import_module("Custom.NanoFXv2.NanoFX_Lib")


@pytest.fixture(autouse=True)
def _clean():
    atmosphere.clear_requested()
    yield
    atmosphere.clear_requested()


def test_uncatalogued_planet_gets_the_class_preset(lib):
    lib.CreateAtmosphereFX(_Planet("ModSys1", "Mod World"),
                           "data/models/environment/zz_custom_world.nif", "Class-H")
    a = atmosphere.resolve("ModSys1", "Mod World", "data/models/environment/zz_custom_world.nif")
    preset = atmosphere.parse_entry("Class-H", atmosphere.class_preset("Class-H"))
    assert a == preset


def test_catalogued_stem_wins(lib):
    lib.CreateAtmosphereFX(_Planet("ModSys1", "Blue"),
                           "data/models/environment/earth.nif", "Class-H")
    a = atmosphere.resolve("ModSys1", "Blue", "data/models/environment/earth.nif")
    assert a == atmosphere.parse_entry("earth", atmosphere.load()["earth"])


def test_unknown_class_falls_back_to_default(lib):
    lib.CreateAtmosphereFX(_Planet("S", "P"), "data/x/zz_other.nif", "Class-Q")
    a = atmosphere.resolve("S", "P", "data/x/zz_other.nif")
    assert a == atmosphere.parse_entry("Class-M", atmosphere.class_preset("Class-M"))


def test_unrequested_uncatalogued_stays_airless():
    assert atmosphere.resolve("S", "P", "data/x/zz_nothing.nif") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_fx_api_atmosphere.py -v`
Expected: FAIL with `AttributeError: module 'engine.planets.atmosphere' has no attribute 'clear_requested'`.

- [ ] **Step 3: Implement**

`native/assets/planets/atmosphere_classes.json`:

```json
{
  "Class-M": {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "Class-O": {"color": "#8EC8FF", "thickness": 0.035, "density": 1.0, "limb": 1.0},
  "Class-H": {"color": "#F0DCB0", "thickness": 0.02, "density": 0.5, "limb": 0.8},
  "Class-K": {"color": "#E08A50", "thickness": 0.02, "density": 0.5, "limb": 0.8},
  "default": "Class-M"
}
```

`engine/planets/atmosphere.py`:

- After the `_overrides: dict = {}` block, add:

```python
# Mod-requested atmospheres (spec 2026-10-16 §8.3): "<set>/<name>" -> raw
# entry in the catalogue's own schema, from the legacy FX API's
# CreateAtmosphereFX. Consulted only when the catalogue has neither the
# "<set>/<name>" override nor the NIF stem. Kept for the whole session (a set
# can be re-realised without re-running its Initialize), cleared at session
# teardown and by the test suite's autouse reset.
_requested: dict = {}
```

- In `resolve_key`, replace its final line
  `return stem if stem in raw else None` with:

```python
    if stem in raw:
        return stem
    requested = f"{set_name}/{obj_name}"
    return requested if set_name and requested in _requested else None
```

- In `resolve`, replace the `try:` block with:

```python
    entry = load().get(key)
    if entry is None:
        entry = _requested.get(key)
    try:
        return parse_entry(key, entry)
    except (ValueError, KeyError, TypeError) as e:
        _warn(str(catalogue_path()), key, f"malformed ({e}); treated as airless")
        return None
```

- At the end of the module, add:

```python
def request(set_name: str, obj_name: str, entry: dict) -> None:
    """Register a mod-requested atmosphere for one planet (spec 2026-10-16
    §8.3). The catalogue always wins over it."""
    _requested[f"{set_name}/{obj_name}"] = dict(entry)


def clear_requested() -> None:
    _requested.clear()


def class_presets_path() -> pathlib.Path:
    return catalogue_path().with_name("atmosphere_classes.json")


def class_preset(name: str):
    """The planet-class preset entry for `name` ("Class-M", ...), else the
    file's "default" class, else None. Resolved at use."""
    try:
        presets = json.loads(class_presets_path().read_text())
    except (OSError, ValueError) as e:
        _warn(str(class_presets_path()), "atmosphere_classes.json", f"unreadable ({e})")
        return None
    entry = presets.get(name)
    if not isinstance(entry, dict):
        entry = presets.get(presets.get("default", ""))
    return dict(entry) if isinstance(entry, dict) else None
```

`engine/compat/fx_api/NanoFX_Lib.py`: append

```python
def CreateAtmosphereFX(pPlanet, sNifPath="data/models/environment/planet.nif",
                       sTexturePath="Class-M"):
    """Request an atmosphere for pPlanet from the planet-class preset named
    by sTexturePath ("Class-M", "Class-H", ...). Creates no objects: NanoFX's
    sun-shell layers are not built (spec 2026-10-16 §8.3)."""
    from engine.planets import atmosphere
    try:
        set_name = pPlanet.GetContainingSet().GetName()
        obj_name = pPlanet.GetName()
    except Exception:
        return
    preset = atmosphere.class_preset(sTexturePath)
    if preset is not None and set_name and obj_name:
        atmosphere.request(set_name, obj_name, preset)
```

`engine/host_loop.py`: directly after the line `_atmosphere.clear_live()`
(~L6320), add `_atmosphere.clear_requested()` at the same indentation.

`tests/conftest.py` reset (before `    yield`):

```python
    try:
        from engine.planets import atmosphere as _atmo_req
        _atmo_req.clear_requested()
    except Exception:
        pass
```

Spec §8.3: replace the bullet "Mod-requested entries are cleared with the set
(`clear_live_for_set`)." with:

```markdown
- Mod-requested entries are kept for the whole session and cleared at session
  teardown (next to `clear_live()`). A set can be re-realised without
  re-running its `Initialize`, so clearing per set would lose them.
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_fx_api_atmosphere.py tests -k atmosphere -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/assets/planets/atmosphere_classes.json engine/planets/atmosphere.py engine/compat/fx_api/NanoFX_Lib.py engine/host_loop.py tests/conftest.py tests/unit/test_fx_api_atmosphere.py docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md
git commit -m "feat(planets): mod-requested atmospheres via CreateAtmosphereFX

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Production particle guard (characterisation, BEFORE any particle change)

**Files:**
- Create: `tests/unit/test_stock_particle_output_unchanged.py`
- Create: `tests/fixtures/stock_particle_descriptors.json` (generated in Step 2)

**Interfaces:**
- Produces: a golden file pinning the stock path's descriptors. Tasks 10-13
  must keep it green.

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_stock_particle_output_unchanged.py
"""Production particle output is byte-identical across the legacy FX API work
(spec 2026-10-16 §9 guard). Drives the stock Effects helpers the engine calls,
plus direct CreateTarget on the stock sheets, and compares every descriptor
with a golden captured BEFORE the particle changes.

Regenerate ONLY on purpose: UPDATE_STOCK_PARTICLE_GOLDEN=1 uv run pytest <this file>.
Keys added later must hold their documented defaults on this path."""
import json
import os
from pathlib import Path

import pytest

import App
from engine.appc import particles as P

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "stock_particle_descriptors.json"

# Descriptor keys introduced by the legacy FX API work, and the value each
# must hold for every stock caller.
NEW_KEY_DEFAULTS = {"playback": 0, "fps": 0.0, "pivot": [0.0, 0.0],
                    "orient": 0, "roll_rate": 0.0}


def _direct(path):
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(path)
    c.AddColorKey(0.0, 1.0, 0.5, 0.25)
    c.AddAlphaKey(0.0, 1.0)
    c.AddSizeKey(0.0, 2.0)
    P.EffectAction_Create(c).Start()


def _cases():
    import Effects
    return {
        "smoke_high": lambda: Effects.CreateSmokeHigh(2.0, 1.5, 0.6, object(), None, None, object()).Start(),
        "debris_smoke": lambda: Effects.CreateDebrisSmoke(5.0, 0.8, object(), 0, object()).Start(),
        "debris_sparks": lambda: Effects.CreateDebrisSparks(3.0, object(), 0, object()).Start(),
        "explosion_a": lambda: _direct("data/Textures/Effects/ExplosionA.tga"),
        "explosion_b": lambda: _direct("data/Textures/Effects/ExplosionB.tga"),
        "explosion_a_case": lambda: _direct("Data\\Textures\\Effects\\EXPLOSIONA.TGA"),
        "rough": lambda: _direct("data/rough.tga"),
        "unknown": lambda: _direct("data/Textures/whatever.tga"),
    }


def _snapshot(monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    out = {}
    for name, run in _cases().items():
        P.reset()
        run()
        descs = P.snapshot_descriptors()
        for d in descs:
            d.pop("seed", None)
        out[name] = json.loads(json.dumps(descs))
    P.reset()
    return out


def test_stock_particle_descriptors_unchanged(monkeypatch):
    got = _snapshot(monkeypatch)
    if os.environ.get("UPDATE_STOCK_PARTICLE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        pytest.skip("golden regenerated")
    want = json.loads(GOLDEN.read_text())
    assert set(got) == set(want)
    for case, descs in want.items():
        assert len(got[case]) == len(descs), case
        for i, (g, w) in enumerate(zip(got[case], descs)):
            for k, v in w.items():
                assert g.get(k) == v, f"{case}[{i}].{k}: {g.get(k)!r} != {v!r}"
            for k in set(g) - set(w):
                assert k in NEW_KEY_DEFAULTS, f"{case}[{i}] unexpected new key {k}"
                assert g[k] == NEW_KEY_DEFAULTS[k], f"{case}[{i}].{k} = {g[k]!r}"
```

- [ ] **Step 2: Generate the golden on the UNCHANGED particle code**

Run: `UPDATE_STOCK_PARTICLE_GOLDEN=1 uv run pytest tests/unit/test_stock_particle_output_unchanged.py -v`
Expected: SKIPPED ("golden regenerated"), and
`tests/fixtures/stock_particle_descriptors.json` exists with 8 cases. Check
that `explosion_a` has `atlas_cols == 8` and the colour keys multiplied by 2.0.

- [ ] **Step 3: Run normally**

Run: `uv run pytest tests/unit/test_stock_particle_output_unchanged.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_stock_particle_output_unchanged.py tests/fixtures/stock_particle_descriptors.json
git commit -m "test(particles): golden guard for stock particle output

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Sprite library runtime, `CreateTarget` integration and `g_kTextureAnimManager`

**Files:**
- Create: `engine/sprites.py`, `engine/appc/texture_anim.py`
- Create: `native/assets/sprites/manifest.json`, `native/assets/sprites/legacy_aliases.json`
- Modify: `engine/appc/particles.py` (remove `_KNOWN_SHEET_TEXTURES` /
  `_TEXTURE_BRIGHTNESS`; new init attrs; `CreateTarget`)
- Modify: `App.py` (bind `g_kTextureAnimManager` next to `g_kLODModelManager` ~L967)
- Modify: `tests/conftest.py` (resets before `    yield`)
- Test: `tests/unit/test_sprite_library.py`, `tests/unit/test_texture_anim_manager.py`

**Interfaces:**
- Produces:
  - `sprites.SpriteRef(sprite_id, kind, texture_path, cols, rows, playback,
    fps, scale, brightness, pivot, orient, native)` (frozen dataclass)
  - `sprites.resolve(path) -> SpriteRef | None`
  - `sprites.resolve_legacy(path)`, `sprites.stock_ref(path)`
  - `sprites.sprites_root() -> Path`, `sprites.fold_path(p) -> str`,
    `sprites.reset()`
  - `sprites.PLAYBACK_CODES`, `sprites.ORIENT_CODES`
  - `texture_anim.g_kTextureAnimManager`, `texture_anim.grid_for(path)`,
    `texture_anim.reset()`
  - Controller attributes:
    - `_library_kind` (str, default `"sprite"`)
    - `_native` (dict | None)
    - `_playback` (int, 0)
    - `_fps` (0.0)
    - `_size_scale` (1.0)
    - `_pivot` ((0.0, 0.0))
    - `_orient` (0)
    - `_roll_rate` (0.0)

- [ ] **Step 1: Write the data files**

`native/assets/sprites/manifest.json`:

```json
{
  "version": 1,
  "sprites": {
    "stock_explosion_a": {"stock": "data/Textures/Effects/ExplosionA.tga", "match_stock": true, "grid": [8, 8], "playback": "life_columns", "brightness": 2.0},
    "stock_explosion_b": {"stock": "data/Textures/Effects/ExplosionB.tga", "match_stock": true, "grid": [8, 8], "playback": "life_columns"},
    "stock_explode_sharp": {"stock": "data/explodeSharp.tga"},
    "stock_round": {"stock": "data/round.tga"},
    "stock_smooth": {"stock": "data/smooth.tga"},
    "stock_rough": {"stock": "data/rough.tga"},
    "stock_sun_flares_white": {"stock": "data/Textures/Effects/SunFlaresWhite.tga", "grid": [8, 8], "playback": "life_columns"},
    "stock_starstreak": {"stock": "data/Textures/starstreak.tga"},
    "stock_spacedust": {"stock": "data/Textures/spacedust.tga"},
    "stock_warpflash": {"stock": "data/Textures/warpflash3.tga"},

    "fireball": {"file": "fireball.png", "grid": [8, 4], "playback": "life_sequence", "fallback": "stock_explosion_a"},
    "fireball_hot": {"fallback": "stock_explosion_b"},
    "fire_jet": {"file": "fire_jet.png", "grid": [8, 4], "playback": "life_sequence", "pivot": [0.0, -1.0], "orient": "emit_dir", "fallback": "stock_explosion_a"},
    "glint_burst": {"file": "glint_burst.png", "grid": [4, 4], "playback": "life_sequence", "scale": 0.6, "fallback": "stock_explode_sharp"},
    "glint": {"fallback": "stock_round"},
    "spark": {"fallback": "stock_smooth"},
    "plasma_puff": {"fallback": "stock_sun_flares_white"},
    "debris_chunk": {"file": "debris_chunk.png", "grid": [6, 4], "playback": "loop", "fps": 8.0, "fallback": "stock_rough"},
    "shock_ring": {"kind": "native", "native": {"effect": "shockwave", "radius_scale": 1.0}},
    "shock_sphere": {"file": "shock_sphere.png", "grid": [8, 4], "playback": "life_sequence", "fallback": "stock_explode_sharp"},
    "nova_flare": {"kind": "none"},
    "star_streak": {"fallback": "stock_starstreak"},
    "space_dust": {"fallback": "stock_spacedust"},
    "warp_flash": {"fallback": "stock_warpflash"},
    "none": {"kind": "none"}
  }
}
```

`native/assets/sprites/legacy_aliases.json`:

```json
{
  "version": 1,
  "exact": {
    "scripts/custom/nanofxv2/explosionfx/gfx/explosions/exp_expdeb.tga": "fireball_hot",
    "scripts/custom/nanofxv2/explosionfx/gfx/explosions/exp_flare.tga": "fire_jet",
    "scripts/custom/nanofxv2/explosionfx/gfx/explosions/exp_starflare.tga": "fire_jet",
    "scripts/custom/nanofxv2/specialfx/gfx/weapon/weaponflash.tga": "glint_burst",
    "scripts/custom/nanofxv2/warpfx/gfx/nacelleflash/nacelleflash_core.tga": "glint_burst",
    "scripts/custom/nanofxv2/warpfx/gfx/nacelleflash/nacelleflash_outter.tga": "glint_burst",
    "scripts/custom/nanofxv2/specialfx/gfx/blinker/blinker.tga": "glint",
    "scripts/custom/nanofxv2/specialfx/gfx/blinker/blank.tga": "none",
    "scripts/custom/nanofxv2/explosionfx/gfx/particles/sparks.tga": "spark",
    "scripts/custom/nanofxv2/specialfx/gfx/plasma/plasma.tga": "plasma_puff",
    "scripts/custom/nanofxv2/warpfx/gfx/starstreaks_nano.tga": "star_streak",
    "scripts/custom/nanofxv2/warpfx/gfx/spacedust_nano.tga": "space_dust"
  },
  "prefix": {
    "scripts/custom/nanofxv2/explosionfx/gfx/explosions/": "fireball",
    "scripts/custom/nanofxv2/explosionfx/gfx/expflash/": "glint_burst",
    "scripts/custom/nanofxv2/explosionfx/gfx/debris/": "debris_chunk",
    "scripts/custom/nanofxv2/explosionfx/gfx/novaring/": "shock_ring",
    "scripts/custom/nanofxv2/explosionfx/gfx/novasphere/": "shock_sphere",
    "scripts/custom/nanofxv2/explosionfx/gfx/novaflash/": "nova_flare",
    "scripts/custom/nanofxv2/warpfx/gfx/warpflash/": "warp_flash"
  }
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/unit/test_sprite_library.py
"""Sprite library: legacy paths -> Dauntless sprites (spec 2026-10-16 §7)."""
import pytest

from engine import sprites
from engine.appc import particles as P

NANO = "scripts/Custom/NanoFXv2/"


@pytest.fixture(autouse=True)
def _reset():
    sprites.reset()
    yield
    sprites.reset()


def test_alias_resolution_is_spelling_blind():
    a = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano3.tga")
    b = sprites.resolve("./scripts\\Custom\\NanoFXv2\\ExplosionFX\\Gfx\\Explosions\\Exp_Nano3.TGA")
    assert a is not None and a == b and a.sprite_id == "fireball"


def test_exact_beats_prefix():
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Flare.tga").sprite_id == "fire_jet"


def test_missing_png_uses_fallback_runtime_fields(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text((sprites.sprites_root() / "manifest.json").read_text())
    (tmp_path / "legacy_aliases.json").write_text((sprites.sprites_root() / "legacy_aliases.json").read_text())
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    ref = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga")
    assert ref.sprite_id == "fireball"
    assert ref.texture_path == "data/Textures/Effects/ExplosionA.tga"
    assert (ref.cols, ref.rows, ref.playback, ref.brightness) == (8, 8, "life_columns", 2.0)


def test_present_png_is_used(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text((sprites.sprites_root() / "manifest.json").read_text())
    (tmp_path / "legacy_aliases.json").write_text((sprites.sprites_root() / "legacy_aliases.json").read_text())
    (tmp_path / "fireball.png").write_bytes(b"png")
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    ref = sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga")
    assert ref.texture_path == str(tmp_path / "fireball.png")
    assert (ref.cols, ref.rows, ref.playback) == (8, 4, "life_sequence")


def test_native_and_none_kinds():
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga").kind == "native"
    assert sprites.resolve(NANO + "SpecialFX/Gfx/Blinker/Blank.tga").kind == "none"


def test_stock_sheet_keeps_the_callers_path():
    ref = sprites.resolve("data/Textures/Effects/ExplosionB.tga")
    assert ref.texture_path == "data/Textures/Effects/ExplosionB.tga"
    assert (ref.cols, ref.rows) == (8, 8)


def test_fallback_only_stock_entries_do_not_match_callers():
    assert sprites.resolve("data/Textures/Effects/SunFlaresWhite.tga") is None
    assert sprites.resolve("data/rough.tga") is None


def test_unreadable_manifest_passes_paths_through(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text("{not json")
    monkeypatch.setattr(sprites, "sprites_root", lambda: tmp_path)
    assert sprites.resolve(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga") is None
    c = P.AnimTSParticleController_Create()
    c.CreateTarget("data/Textures/Effects/ExplosionA.tga")
    assert c._texture_path == "data/Textures/Effects/ExplosionA.tga"


def test_create_target_applies_library_fields():
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(NANO + "SpecialFX/Gfx/Weapon/WeaponFlash.tga")
    assert c._library_kind == "sprite"
    assert c._size_scale in (0.6, 1.0)  # 0.6 once glint_burst.png exists, fallback otherwise
    c2 = P.AnimTSParticleController_Create()
    c2.CreateTarget(NANO + "ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga")
    assert c2._library_kind == "native" and c2._native["effect"] == "shockwave"
```

```python
# tests/unit/test_texture_anim_manager.py
"""g_kTextureAnimManager records frame rects and infers regular grids
(spec 2026-10-16 §7.5)."""
import App
from engine.appc import particles as P
from engine.appc import texture_anim


def _declare(path, cols, rows):
    track = App.g_kTextureAnimManager.AddContainer(path).AddTextureTrack(cols * rows)
    i = 0
    for r in range(rows):
        for c in range(cols):
            x, y = c / cols, r / rows
            track.SetFrame(i, x, y + 1.0 / rows, x + 1.0 / cols, y)
            i += 1


def test_regular_grid_is_inferred_and_used_by_create_target():
    _declare("scripts/Custom/MyMod/Gfx/Boom.tga", 8, 4)
    assert texture_anim.grid_for("scripts\\custom\\mymod\\gfx\\BOOM.tga") == (8, 4)
    c = P.AnimTSParticleController_Create()
    c.CreateTarget("scripts/Custom/MyMod/Gfx/Boom.tga")
    assert (c._atlas_cols, c._atlas_rows) == (8, 4)


def test_irregular_track_is_ignored():
    track = App.g_kTextureAnimManager.AddContainer("x/odd.tga").AddTextureTrack(2)
    track.SetFrame(0, 0.0, 0.5, 0.5, 0.0)
    track.SetFrame(1, 0.5, 0.3, 1.0, 0.0)
    assert texture_anim.grid_for("x/odd.tga") is None
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/unit/test_sprite_library.py tests/unit/test_texture_anim_manager.py -v`
Expected: ERROR with `No module named 'engine.sprites'`.

- [ ] **Step 4: Implement `engine/sprites.py`**

```python
# engine/sprites.py
"""Sprite library: a texture path given to CreateTarget is a NAME for a kind
of effect, resolved to Dauntless-owned art, a stock BC sprite, a native
effect, or nothing (spec 2026-10-16 §7).

Data: native/assets/sprites/manifest.json (entries) and legacy_aliases.json
(folded legacy path / folder prefix -> id). Both resolved at USE and memoised;
an unreadable file means "no library" -- every path passes through unchanged.

Stock entries with "match_stock" carry today's per-texture grid/brightness for
the stock sheets (they replace particles._KNOWN_SHEET_TEXTURES); they match a
caller's path by BASENAME and keep the caller's own path, so production
descriptors are byte-identical. Other stock entries exist only as fallbacks.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from engine import paths

PLAYBACK_CODES = {"life_columns": 0, "life_sequence": 1, "loop": 2}
ORIENT_CODES = {"camera": 0, "emit_dir": 1}

_memo: dict = {}


@dataclass(frozen=True)
class SpriteRef:
    sprite_id: str
    kind: str                 # "sprite" | "native" | "none"
    texture_path: str         # absolute PNG, or a game-relative stock path; "" if not a sprite
    cols: int = 1
    rows: int = 1
    playback: str = "life_columns"
    fps: float = 0.0
    scale: float = 1.0
    brightness: float = 1.0
    pivot: tuple = (0.0, 0.0)
    orient: str = "camera"
    native: Optional[dict] = None


def sprites_root() -> Path:
    return paths.project_asset_root() / "sprites"


def fold_path(p) -> str:
    s = str(p).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/").lower()


def reset() -> None:
    _memo.clear()


def _load(name: str) -> dict:
    path = sprites_root() / name
    key = str(path)
    if key not in _memo:
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("top level must be an object")
        except (OSError, ValueError) as e:
            print(f"[sprites] {name} unreadable ({e}); legacy paths pass through",
                  file=sys.stderr)
            data = {}
        _memo[key] = data
    return _memo[key]


def _entries() -> dict:
    s = _load("manifest.json").get("sprites", {})
    return s if isinstance(s, dict) else {}


def _ref(sprite_id: str, entry: dict, texture_path: str) -> SpriteRef:
    grid = entry.get("grid", [1, 1])
    return SpriteRef(
        sprite_id=sprite_id,
        kind=entry.get("kind", "sprite"),
        texture_path=texture_path,
        cols=int(grid[0]), rows=int(grid[1]),
        playback=entry.get("playback", "life_columns"),
        fps=float(entry.get("fps", 0.0)),
        scale=float(entry.get("scale", 1.0)),
        brightness=float(entry.get("brightness", 1.0)),
        pivot=tuple(float(v) for v in entry.get("pivot", [0.0, 0.0])),
        orient=entry.get("orient", "camera"),
        native=entry.get("native"),
    )


def _sprite_ref(sprite_id: str, seen: tuple = ()) -> Optional[SpriteRef]:
    entry = _entries().get(sprite_id)
    if not isinstance(entry, dict):
        return None
    if entry.get("kind", "sprite") != "sprite":
        return _ref(sprite_id, entry, "")
    file_name = entry.get("file")
    if file_name:
        png = sprites_root() / file_name
        if png.is_file():
            return _ref(sprite_id, entry, str(png))
    if entry.get("stock"):
        return _ref(sprite_id, entry, entry["stock"])
    fallback = entry.get("fallback")
    if fallback and fallback not in seen:
        ref = _sprite_ref(fallback, seen + (sprite_id,))
        if ref is not None:
            # The fallback's runtime fields, under our id.
            return replace(ref, sprite_id=sprite_id)
    return None


def resolve_legacy(path) -> Optional[SpriteRef]:
    key = fold_path(path)
    aliases = _load("legacy_aliases.json")
    sprite_id = (aliases.get("exact") or {}).get(key)
    if sprite_id is None:
        best = ""
        for prefix, pid in (aliases.get("prefix") or {}).items():
            if key.startswith(prefix) and len(prefix) > len(best):
                best, sprite_id = prefix, pid
    return _sprite_ref(sprite_id) if sprite_id else None


def stock_ref(path) -> Optional[SpriteRef]:
    base = fold_path(path).rsplit("/", 1)[-1]
    for sprite_id, entry in _entries().items():
        if not (isinstance(entry, dict) and entry.get("match_stock")):
            continue
        if fold_path(entry.get("stock", "")).rsplit("/", 1)[-1] == base:
            return _ref(sprite_id, entry, str(path))
    return None


def resolve(path) -> Optional[SpriteRef]:
    return resolve_legacy(path) or stock_ref(path)
```

- [ ] **Step 5: Implement `engine/appc/texture_anim.py`**

```python
# engine/appc/texture_anim.py
"""App.g_kTextureAnimManager (spec 2026-10-16 §7.5).

Stock BC (Tactical/EffectTextures.py) and mods declare a texture's animation
frames as UV rects: AddContainer(path).AddTextureTrack(n).SetFrame(i, l, t, r, b).
We record them and, when they form a regular grid, report (cols, rows) for
that path; CreateTarget uses it when the sprite library has no entry. An
irregular track is logged once and ignored.
"""
from __future__ import annotations

import sys


def _fold(p) -> str:
    return str(p).replace("\\", "/").strip().strip("/").lower()


class _Track:
    def __init__(self, n):
        self.frames = [None] * max(0, int(n))

    def SetFrame(self, i, left, top, right, bottom):
        i = int(i)
        if 0 <= i < len(self.frames):
            self.frames[i] = (float(left), float(top), float(right), float(bottom))


class _Container:
    def __init__(self, path):
        self.path = path
        self.tracks = []

    def AddTextureTrack(self, n):
        t = _Track(n)
        self.tracks.append(t)
        return t


class TextureAnimManager:
    def __init__(self):
        self._containers: dict = {}
        self._warned: set = set()

    def AddContainer(self, path):
        c = _Container(path)
        self._containers[_fold(path)] = c
        return c

    def grid_for(self, path):
        c = self._containers.get(_fold(path))
        if c is None:
            return None
        rects = [f for t in c.tracks for f in t.frames if f is not None]
        grid = _infer_grid(rects)
        if grid is None and rects and c.path not in self._warned:
            self._warned.add(c.path)
            print(f"[texture-anim] {c.path}: frames are not a regular grid; ignored",
                  file=sys.stderr)
        return grid


def _infer_grid(rects):
    if not rects:
        return None
    eps = 1e-3
    w = abs(rects[0][2] - rects[0][0])
    h = abs(rects[0][1] - rects[0][3])
    if w <= 0 or h <= 0:
        return None
    cols, rows = round(1.0 / w), round(1.0 / h)
    if cols < 1 or rows < 1 or abs(cols * w - 1) > eps or abs(rows * h - 1) > eps:
        return None
    for left, top, right, bottom in rects:
        if abs(abs(right - left) - w) > eps or abs(abs(top - bottom) - h) > eps:
            return None
        lo_x, lo_y = min(left, right), min(top, bottom)
        if abs(lo_x / w - round(lo_x / w)) > eps or abs(lo_y / h - round(lo_y / h)) > eps:
            return None
    return (int(cols), int(rows))


g_kTextureAnimManager = TextureAnimManager()


def grid_for(path):
    return g_kTextureAnimManager.grid_for(path)


def reset() -> None:
    g_kTextureAnimManager._containers.clear()
    g_kTextureAnimManager._warned.clear()
```

- [ ] **Step 6: Wire `CreateTarget` and `App`**

`engine/appc/particles.py`:

- Delete the `_KNOWN_SHEET_TEXTURES` and `_TEXTURE_BRIGHTNESS` dicts and their
  comments (their values now live in `manifest.json` as `stock_explosion_a/b`).
- Add near the top imports:

```python
from engine import sprites as _sprites
from engine.appc import texture_anim as _texture_anim
```

- In `AnimTSParticleController.__init__`, after `self._atlas_rows = 1`, add:

```python
        # Sprite library (spec 2026-10-16 §7). Defaults reproduce today's
        # behaviour exactly; only a library-resolved path changes them.
        self._library_kind = "sprite"   # "sprite" | "native" | "none"
        self._native = None
        self._playback = 0
        self._fps = 0.0
        self._size_scale = 1.0
        self._pivot = (0.0, 0.0)
        self._orient = 0
        self._roll_rate = 0.0
```

- Replace `CreateTarget` with:

```python
    def CreateTarget(self, path):
        """Bind the target texture. A path the sprite library knows (spec
        2026-10-16 §7: legacy alias, or a stock sheet) applies its entry; a
        path declared through g_kTextureAnimManager gets its grid; anything
        else is used as-is, as before."""
        self._texture_path = path
        ref = _sprites.resolve(path)
        if ref is None:
            grid = _texture_anim.grid_for(path)
            if grid is not None:
                self._atlas_cols, self._atlas_rows = grid
            self._brightness = 1.0
            return
        self._library_kind = ref.kind
        self._native = ref.native
        if ref.kind != "sprite":
            return
        self._texture_path = ref.texture_path
        self._atlas_cols, self._atlas_rows = ref.cols, ref.rows
        self._brightness = ref.brightness
        self._playback = _sprites.PLAYBACK_CODES.get(ref.playback, 0)
        self._fps = ref.fps
        self._size_scale = ref.scale
        self._pivot = ref.pivot
        self._orient = _sprites.ORIENT_CODES.get(ref.orient, 0)
```

`App.py`: directly after `g_kLODModelManager = LODModelManager()`, add:

```python
from engine.appc.texture_anim import g_kTextureAnimManager  # noqa: E402 (spec 2026-10-16 §7.5)
```

`tests/conftest.py` reset (before `    yield`):

```python
    try:
        from engine import sprites as _sprites
        _sprites.reset()
        from engine.appc import texture_anim as _texture_anim
        _texture_anim.reset()
    except Exception:
        pass
```

- [ ] **Step 7: Run to verify pass, including the guard**

Run: `uv run pytest tests/unit/test_sprite_library.py tests/unit/test_texture_anim_manager.py tests/unit/test_stock_particle_output_unchanged.py tests/unit/test_particles_sdk_unmodified.py tests/unit/test_path_indirection.py -v`
Then: `uv run pytest tests -k "particle or explosion or smoke" -q`
Expected: all PASS. The guard must stay green; no stock descriptor value may
change.

- [ ] **Step 8: Commit**

```bash
git add engine/sprites.py engine/appc/texture_anim.py engine/appc/particles.py App.py tests/conftest.py native/assets/sprites/manifest.json native/assets/sprites/legacy_aliases.json tests/unit/test_sprite_library.py tests/unit/test_texture_anim_manager.py
git commit -m "feat(particles): sprite library + legacy aliases at CreateTarget; real g_kTextureAnimManager

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Particle playback, pivot and orient — descriptor, bindings, C++ pass, PNG decode

**Files:**
- Modify: `engine/appc/particles.py` (`_descriptor_for` return dict)
- Modify: `native/src/renderer/include/renderer/frame.h` (`ParticleEmitterDescriptor`)
- Modify: `native/src/renderer/include/renderer/particle_math.h` (add `atlas_cell`)
- Modify: `native/src/renderer/particle_pass.cc` (`texture_for` decode; frame/row
  block ~L276-285; streak branch ~L298-305; per-emitter `u_pivot`)
- Modify: `native/src/renderer/include/renderer/particle_pass.h` (public `loaded_texture_count()`)
- Modify: `native/src/renderer/shaders/hit_vfx.vert` (`u_pivot`)
- Modify: `native/src/renderer/hit_vfx_pass.cc` (reset `u_pivot` beside `u_roll` ~L238)
- Modify: `native/src/host/host_bindings.cc` (`set_particle_emitters` dict reads ~L5853-5857)
- Create: `native/tests/renderer/fixtures/sprite_4x4.png`
- Test: `tests/unit/test_particle_playback_descriptors.py`,
  `native/tests/renderer/particle_math_test.cc`,
  `native/tests/renderer/particle_pass_test.cc`,
  `tests/host/test_legacy_fx_bindings.py`

**Interfaces:**
- Consumes: controller attrs from Task 10
- Produces:
  - Descriptor keys `playback` (int), `fps` (float), `pivot` ((x, y)),
    `orient` (int), `roll_rate` (float); size keys scaled by `_size_scale`
  - C++ `renderer::atlas_cell(int playback, float t, float tau, int cols,
    int rows, float fps, float hash_row, float hash_phase) -> glm::ivec2`
  - `ParticlePass::loaded_texture_count() const -> std::size_t`

- [ ] **Step 1: Write the failing Python test**

```python
# tests/unit/test_particle_playback_descriptors.py
"""Library fields reach the render descriptor (spec 2026-10-16 §7.4, §7.5)."""
from engine.appc import particles as P


def test_descriptor_carries_library_fields_and_scaled_sizes():
    P.reset()
    c = P.AnimTSParticleController_Create()
    c.AddSizeKey(0.0, 2.0)
    c._playback, c._fps, c._pivot, c._orient = 2, 8.0, (0.0, -1.0), 1
    c._size_scale, c._roll_rate = 0.5, 2.0
    P.EffectAction_Create(c).Start()
    (d,) = P.snapshot_descriptors()
    assert (d["playback"], d["fps"], d["pivot"], d["orient"], d["roll_rate"]) == (2, 8.0, (0.0, -1.0), 1, 2.0)
    assert d["size_keys"] == [(0.0, 1.0)]
    P.reset()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_particle_playback_descriptors.py -v`
Expected: FAIL with `KeyError: 'playback'`.

- [ ] **Step 3: Python descriptor**

In `_descriptor_for`'s returned dict, replace
`"size_keys":         list(c._size_keys),` with:

```python
        "size_keys":         [(t, s * c._size_scale) for (t, s) in c._size_keys],
```

and add, after `"seed": float(c._seed),`:

```python
        # Sprite library (spec 2026-10-16 §7.4). Defaults = today's behaviour.
        "playback":          int(c._playback),
        "fps":               float(c._fps),
        "pivot":             (float(c._pivot[0]), float(c._pivot[1])),
        "orient":            int(c._orient),
        "roll_rate":         float(c._roll_rate),
```

Run: `uv run pytest tests/unit/test_particle_playback_descriptors.py tests/unit/test_stock_particle_output_unchanged.py -v`
Expected: PASS. The guard sees the new keys at their defaults.

- [ ] **Step 4: Write the failing C++ tests**

Append to `native/tests/renderer/particle_math_test.cc`:

```cpp
TEST(ParticleMath, AtlasCellLifeColumnsMatchesLegacyRule) {
    // playback 0: frame = t*cols along the columns; row from the hash.
    EXPECT_EQ(atlas_cell(0, 0.0f, 0.0f, 8, 8, 0.0f, 0.99f, 0.0f), glm::ivec2(0, 7));
    EXPECT_EQ(atlas_cell(0, 0.5f, 0.0f, 8, 8, 0.0f, 0.0f, 0.0f), glm::ivec2(4, 0));
    EXPECT_EQ(atlas_cell(0, 1.0f, 0.0f, 8, 8, 0.0f, 0.0f, 0.0f), glm::ivec2(7, 0));
    EXPECT_EQ(atlas_cell(0, 0.3f, 0.0f, 1, 1, 0.0f, 0.7f, 0.0f), glm::ivec2(0, 0));
}

TEST(ParticleMath, AtlasCellLifeSequenceWalksTheWholeSheetRowMajor) {
    // 8x4 = 32 frames; t in [0,1] walks rows top to bottom.
    EXPECT_EQ(atlas_cell(1, 0.0f,    0.0f, 8, 4, 0.0f, 0.9f, 0.9f), glm::ivec2(0, 0));
    EXPECT_EQ(atlas_cell(1, 9.0f / 32.0f, 0.0f, 8, 4, 0.0f, 0.9f, 0.9f), glm::ivec2(1, 1));
    EXPECT_EQ(atlas_cell(1, 1.0f,    0.0f, 8, 4, 0.0f, 0.9f, 0.9f), glm::ivec2(7, 3));
}

TEST(ParticleMath, AtlasCellLoopCyclesColumnsAtFpsOnAStableRow) {
    // 6 columns, start column from hash_phase 0.5 -> 3; 8 fps.
    EXPECT_EQ(atlas_cell(2, 0.9f, 0.0f,   6, 4, 8.0f, 0.3f, 0.5f), glm::ivec2(3, 1));
    EXPECT_EQ(atlas_cell(2, 0.9f, 0.125f, 6, 4, 8.0f, 0.3f, 0.5f), glm::ivec2(4, 1));
    EXPECT_EQ(atlas_cell(2, 0.9f, 0.375f, 6, 4, 8.0f, 0.3f, 0.5f), glm::ivec2(0, 1));
}
```

Append to `native/tests/renderer/particle_pass_test.cc`:

```cpp
// Sprite-library PNGs (spec 2026-10-16 §7.5): the pass decodes PNG as well as
// TGA, so an absolute PNG path renders.
TEST_F(ParticlePassTest, AbsolutePngTextureLoads) {
    const auto png = (project_root() / "native" / "tests" / "renderer" /
                      "fixtures" / "sprite_4x4.png").string();
    renderer::ParticleEmitterDescriptor e;
    e.texture_path = png;
    e.emit_life = 1.0f;
    e.emit_frequency = 0.5f;
    e.effect_age = 0.25f;
    e.num_size_keys = 1; e.size_keys[0].t = 0.0f; e.size_keys[0].v = 1.0f;
    e.playback = 1;
    e.atlas_cols = 2; e.atlas_rows = 2;
    e.pivot = glm::vec2(0.0f, -1.0f);
    e.orient = 1;
    renderer::ParticlePass pass;
    scenegraph::World world;
    scenegraph::Camera cam;
    pass.render({e}, world, cam, *pipeline);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_EQ(pass.loaded_texture_count(), 1u);
}
```

> If `scenegraph::World` / `scenegraph::Camera` need constructor arguments in
> this file, copy the construction used by the existing render tests in the
> same file (search `pass.render(` there) instead of the two defaults above.

Create the fixture PNG:

Run: `uv run python -c "from PIL import Image; Image.new('RGBA', (4, 4), (255, 255, 255, 255)).save('native/tests/renderer/fixtures/sprite_4x4.png')"`
(`mkdir -p native/tests/renderer/fixtures` first.)

- [ ] **Step 5: Implement C++**

`frame.h` — in `ParticleEmitterDescriptor`, after `float seed = 0.0f;`:

```cpp
    // Sprite-library playback (spec 2026-10-16 §7.4). 0 = life_columns
    // (today: frame along the columns over life, random variant row);
    // 1 = life_sequence (whole sheet row-major over life); 2 = loop (random
    // variant row, columns cycle at `fps` from a random start).
    int       playback = 0;
    float     fps      = 0.0f;
    // Quad anchor in corner units: (0,0) = centred (today); (0,-1) puts the
    // quad's bottom-centre on the emit point.
    glm::vec2 pivot{0.0f};
    // 0 = camera-facing (today); 1 = stretched along the emit direction
    // (streak path, length = particle size).
    int       orient   = 0;
```

`particle_math.h` — add before the namespace's closing brace:

```cpp
/// Sprite-sheet cell (column, row) for one particle (spec 2026-10-16 §7.4).
/// `t` is life fraction [0,1], `tau` the particle's age in seconds,
/// `hash_row`/`hash_phase` stable per-particle hashes in [0,1).
/// playback 0 reproduces the pre-library rule exactly.
inline glm::ivec2 atlas_cell(int playback, float t, float tau, int cols, int rows,
                             float fps, float hash_row, float hash_phase) {
    cols = std::max(1, cols);
    rows = std::max(1, rows);
    t = std::clamp(t, 0.0f, 1.0f);
    if (playback == 1) {
        const int n = cols * rows;
        const int f = std::min(static_cast<int>(t * n), n - 1);
        return {f % cols, f / cols};
    }
    const int row = std::min(static_cast<int>(hash_row * rows), rows - 1);
    if (playback == 2) {
        const int start = std::min(static_cast<int>(hash_phase * cols), cols - 1);
        const int step = fps > 0.0f
            ? static_cast<int>(std::floor(std::max(0.0f, tau) * fps)) : 0;
        return {(start + step) % cols, row};
    }
    const int frame = std::min(std::max(static_cast<int>(t * cols), 0), cols - 1);
    return {frame, row};
}
```

`particle_pass.h`: in `public:` after `render(...)`, add:

```cpp
    /// Textures decoded and uploaded so far (tests).
    std::size_t loaded_texture_count() const;
```

`particle_pass.cc`:

- In `texture_for`, replace `assets::Image img = assets::decode_tga(bytes);`
  with `assets::Image img = assets::decode_image(bytes);`.
- Add the definition after `texture_for`:

```cpp
std::size_t ParticlePass::loaded_texture_count() const {
    std::size_t n = 0;
    for (const auto& kv : textures_)
        if (kv.second && kv.second->id() != 0) ++n;
    return n;
}
```

- Replace the frame/row block. That's the lines from
  `// Sprite-sheet cell: frame steps along the columns...` through
  `shader.set_vec2("u_atlas_cell", glm::vec2(float(frame), float(row)));`.
  The replacement:

```cpp
            // Sprite-sheet cell (spec 2026-10-16 §7.4); playback 0 is the
            // pre-library rule: frame along the columns over life, variant
            // row from a stable per-particle hash.
            const glm::vec2 rh = hash3(hseed, i + 4099);
            const glm::ivec2 cell = atlas_cell(e.playback, t, tau, atlas_cols,
                                               atlas_rows, e.fps, rh.x, rh.y);
            shader.set_vec2("u_atlas_cell", glm::vec2(float(cell.x), float(cell.y)));
```

- Directly after `shader.set_float("u_roll", 0.0f);` (the per-emitter
  defaults), add:

```cpp
        shader.set_vec2("u_pivot", e.pivot);
```

- Replace the streak block

```cpp
            if (e.tail_length > 0.0f) {
```

with

```cpp
            if (e.orient == 1) {
                // Stretched along the emit direction (fire_jet): the quad's
                // long axis is the hit normal, length = particle size.
                shader.set_vec3 ("u_streak_axis",   emit_dir_world);
                shader.set_float("u_streak_length", size);
            } else if (e.tail_length > 0.0f) {
```

(keep the rest of that if/else unchanged).

`hit_vfx.vert`: add `uniform vec2  u_pivot;` after `uniform float u_roll;`,
and replace the `world_pos` line with:

```glsl
    // u_pivot (corner units) moves the quad's anchor off its centre; (0,0)
    // = centred (default; hit VFX always). Spec 2026-10-16 §7.4.
    vec3 world_pos = u_world_position + right * (a_corner.x - u_pivot.x)
                                      + up    * (a_corner.y - u_pivot.y);
```

`hit_vfx_pass.cc`: directly after `shader.set_float("u_roll", 0.0f);`
(~L238), add:

```cpp
    shader.set_vec2("u_pivot", glm::vec2(0.0f));   // shared shader: never inherit the particle pass's anchor
```

`host_bindings.cc` (`set_particle_emitters`): after
`e.seed = d.contains("seed") ? ...;`, add:

```cpp
                  // Sprite library (spec 2026-10-16 §7.4); defaults = today.
                  e.playback  = d.contains("playback")  ? d["playback"].cast<int>()    : 0;
                  e.fps       = d.contains("fps")       ? d["fps"].cast<float>()       : 0.0f;
                  e.orient    = d.contains("orient")    ? d["orient"].cast<int>()      : 0;
                  e.roll_rate = d.contains("roll_rate") ? d["roll_rate"].cast<float>() : 0.0f;
                  if (d.contains("pivot")) {
                      auto p = d["pivot"].cast<std::tuple<float, float>>();
                      e.pivot = glm::vec2(std::get<0>(p), std::get<1>(p));
                  }
```

- [ ] **Step 6: Write the host binding test**

```python
# tests/host/test_legacy_fx_bindings.py
"""New particle/shockwave dict keys cross the binding (spec 2026-10-16 §7.4/§7.5)."""
import os


def test_particle_and_shockwave_keys_accepted():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "legacy-fx")
    try:
        h.set_particle_emitters([{
            "instance_id": None, "emit_pos": (0.0, 0.0, 0.0), "emit_dir": (0.0, 1.0, 0.0),
            "emit_vel_world": (0.0, 0.0, 0.0), "inherit": 0.0, "emit_velocity": 0.0,
            "angle_variance": 0.0, "emit_life": 1.0, "emit_life_variance": 0.0,
            "emit_frequency": 0.5, "effect_age": 0.1, "stop_age": 1.0, "draw_old_to_new": 1,
            "color_keys": [(0.0, 1.0, 1.0, 1.0)], "alpha_keys": [(0.0, 1.0)],
            "size_keys": [(0.0, 1.0)], "texture_path": "", "seed": 0.5,
            "playback": 2, "fps": 8.0, "pivot": (0.0, -1.0), "orient": 1, "roll_rate": 2.0,
        }])
        h.set_shockwaves([{"world_center": (0.0, 0.0, 0.0), "max_radius": 5.0,
                           "age": 0.1, "lifetime": 1.0, "tint": (0.2, 0.5, 1.0)}])
        h.frame()
    finally:
        h.set_particle_emitters([])
        h.set_shockwaves([])
        h.shutdown()
```

(The `tint` key is wired in Task 12; until then the binding ignores unknown
keys, so this test passes here too.)

- [ ] **Step 7: Rebuild (shader edit → reconfigure) and run**

```bash
cmake -B build -S .
cmake --build build -j
ctest --test-dir build -R "ParticleMath|ParticlePass" --output-on-failure
uv run pytest tests/host/test_legacy_fx_bindings.py tests/unit/test_particle_playback_descriptors.py tests/unit/test_stock_particle_output_unchanged.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/appc/particles.py native/src/renderer/include/renderer/frame.h native/src/renderer/include/renderer/particle_math.h native/src/renderer/include/renderer/particle_pass.h native/src/renderer/particle_pass.cc native/src/renderer/shaders/hit_vfx.vert native/src/renderer/hit_vfx_pass.cc native/src/host/host_bindings.cc native/tests/renderer/particle_math_test.cc native/tests/renderer/particle_pass_test.cc native/tests/renderer/fixtures/sprite_4x4.png tests/unit/test_particle_playback_descriptors.py tests/host/test_legacy_fx_bindings.py
git commit -m "feat(renderer): particle playback modes, pivot, emit-dir orient, PNG sprites

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Native shockwave kind (tint) and the `none` kind

**Files:**
- Modify: `engine/appc/shockwaves.py` (`spawn`, `render_data`)
- Modify: `engine/appc/particles.py` (`EffectAction.Start`; new
  `_spawn_native`, `_controller_world_pos`, `_mid_colour`)
- Modify: `native/src/renderer/include/renderer/frame.h` (`ShockwaveDescriptor.tint`)
- Modify: `native/src/renderer/shockwave_pass.cc` (`u_tint`), `native/src/renderer/shaders/shockwave.frag`
- Modify: `native/src/host/host_bindings.cc` (`set_shockwaves`)
- Test: `tests/unit/test_sprite_native_kinds.py`

**Interfaces:**
- Consumes: `_library_kind`, `_native` (Task 10)
- Produces:
  - `shockwaves.spawn(center_world, max_radius_gu, lifetime, pSet=None,
    tint=None)`; `render_data()` entries carry `"tint": (r, g, b)`
  - `ShockwaveDescriptor::tint` (default `glm::vec3(1)`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_sprite_native_kinds.py
"""kind:native (shock_ring -> procedural shockwave) and kind:none
(spec 2026-10-16 §7.5)."""
import App
from engine.appc import particles as P
from engine.appc import shockwaves

RING = "scripts/Custom/NanoFXv2/ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga"
BLANK = "scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga"


def _ring_controller(ship):
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(RING)
    c.AddColorKey(0.1, 1.0, 1.0, 1.0)
    c.AddColorKey(0.5, 0.2, 0.4, 1.0)
    c.AddColorKey(1.0, 0.0, 0.0, 0.0)
    c.AddSizeKey(0.0, 12.0)
    c.AddSizeKey(1.0, 12.0)
    c.SetEmitLife(64 / 15.0)
    c.SetEmitFromObject(ship)
    c.SetEmitPositionAndDirection(App.TGPoint3(0.0, 2.0, 0.0), App.TGPoint3(0.0, 0.0, 0.0))
    return c


def test_native_ring_spawns_a_tinted_shockwave_not_an_emitter():
    shockwaves.reset()
    P.reset()
    ship = App.ShipClass_Create("Nova")
    ship.SetTranslateXYZ(10.0, 0.0, 0.0)
    P.EffectAction_Create(_ring_controller(ship)).Start()
    assert P.active_count() == 0
    (sw,) = shockwaves.render_data()
    assert sw["max_radius"] == 12.0
    assert abs(sw["lifetime"] - 64 / 15.0) < 1e-9
    assert sw["tint"] == (0.2, 0.4, 1.0)
    cx, cy, cz = sw["world_center"]
    assert abs(cx - 10.0) < 1e-6 and abs(cy - 2.0) < 1e-6
    shockwaves.reset()


def test_none_kind_never_emits():
    P.reset()
    c = P.AnimTSParticleController_Create()
    c.CreateTarget(BLANK)
    P.EffectAction_Create(c).Start()
    assert P.active_count() == 0


def test_default_tint_is_white():
    shockwaves.reset()
    shockwaves.spawn((0.0, 0.0, 0.0), 5.0, 1.0)
    assert shockwaves.render_data()[0]["tint"] == (1.0, 1.0, 1.0)
    shockwaves.reset()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_sprite_native_kinds.py -v`
Expected: FAIL. `active_count() == 1` (a native ring was registered as an
emitter), or `KeyError: 'tint'`.

- [ ] **Step 3: Implement Python**

`engine/appc/shockwaves.py`: change `spawn`'s signature to
`def spawn(center_world, max_radius_gu, lifetime, pSet=None, tint=None) -> None:`.
In its appended dict, add
`"tint": tuple(float(v) for v in tint) if tint is not None else (1.0, 1.0, 1.0),`.
In `render_data`'s per-entry dict, add `"tint": entry["tint"],`. Append to
`spawn`'s docstring:
`` `tint` (r, g, b) multiplies the ring colour; white = today's look (spec 2026-10-16 §7.5). ``

`engine/appc/particles.py`: replace `EffectAction.Start` with:

```python
    def Start(self):
        c = self._controller
        kind = c.__dict__.get("_library_kind", "sprite")
        if kind == "none":
            return
        if kind == "native":
            _spawn_native(c)
            return
        register(c)
```

and add these module-level functions before `class EffectAction`:

```python
def _mid_colour(c):
    """The colour key nearest t=0.5 (NanoFX puts the caller's tint there)."""
    if not c._color_keys:
        return None
    t, r, g, b = min(c._color_keys, key=lambda k: abs(k[0] - 0.5))
    return (float(r), float(g), float(b))


def _controller_world_pos(c):
    """World position of a controller's emit point, or None."""
    from engine.appc.math import TGPoint3
    from engine.appc.objects import _ObjectNodeRef
    from engine.appc.sets import SetEffectRoot
    x, y, z = _vec3(c._emit_pos)
    src = c._emit_from
    if src is None and isinstance(c._attach_node, _ObjectNodeRef):
        src = c._attach_node._owner()
    if src is None:
        return (x, y, z) if isinstance(c._attach_node, SetEffectRoot) else None
    if hasattr(src, "GetWorldLocation") and hasattr(src, "GetWorldRotation"):
        p = TGPoint3(x, y, z)
        p.MultMatrixLeft(src.GetWorldRotation())
        loc = src.GetWorldLocation()
        return (loc.x + p.x, loc.y + p.y, loc.z + p.z)
    if hasattr(src, "x"):
        return (src.x, src.y, src.z)
    return None


def _spawn_native(c):
    """kind:native (spec 2026-10-16 §7.5): play a Dauntless procedural effect
    instead of registering a particle emitter."""
    native = c._native or {}
    if native.get("effect") != "shockwave":
        return
    from engine.appc import shockwaves
    center = _controller_world_pos(c)
    if center is None:
        return
    sizes = [s for (_t, s) in c._size_keys] or [1.0]
    radius = max(sizes) * float(native.get("radius_scale", 1.0))
    shockwaves.spawn(center, radius, max(0.1, float(c._emit_life)),
                     _controller_set(c), tint=_mid_colour(c))
```

- [ ] **Step 4: Implement C++**

`frame.h` `ShockwaveDescriptor`: after `float lifetime;`, add:

```cpp
    glm::vec3 tint{1.0f};   // ring colour multiplier; white = default look (spec 2026-10-16 §7.5)
```

`shockwave_pass.cc`: inside the per-shockwave loop, after
`sh.set_float("u_t", t);`, add `sh.set_vec3("u_tint", s.tint);`.

`shockwave.frag`: add `uniform vec3  u_tint;` after `uniform float u_t;`.
Change `vec3 col = ring_col * ring_alpha + flash_col * flash;` to:

```glsl
    vec3 col = ring_col * u_tint * ring_alpha + flash_col * flash;
```

`host_bindings.cc` `set_shockwaves`: after `s.lifetime = ...;`, add:

```cpp
                  if (d.contains("tint")) {
                      auto t = d["tint"].cast<std::tuple<float, float, float>>();
                      s.tint = {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
                  }
```

- [ ] **Step 5: Rebuild (shader edit → reconfigure) and run**

```bash
cmake -B build -S .
cmake --build build -j
uv run pytest tests/unit/test_sprite_native_kinds.py tests/host/test_legacy_fx_bindings.py tests/unit/test_stock_particle_output_unchanged.py -v
uv run pytest tests -k "shockwave or warp_core" -q
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/shockwaves.py engine/appc/particles.py native/src/renderer/include/renderer/frame.h native/src/renderer/shockwave_pass.cc native/src/renderer/shaders/shockwave.frag native/src/host/host_bindings.cc tests/unit/test_sprite_native_kinds.py
git commit -m "feat(vfx): native shockwave sprite kind with tint; none kind

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: `CreateControllerFX` / `SetupController`, `DebrisParticleController_Create`, `App.NiPoint3`

**Files:**
- Modify: `engine/appc/particles.py` (add `DebrisParticleController` + factory)
- Modify: `App.py` (particles import list ~L327-334; `NiPoint3`)
- Modify: `engine/compat/fx_api/NanoFX_ScriptActions.py` (append)
- Test: `tests/unit/test_fx_api_controller.py`

**Interfaces:**
- Produces:
  - `App.DebrisParticleController_Create(total_life=1.0, duration=1.0, emit_rate=0.005)`
  - `App.NiPoint3 = TGPoint3`
  - `NanoFX_ScriptActions.SetupController(sType, fSize, fLifeTime, fRed, fGreen, fBlue, fBrightness)`
  - `NanoFX_ScriptActions.CreateControllerFX(sFile, pEmitFrom, pAttachTo,
    fSize=1.0, vEmitPos=None, vEmitDir=None, bInheritVel=0, bDetach=0,
    fFrequency=0.2, fLifeTime=0.1, fEmitVel=None, fVariance=None,
    fDamping=None, vGravity=None, iTiming=32, sType="Normal", fRed=255.0,
    fGreen=255.0, fBlue=255.0, fBrightness=0.6) -> EffectAction`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_fx_api_controller.py
"""CreateControllerFX the NanoFX way (spec 2026-10-16 §8.4)."""
import importlib

import pytest

import App
from engine.appc import particles as P

NANO = "scripts/Custom/NanoFXv2/"


@pytest.fixture
def acts():
    return importlib.import_module("Custom.NanoFXv2.NanoFX_ScriptActions")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    P.reset()
    yield
    P.reset()


def test_stub_emit_source_anchors_to_attach_owner(acts):
    ship = App.ShipClass_Create("Host")
    stub = App.TGModelUtils_CastNodeToAVObject(ship.GetNode())
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Explosions/Exp_Nano1.tga",
                                     stub, ship.GetNode(), 2.0,
                                     App.NiPoint3(0.0, 3.0, 0.0), App.NiPoint3(0.0, 0.0, 1.0))
    c = action.GetController()
    assert c._emit_from is ship
    assert (c._emit_pos.x, c._emit_pos.y, c._emit_pos.z) == (0.0, 3.0, 0.0)


def test_normal_type_keys_and_timing(acts):
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/ExpFlash/ExpFlash1.tga",
                                     None, App.ShipClass_Create("K").GetNode(), 1.5,
                                     iTiming=15, fLifeTime=0.1, fRed=51.0, fGreen=102.0,
                                     fBlue=255.0, fBrightness=0.4)
    c = action.GetController()
    assert c._color_keys == [(0.1, 1.0, 1.0, 1.0), (0.4, 0.2, 0.4, 1.0), (1.0, 0.0, 0.0, 0.0)]
    assert c._alpha_keys == [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)]
    assert c._size_keys == [(0.0, 1.5), (1.0, 1.5)]
    assert c._emit_life == 1.0 and c._effect_life_time == pytest.approx(1.1)
    assert c._blend_mode == 1


def test_debris_type_uses_a_debris_controller(acts):
    action = acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Debris/nano_debris1a.tga",
                                     None, App.ShipClass_Create("D").GetNode(), 4.0,
                                     fLifeTime=30.0, sType="Debris", fDamping=0.1)
    c = action.GetController()
    assert isinstance(c, P.DebrisParticleController)
    assert c._roll_rate > 0.0 and c._damping == 0.1


def test_gravity_is_accepted_and_ignored(acts):
    acts.CreateControllerFX(NANO + "ExplosionFX/Gfx/Particles/Sparks.tga", None,
                            App.ShipClass_Create("G").GetNode(), vGravity=App.NiPoint3(0, 0, -9))


def test_niPoint3_is_a_real_point():
    p = App.NiPoint3(1.0, 2.0, 3.0)
    assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_fx_api_controller.py -v`
Expected: FAIL. `CreateControllerFX` doesn't exist (`AttributeError`), and
`NiPoint3` returns a stub.

- [ ] **Step 3: Implement**

`engine/appc/particles.py`: after `SparkParticleController_Create`, add:

```python
class DebrisParticleController(SparkParticleController):
    """Tumbling debris billboards (spec 2026-10-16 §8.4): a spark controller
    with no tail and a billboard tumble. No stock script creates one, so
    adding it changes no production effect."""
    def __init__(self, total_life=1.0, duration=1.0, emit_rate=0.005):
        super().__init__(total_life, duration, emit_rate)
        self._roll_rate = 2.0


def DebrisParticleController_Create(total_life=1.0, duration=1.0, emit_rate=0.005):
    return DebrisParticleController(total_life, duration, emit_rate)
```

`App.py`:

- Add `DebrisParticleController_Create,` to the `from engine.appc.particles import (...)` list.
- Find where `TGPoint3` is imported into `App` (search `TGPoint3` in `App.py`'s
  imports) and add directly after that import line:

```python
NiPoint3 = TGPoint3  # SDK App.py:189 binds NiPoint3; ours is the same 3-vector (no stock script calls it)
```

Append to `engine/compat/fx_api/NanoFX_ScriptActions.py`:

```python
def _keys(c, colours, alphas, sizes):
    for k in colours:
        c.AddColorKey(*k)
    for k in alphas:
        c.AddAlphaKey(*k)
    for k in sizes:
        c.AddSizeKey(*k)


def SetupController(sType, fSize, fLifeTime, fRed, fGreen, fBlue, fBrightness):
    """A particle controller for one of NanoFX's controller types. Key shapes
    follow NanoFX's documented types so callers' effects keep their timing
    and shape; textures come from the sprite library (spec §7)."""
    r, g, b = fRed / 255.0, fGreen / 255.0, fBlue / 255.0
    rnd = App.g_kSystemWrapper.GetRandomNumber
    if sType == "Plume":
        c = App.AnimTSParticleController_Create()
        s = fSize + rnd(20) * 0.01
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)], [(0.0, s), (1.0, s)])
    elif sType == "Blinker":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, fSize), (1.0, fSize)])
    elif sType == "StaticBlinker":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, r, g, b)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, fSize), (1.0, fSize)])
    elif sType == "Debris":
        life = fLifeTime
        c = App.DebrisParticleController_Create(
            life * (1.1295 - life * 0.00003) + rnd(10) * 0.001, life, 0.005)
        c.SetEmitLifeVariance(life / 4.0)
        k = (rnd(5) + 5) * fSize * 0.01
        _keys(c, [(0.0, 1.0, 1.0, 1.0), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 0.8 + rnd(3) * 0.1), (1.0, 0.0)],
              [(0.0, 0.01), (0.2, k), (0.7, k), (1.0, 0.01)])
    elif sType in ("ExpSparks", "DamageSparks"):
        if sType == "ExpSparks":
            life = 3.0 + rnd(100) * 0.01
            c = App.SparkParticleController_Create(life * 1.1345 + rnd(25) * 0.001, life, 0.005)
            c.SetTailLength(0.05 * (rnd(2) + 1))
        else:
            life = fLifeTime
            c = App.SparkParticleController_Create(life, 1.0, 0.5)
            c.SetTailLength(0.02)
        c.SetEmitLifeVariance(life / 4.0)
        _keys(c, [(0.0, 1.0, 1.0, 0.9), (0.6, 1.0, 0.8, 0.5), (1.0, 0.5, 0.2, 0.0)],
              [(0.0, 1.0), (0.6, 0.5), (1.0, 0.0)],
              [(0.0, 0.01), (0.2, 0.03 * fSize * 0.75), (0.8, 0.05 * fSize * 0.75), (1.0, 0.01)])
    elif sType == "Atmosphere":
        c = App.AnimTSParticleController_Create()
        _keys(c, [(0.0, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (1.0, 1.0)], [(0.0, 2.0 * fSize), (1.0, 2.0 * fSize)])
    else:   # "Normal", "Plasma", and anything unknown
        c = App.AnimTSParticleController_Create()
        s = fSize + rnd(10) * 0.01
        _keys(c, [(0.1, 1.0, 1.0, 1.0), (fBrightness, r, g, b), (1.0, 0.0, 0.0, 0.0)],
              [(0.0, 1.0), (0.7, 0.5), (1.0, 0.0)], [(0.0, s), (1.0, s)])
    return c


def _emit_source(pEmitFrom, pAttachTo):
    """The object to emit from. A stub (e.g. the result of
    App.TGModelUtils_CastNodeToAVObject, which stays a stub so stock effects
    are unchanged) or None falls back to the owner of pAttachTo when that is
    an object's GetNode() handle; a set effect root means world space."""
    from engine.appc.objects import _ObjectNodeRef
    if pEmitFrom is not None and not isinstance(pEmitFrom, App._Stub):
        return pEmitFrom
    if isinstance(pAttachTo, _ObjectNodeRef):
        return pAttachTo._owner()      # a weakref to the owning object
    return None


def CreateControllerFX(sFile, pEmitFrom, pAttachTo, fSize=1.0, vEmitPos=None,
                       vEmitDir=None, bInheritVel=0, bDetach=0, fFrequency=0.2,
                       fLifeTime=0.1, fEmitVel=None, fVariance=None, fDamping=None,
                       vGravity=None, iTiming=32, sType="Normal", fRed=255.0,
                       fGreen=255.0, fBlue=255.0, fBrightness=0.6):
    """NanoFX's one-call effect builder (spec 2026-10-16 §8.4). `iTiming` is
    in 1/15 s; `fBrightness` is the TIME of the tint colour key. `vGravity`
    and `bDetach` are accepted and ignored (spec §8.4)."""
    c = SetupController(sType, fSize, fLifeTime, fRed, fGreen, fBlue, fBrightness)
    emit_life = iTiming / 15.0
    if sType not in ("ExpSparks", "DamageSparks", "Debris"):
        c.SetEmitLife(emit_life)
        c.SetEmitFrequency(fFrequency)
        c.SetEffectLifeTime(emit_life + fLifeTime)
    c.CreateTarget(sFile)
    if fEmitVel:
        c.SetEmitVelocity(fEmitVel)
    if fVariance:
        c.SetAngleVariance(fVariance)
        c.SetEmitRadius(fSize / 4.0)
    if fDamping:
        c.SetDamping(fDamping)
    if sType in ("Normal", "Plasma", "Blinker", "StaticBlinker", "Atmosphere"):
        c.SetTargetAlphaBlendModes(0, 0 if sType != "Atmosphere" else 7)
    source = _emit_source(pEmitFrom, pAttachTo)
    if source is not None:
        c.SetEmitFromObject(source)
    c.SetEmitPositionAndDirection(vEmitPos if vEmitPos is not None else App.NiPoint3(0.0, 0.0, 0.0),
                                  vEmitDir if vEmitDir is not None else App.NiPoint3(0.0, 0.0, 0.0))
    c.SetInheritsVelocity(bInheritVel)
    c.SetDetachEmitObject(bDetach)
    c.AttachEffect(pAttachTo)
    return App.EffectAction_Create(c)
```

> `_emit_source` checks `isinstance(pAttachTo, _ObjectNodeRef)` before
> reading `_owner`. `_ObjectNodeRef` subclasses the chainable `_NodeStub`, and
> other stubs would answer any attribute truthily. `_owner` is the instance's
> `weakref.ref` to its object (`engine/appc/objects.py:46`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_fx_api_controller.py tests/unit/test_stock_particle_output_unchanged.py tests/unit/test_particles_sdk_unmodified.py -v`
Expected: all PASS. If `test_stub_emit_source_anchors_to_attach_owner` fails
because `_ObjectNodeRef` stores the owner under another attribute name, read
`engine/appc/objects.py:_ObjectNodeRef` (~L39). Adapt `_emit_source` to the
real accessor `particles._controller_set` uses (`node._owner()`).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/particles.py App.py engine/compat/fx_api/NanoFX_ScriptActions.py tests/unit/test_fx_api_controller.py
git commit -m "feat(compat): CreateControllerFX/SetupController; DebrisParticleController; App.NiPoint3

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Sprite prep tool

**Files:**
- Create: `tools/sprites/__init__.py` (empty), `tools/sprites/prep.py`
- Test: `tests/tools/test_sprite_prep.py`

**Interfaces:**
- Produces:
  - `prep.build(sprite_id: str, prep: dict, src_dir: Path) -> PIL.Image.Image` (RGBA sheet)
  - `prep.PrepError`
  - CLI: `uv run python tools/sprites/prep.py [--write] [id ...]`
- Prep fields (manifest `prep` object):
  - `grid: [cols, rows]`
  - `background`: one of `"black"`, `"black_solid"`, `"green_matte"`, `"alpha"`
  - `black_cut: int` (default 2)
  - `solid: [lo, hi]` (default `[4, 16]`)
  - `green: [lo, hi]` (default `[40, 160]`)
  - `shrink: int` (default 1)
  - `edge_fade: float`: fraction of the cell (default 0)
  - `origin_ramp: {"edge": "left" | "right" | "top" | "bottom", "width": float}`
  - `rotate`: `"cw"` | `"ccw"` | `null`
  - `keep_rows: [int]` (0-based), `keep_frames: [int]` (0-based, row-major)
  - `cell: int` (output cell px, default 256)

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_sprite_prep.py
"""tools/sprites/prep.py on synthetic sheets (spec 2026-10-16 §7.3)."""
import pytest
from PIL import Image, ImageDraw

from tools.sprites import prep


def _sheet(tmp_path, name, cols, rows, cell, bg, fg, draw_off=0):
    im = Image.new("RGB", (cols * cell, rows * cell), bg)
    d = ImageDraw.Draw(im)
    for r in range(rows):
        for c in range(cols):
            x, y = c * cell + cell // 4 + draw_off, r * cell + cell // 4
            d.ellipse((x, y, x + cell // 2, y + cell // 2), fill=fg)
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    im.save(tmp_path / name)
    return tmp_path


def test_black_mode_alpha_is_brightness_and_colour_restored(tmp_path):
    src = _sheet(tmp_path, "black.jpeg", 2, 1, 64, (0, 0, 0), (200, 100, 50))
    out = prep.build("x", {"grid": [2, 1], "background": "black", "cell": 32}, src)
    assert out.size == (64, 32) and out.mode == "RGBA"
    r, g, b, a = out.getpixel((16, 16))
    assert a >= 190 and r >= 250          # alpha ~ max channel; colour un-darkened
    assert out.getpixel((1, 1))[3] == 0   # black background -> transparent


def test_black_cut_removes_near_black_haze(tmp_path):
    src = _sheet(tmp_path, "black.jpeg", 1, 1, 64, (4, 4, 4), (255, 255, 255))
    out = prep.build("x", {"grid": [1, 1], "background": "black", "black_cut": 6, "cell": 64}, src)
    assert out.getpixel((2, 2))[3] == 0


def test_edge_fade_zeroes_cell_borders(tmp_path):
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [1, 1], "background": "black", "edge_fade": 0.1, "cell": 64}, tmp_path)
    assert out.getpixel((0, 32))[3] == 0 and out.getpixel((32, 32))[3] == 255


def test_origin_ramp_then_rotate_cw_puts_origin_on_top(tmp_path):
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [1, 1], "background": "black", "cell": 64,
                           "origin_ramp": {"edge": "left", "width": 0.25}, "rotate": "cw"}, tmp_path)
    assert out.getpixel((32, 0))[3] == 0        # ramped edge is now the top
    assert out.getpixel((32, 63))[3] == 255


def test_keep_rows_selects_rows(tmp_path):
    im = Image.new("RGB", (32, 48), (0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 16, 31, 31), fill=(255, 0, 0))     # row 1 red
    im.save(tmp_path / "black.jpeg")
    out = prep.build("x", {"grid": [2, 3], "background": "black", "cell": 16, "keep_rows": [1]}, tmp_path)
    assert out.size == (32, 16) and out.getpixel((8, 8))[0] == 255


def test_green_matte_takes_shape_from_green_colour_from_black(tmp_path):
    _sheet(tmp_path, "black.jpeg", 1, 1, 64, (0, 0, 0), (90, 90, 100))
    _sheet(tmp_path, "green.jpeg", 1, 1, 64, (0, 255, 0), (90, 90, 100))
    out = prep.build("x", {"grid": [1, 1], "background": "green_matte", "cell": 64}, tmp_path)
    r, g, b, a = out.getpixel((32, 32))
    assert a == 255 and (r, g, b) == pytest.approx((90, 90, 100), abs=6)   # dark metal stays opaque
    assert out.getpixel((2, 2))[3] == 0


def test_green_matte_refuses_misaligned_pair(tmp_path):
    _sheet(tmp_path, "black.jpeg", 1, 1, 64, (0, 0, 0), (90, 90, 100))
    _sheet(tmp_path, "green.jpeg", 1, 1, 64, (0, 255, 0), (90, 90, 100), draw_off=20)
    with pytest.raises(prep.PrepError, match="cell"):
        prep.build("x", {"grid": [1, 1], "background": "green_matte", "cell": 64}, tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_sprite_prep.py -v`
Expected: ERROR with `No module named 'tools.sprites'`.

- [ ] **Step 3: Implement**

```python
# tools/sprites/prep.py
"""Build native/assets/sprites/<id>.png from generated source sheets
(spec docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md §7.3).

    uv run python tools/sprites/prep.py            # preview: build all, report, write nothing
    uv run python tools/sprites/prep.py --write    # write <id>.png for every entry with "prep"
    uv run python tools/sprites/prep.py --write fire_jet

Sources live in native/assets/sprites/src/<id>/ (black.jpeg, plus green.jpeg
for green_matte). The output PNGs are GENERATED -- never hand-edit them;
tests/tools/test_sprite_drift.py fails on drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]


def sprites_dir() -> Path:
    return ROOT / "native" / "assets" / "sprites"


class PrepError(Exception):
    pass


def _cells(img, cols, rows):
    """Rows of cell images; fractional cell sizes allowed."""
    w, h = img.size
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            box = (round(c * w / cols), round(r * h / rows),
                   round((c + 1) * w / cols), round((r + 1) * h / rows))
            row.append(img.crop(box))
        out.append(row)
    return out


def _resize(cell, size):
    return cell.resize((size, size), Image.LANCZOS)


def _key_black(cell, cut):
    rgba = []
    for r, g, b in cell.convert("RGB").getdata():
        a = max(r, g, b)
        if a <= cut:
            rgba.append((0, 0, 0, 0))
        else:
            rgba.append((min(255, r * 255 // a), min(255, g * 255 // a),
                         min(255, b * 255 // a), a))
    out = Image.new("RGBA", cell.size)
    out.putdata(rgba)
    return out


def _key_black_solid(cell, lo, hi):
    rgb = cell.convert("RGB")
    alpha = Image.new("L", rgb.size)
    alpha.putdata([int(255 * min(1.0, max(0.0, (max(p) - lo) / float(hi - lo))))
                   for p in rgb.getdata()])
    alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.7))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _green_alpha(green, lo, hi):
    a = Image.new("L", green.size)
    a.putdata([int(255 * (1.0 - min(1.0, max(0.0, ((g - max(r, b)) - lo) / float(hi - lo)))))
               for r, g, b in green.convert("RGB").getdata()])
    return a


def _silhouette_outside(black, green, lo):
    """Fraction of the green-keyed object lying outside the black sheet's
    object (brightness > 16) dilated by 2 px."""
    obj = Image.new("L", black.size)
    obj.putdata([255 if max(p) > 16 else 0 for p in black.convert("RGB").getdata()])
    obj = obj.filter(ImageFilter.MaxFilter(5))
    g_obj = [(g - max(r, b)) < lo for r, g, b in green.convert("RGB").getdata()]
    total = sum(g_obj)
    if total == 0:
        return 0.0
    outside = sum(1 for inside, o in zip(g_obj, obj.getdata()) if inside and o == 0)
    return outside / float(total)


def _key_green_matte(black, green, lo, hi, shrink):
    alpha = _green_alpha(green, lo, hi)
    for _ in range(int(shrink)):
        alpha = alpha.filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.6))
    out = black.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def _scale_alpha(rgba, weight):
    """Multiply alpha by weight(x, y) in [0, 1]."""
    w, h = rgba.size
    px = rgba.load()
    for y in range(h):
        for x in range(w):
            k = weight(x, y)
            if k < 1.0:
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, int(a * k))
    return rgba


def _edge_fade(rgba, frac):
    w, h = rgba.size
    span = max(1.0, frac * min(w, h))
    return _scale_alpha(rgba, lambda x, y: min(1.0, min(x, y, w - 1 - x, h - 1 - y) / span))


def _origin_ramp(rgba, edge, frac):
    w, h = rgba.size
    span = max(1.0, frac * (w if edge in ("left", "right") else h))
    dist = {"left": lambda x, y: x, "right": lambda x, y: w - 1 - x,
            "top": lambda x, y: y, "bottom": lambda x, y: h - 1 - y}[edge]
    return _scale_alpha(rgba, lambda x, y: min(1.0, dist(x, y) / span))


def build(sprite_id: str, prep: dict, src_dir: Path) -> Image.Image:
    cols, rows = prep["grid"]
    cell = int(prep.get("cell", 256))
    mode = prep.get("background", "black")
    black_img = Image.open(src_dir / "black.jpeg").convert("RGB") \
        if (src_dir / "black.jpeg").exists() else Image.open(src_dir / "alpha.png").convert("RGBA")
    black_cells = _cells(black_img, cols, rows)
    green_cells = None
    if mode == "green_matte":
        green_cells = _cells(Image.open(src_dir / "green.jpeg").convert("RGB"), cols, rows)

    keep_rows = prep.get("keep_rows", list(range(rows)))
    frames = [(r, c) for r in keep_rows for c in range(cols)]
    if "keep_frames" in prep:
        frames = [frames[i] for i in prep["keep_frames"]]

    bad = []
    out_cells = []
    for r, c in frames:
        blk = _resize(black_cells[r][c], cell)
        if mode == "black":
            rgba = _key_black(blk, int(prep.get("black_cut", 2)))
        elif mode == "black_solid":
            lo, hi = prep.get("solid", [4, 16])
            rgba = _key_black_solid(blk, lo, hi)
        elif mode == "green_matte":
            grn = _resize(green_cells[r][c], cell)
            lo, hi = prep.get("green", [40, 160])
            if _silhouette_outside(blk, grn, lo) > 0.01:
                bad.append(f"row {r} col {c}")
                continue
            rgba = _key_green_matte(blk, grn, lo, hi, prep.get("shrink", 1))
        elif mode == "alpha":
            rgba = blk.convert("RGBA")
        else:
            raise PrepError(f"{sprite_id}: unknown background mode {mode!r}")
        if prep.get("edge_fade"):
            rgba = _edge_fade(rgba, float(prep["edge_fade"]))
        if prep.get("origin_ramp"):
            ramp = prep["origin_ramp"]
            rgba = _origin_ramp(rgba, ramp["edge"], float(ramp["width"]))
        if prep.get("rotate") == "cw":
            rgba = rgba.transpose(Image.Transpose.ROTATE_270)
        elif prep.get("rotate") == "ccw":
            rgba = rgba.transpose(Image.Transpose.ROTATE_90)
        out_cells.append(rgba)
    if bad:
        raise PrepError(f"{sprite_id}: green/black sheets disagree in cell(s): {', '.join(bad)}")

    out_rows = len(frames) // cols if len(frames) % cols == 0 else len(frames) // cols + 1
    sheet = Image.new("RGBA", (cols * cell, out_rows * cell), (0, 0, 0, 0))
    for i, rgba in enumerate(out_cells):
        sheet.paste(rgba, ((i % cols) * cell, (i // cols) * cell))
    return sheet


def _manifest() -> dict:
    return json.loads((sprites_dir() / "manifest.json").read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args(argv)
    entries = _manifest()["sprites"]
    ids = args.ids or [k for k, v in entries.items() if isinstance(v, dict) and "prep" in v]
    status = 0
    for sid in ids:
        entry = entries.get(sid) or {}
        if "prep" not in entry:
            print(f"{sid}: no prep section", file=sys.stderr)
            status = 1
            continue
        try:
            sheet = build(sid, entry["prep"], sprites_dir() / "src" / sid)
        except (PrepError, OSError) as e:
            print(f"{sid}: FAILED -- {e}", file=sys.stderr)
            status = 1
            continue
        print(f"{sid}: {sheet.size[0]}x{sheet.size[1]}")
        if args.write:
            sheet.save(sprites_dir() / entry["file"])
    return status


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/tools/test_sprite_prep.py -v`
Expected: all PASS. If the JPEG round-trip shifts a pixel threshold by a few
levels, widen only that test's tolerance; don't change the algorithm.

- [ ] **Step 5: Commit**

```bash
git add tools/sprites/__init__.py tools/sprites/prep.py tests/tools/test_sprite_prep.py
git commit -m "feat(tools): sprite prep tool — black/black_solid/green_matte keying, fades, packing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Import the generated art, generate PNGs, drift test

**Files:**
- Create:
  - `native/assets/sprites/src/fireball/black.jpeg`
  - `native/assets/sprites/src/fire_jet/black.jpeg`
  - `native/assets/sprites/src/glint_burst/black.jpeg`
  - `native/assets/sprites/src/shock_sphere/black.jpeg`
  - `native/assets/sprites/src/debris_chunk/black.jpeg`
  - `native/assets/sprites/src/debris_chunk/green.jpeg`
- Create (generated): `native/assets/sprites/{fireball,fire_jet,glint_burst,shock_sphere,debris_chunk}.png`
- Modify: `native/assets/sprites/manifest.json` (`prep` sections)
- Test: `tests/tools/test_sprite_drift.py`

- [ ] **Step 1: Copy the sources**

```bash
D=~/Downloads/sprites
S=native/assets/sprites/src
mkdir -p $S/fireball $S/fire_jet $S/glint_burst $S/shock_sphere $S/debris_chunk
cp "$D/fireball.jpeg" $S/fireball/black.jpeg
cp "$D/fire_jet.jpeg" $S/fire_jet/black.jpeg
cp "$D/glint_burst.jpeg" $S/glint_burst/black.jpeg
cp "$D/shock_sphere.jpeg" $S/shock_sphere/black.jpeg
cp "$D/debris_chunk.jpeg" $S/debris_chunk/black.jpeg
cp "$D/debris_chunk_green.jpeg" $S/debris_chunk/green.jpeg
ls -la $S/*/
```

Expected: six files, sizes about 1.3–2.5 MB each.

- [ ] **Step 2: Add the `prep` sections**

In `manifest.json`, add a `"prep"` object to each of these five entries. Leave
their other fields as they are:

```json
"fireball":     {..., "prep": {"grid": [8, 4], "background": "black", "black_cut": 6, "edge_fade": 0.06, "cell": 256}},
"fire_jet":     {..., "prep": {"grid": [8, 4], "background": "black", "black_cut": 6, "origin_ramp": {"edge": "left", "width": 0.12}, "rotate": "cw", "cell": 256}},
"glint_burst":  {..., "prep": {"grid": [4, 4], "background": "black", "black_cut": 4, "edge_fade": 0.08, "cell": 256}},
"shock_sphere": {..., "prep": {"grid": [8, 4], "background": "black", "black_cut": 12, "edge_fade": 0.08, "cell": 256}},
"debris_chunk": {..., "prep": {"grid": [6, 6], "background": "green_matte", "green": [40, 160], "shrink": 1, "keep_rows": [0, 1, 3, 5], "cell": 128}}
```

(Write them as complete JSON objects. The `...` stands for the entry's existing
fields from Task 10.)

> `fire_jet` uses `rotate: "cw"` because the source jet points right with its
> origin on the left. After rotation the origin is on the cell's TOP edge.
> Images upload top row first, so the cell top maps to the quad's bottom
> (`a_corner.y = -1`). With `pivot [0, -1]`, that bottom sits on the emit
> point, and the flame extends along `+emit_dir`. Confirm by eye in the live
> check.

- [ ] **Step 3: Preview, then write**

Run: `uv run python tools/sprites/prep.py`
Expected:
- `fireball: 2048x1024`
- `fire_jet: 2048x1024`
- `glint_burst: 1024x1024`
- `shock_sphere: 2048x1024`
- `debris_chunk: 768x512`
- exit 0

If debris reports `green/black sheets disagree`, STOP and report the cells. The
spec's guard is doing its job; do not loosen it.

Run: `uv run python tools/sprites/prep.py --write`
Expected: the five PNGs exist under `native/assets/sprites/`.

- [ ] **Step 4: Write the drift test**

```python
# tests/tools/test_sprite_drift.py
"""Committed sprite PNGs match a fresh prep run (spec 2026-10-16 §7.3).
Never hand-edit an output; regenerate with tools/sprites/prep.py --write."""
import json

import pytest
from PIL import Image, ImageChops

from tools.sprites import prep

ENTRIES = {k: v for k, v in json.loads((prep.sprites_dir() / "manifest.json").read_text())["sprites"].items()
           if isinstance(v, dict) and "prep" in v}


@pytest.mark.parametrize("sprite_id", sorted(ENTRIES))
def test_committed_png_matches_prep(sprite_id):
    entry = ENTRIES[sprite_id]
    fresh = prep.build(sprite_id, entry["prep"], prep.sprites_dir() / "src" / sprite_id)
    committed = Image.open(prep.sprites_dir() / entry["file"]).convert("RGBA")
    assert committed.size == fresh.size
    diff = ImageChops.difference(committed, fresh).getdata()
    off = sum(1 for p in diff if max(p) > 4)
    assert off <= 0.005 * committed.size[0] * committed.size[1], f"{off} pixels drifted"


def test_every_prep_entry_has_its_sources():
    for sid, entry in ENTRIES.items():
        src = prep.sprites_dir() / "src" / sid
        assert (src / "black.jpeg").is_file(), sid
        if entry["prep"].get("background") == "green_matte":
            assert (src / "green.jpeg").is_file(), sid
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/tools/test_sprite_drift.py tests/unit/test_sprite_library.py -v`
Expected: all PASS. `test_create_target_applies_library_fields` now sees
`_size_scale == 0.6` for `glint_burst`.

- [ ] **Step 6: Contact sheet for Mark's review (not committed)**

Write the script to `/private/tmp/claude-501/sprite_review.py` (or the
session scratchpad) and run it with
`uv run python /private/tmp/claude-501/sprite_review.py`:

```python
import json
from pathlib import Path
from PIL import Image

root = Path("native/assets/sprites")
m = json.loads((root / "manifest.json").read_text())["sprites"]
tiles = []
for sid, e in m.items():
    if "prep" in e:
        im = Image.open(root / e["file"])
        im.thumbnail((1024, 512))
        bg = Image.new("RGBA", im.size, (40, 52, 80, 255))
        tiles.append(Image.alpha_composite(bg, im.convert("RGBA")))
W = max(t.size[0] for t in tiles)
H = sum(t.size[1] + 8 for t in tiles)
sheet = Image.new("RGBA", (W, H), (10, 10, 12, 255))
y = 0
for t in tiles:
    sheet.paste(t, (0, y))
    y += t.size[1] + 8
sheet.save("/private/tmp/claude-501/sprite_review.png")
```

Then show `/private/tmp/claude-501/sprite_review.png` to Mark. Per the
"UI: look first" rule, wait for his OK before committing. If he asks for prep
tweaks, change only the manifest `prep` values, re-run `--write`, and
re-show.

- [ ] **Step 7: Commit**

```bash
git add native/assets/sprites/manifest.json native/assets/sprites/src/fireball/black.jpeg native/assets/sprites/src/fire_jet/black.jpeg native/assets/sprites/src/glint_burst/black.jpeg native/assets/sprites/src/shock_sphere/black.jpeg native/assets/sprites/src/debris_chunk/black.jpeg native/assets/sprites/src/debris_chunk/green.jpeg native/assets/sprites/fireball.png native/assets/sprites/fire_jet.png native/assets/sprites/glint_burst.png native/assets/sprites/shock_sphere.png native/assets/sprites/debris_chunk.png tests/tools/test_sprite_drift.py
git commit -m "feat(assets): generated sprite library art + drift test

Sources are Gemini-generated sheets from briefs written against each
effect's meaning; outputs are tools/sprites/prep.py products.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Docs, fixture mod, full gate

**Files:**
- Modify: `CLAUDE.md` ("Key reference material" table: add one row, before the
  "Game-unit conversion" row)
- Create (NOT committed): `mods/LegacyFxFixture/scripts/Custom/Autoload/LegacyFxFixture.py`

- [ ] **Step 1: CLAUDE.md row**

Add this row to the "Key reference material" table:

```markdown
| Legacy FX API surface — NanoFX's API without NanoFX | `engine/mod_policy.py`, `engine/compat/{claimed.py,fx_api/}`, `engine/sprites.py`, `native/assets/sprites/`, `tools/sprites/prep.py`, `docs/superpowers/specs/2026-10-16-legacy-fx-api-surface-design.md` | Mods calling `Custom.NanoFXv2.*` get Dauntless's implementation, served by a claimed-namespace rule in BOTH `_SDKFinder`s (ours always wins). A real NanoFX install is **blocked** (standalone) or its files **skipped** (bundled); Foundation's bundled infrastructure files are refused (`LoadTacticalSounds`/`QuickBattle`/`mainmenu` only when they import Foundation) — see `describe()` and the Mods screen. NanoFX texture paths are NAMES resolved by the sprite library (`legacy_aliases.json` → `manifest.json`: `sprite`/`native`/`none`, playback `life_columns`/`life_sequence`/`loop`, `pivot`, `orient: emit_dir`). ⚠️ Production VFX are byte-identical — `tests/unit/test_stock_particle_output_unchanged.py` guards it; stock `App` controller methods are NOT changed. ⚠️ Output PNGs are GENERATED by `tools/sprites/prep.py` from `native/assets/sprites/src/` — never hand-edit (drift test). ⚠️ §6.3 "re-enabling global glow clears per-ship disables" is an ASSUMPTION. Next: apply the library to Dauntless's own stock effects. |
```

- [ ] **Step 2: Create the fixture mod (uncommitted, gitignored `mods/`)**

```python
# mods/LegacyFxFixture/scripts/Custom/Autoload/LegacyFxFixture.py
"""Developer-only live check for the legacy FX API surface (spec 2026-10-16
§9). Pause menu (--developer) -> "Legacy FX fixture". NOT committed."""
import App
from engine import dev_mode

N = "scripts/Custom/NanoFXv2/"
PATHS = [
    N + "ExplosionFX/Gfx/Explosions/Exp_Nano3.tga",       # fireball
    N + "ExplosionFX/Gfx/Explosions/Exp_ExpDeb.tga",      # fireball_hot
    N + "ExplosionFX/Gfx/Explosions/Exp_Flare.tga",       # fire_jet
    N + "ExplosionFX/Gfx/ExpFlash/ExpFlash1.tga",         # glint_burst
    N + "SpecialFX/Gfx/Blinker/Blinker.tga",              # glint
    N + "ExplosionFX/Gfx/Particles/Sparks.tga",           # spark
    N + "SpecialFX/Gfx/Plasma/Plasma.tga",                # plasma_puff
    N + "ExplosionFX/Gfx/NovaSphere/Nova_Sphere3a.tga",   # shock_sphere
    N + "ExplosionFX/Gfx/NovaRing/Nova_Ring2a.tga",       # shock_ring (native)
    N + "SpecialFX/Gfx/Blinker/Blank.tga",                # none
]


def _run(*_args):
    import Custom.NanoFXv2.NanoFX_Lib as L
    import Custom.NanoFXv2.NanoFX_ScriptActions as A
    player = App.Game_GetCurrentPlayer()
    if player is None:
        return
    target = App.ShipClass_Cast(player.GetTarget()) or player
    radius = target.GetRadius() or 1.0
    L.CreateFlickerSeq(target, 3.0).Play()
    L.CreateRotationSeq(target, 300).Play()
    for i, path in enumerate(PATHS):
        y = radius * (1.2 + 0.6 * i)
        A.CreateControllerFX(path, App.TGModelUtils_CastNodeToAVObject(target.GetNode()),
                             target.GetNode(), radius * 0.4,
                             App.NiPoint3(0.0, y, 0.0), App.NiPoint3(0.0, 0.0, 1.0),
                             iTiming=45, fRed=55.0, fGreen=120.0, fBlue=255.0,
                             fBrightness=0.5).Play()
    A.CreateControllerFX(N + "ExplosionFX/Gfx/Debris/nano_debris1a.tga", None,
                         target.GetNode(), radius, App.NiPoint3(0.0, 0.0, radius),
                         App.NiPoint3(0.0, 0.0, 1.0), bInheritVel=1, fEmitVel=1.5,
                         fLifeTime=10.0, fVariance=150.0, fDamping=0.1, sType="Debris").Play()


dev_mode.register_dev_pause_menu_entry("Legacy FX fixture", _run)
```

Check that it's ignored: `git status --short mods/` prints nothing.

> **Atmosphere check (manual, optional).** `CreateAtmosphereFX` needs a planet
> with an uncatalogued NIF. If no mod system provides one, confirm via the
> unit tests and note "atmosphere not live-checked" in the hand-off.

- [ ] **Step 3: Full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any new failure or unbaselined skip is a regression from this
branch: fix it, never baseline it.

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs(claude): legacy FX API surface reference row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand-off for live verification (Mark, main checkout or worktree per his preference)**

Report these live checks, named unambiguously:

1. `--developer` → pause → **Legacy FX fixture**, with a target selected. Each
   sprite should appear stacked above the target. The jet should vent outward,
   the ring should be the procedural shockwave tinted blue, `Blank` should show
   nothing, debris should tumble, and the target should flicker and spin.
2. **E4M5**: the Kessok ships go dark when the mission calls
   `DisableGlowAlphaMaps`.
3. **Real NanoFX** in `mods/`: the boot report says it's blocked; tactical
   sounds and Quick Battle still work; `--mods` shows the blocked notice.
4. **By eye**: `nova_flare → none`, each sprite's `scale` / `pivot`, debris
   `fps`.

Then propose the agreed follow-up: apply the library to Dauntless's stock
effects (memory `project_sprite_library_stock_vfx_followup`).
