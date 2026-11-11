# Stock scripts from the retail install: no SDK at runtime

Status: design, approved for planning pending review. Branch `feat/no-sdk-runtime`
(worktree `.claude/worktrees/no-sdk-runtime`).

## 1. Intent

A player needs only a retail copy of Bridge Commander. The README stops asking
them to download the BC SDK 1.1, and the first-run "Select Bridge Commander
Install" screen asks for one folder, not two.

This is possible because retail BC ships every stock script as Python 1.5
bytecode in its own `scripts/` folder, and the bytecode lifter
(`engine/py15/`, spec `2026-11-11-legacy-script-parsing-design.md`) already
lifts all of them to the AST the SDK source parses to. The stock oracle
(`tests/unit/test_py15_stock_oracle.py`) proves it: 1,201 of 1,201 retail
`.pyc`, 0 mismatches under its closed normalisation. Original BC itself never
read the SDK; it ran these same files.

Measured on Mark's install (2026-11-11):

| | |
|---|---|
| SDK `Build/scripts` modules | 1,234 |
| retail `scripts/` `.pyc` | 1,201, every one also in the SDK |
| SDK-only modules | 33: `Custom/Tutorial/**` (the SDK's sample mission, 21), the French/German/Italian/Spanish/UK `*Config` + `Default*KeyboardBinding` (10), and two non-BC files that are not stock (`LoadDamageHitSounds.py`, whose real copy is the project-root shim, and `ships/Hardpoints/galaxy_dauntless_mods.py`, a hand-placed validation copy the glow bake tools exclude) |
| SDK `Build/Data` | only the tutorial's TGL tables; every other TGL is under the game's `data/TGL` |
| lift all 1,201 `.pyc` | 4.2 s, vs 4.8 s to read + fix + parse the SDK source the loaders use today |

## 2. Decisions (Mark's)

1. **The game never reads the SDK. Full stop.** Every stock script comes from
   lifting the retail `.pyc`, on every machine, developers' included. An SDK
   path in `settings.json` `[paths].sdk`, `DAUNTLESS_SDK_DIR` or `--sdk-dir` is
   ignored by the game. No fallback to SDK source, no "SDK wins when present".
2. **The Activision notice splash stays exactly as it is.** The engine was
   built from SDK knowledge, and Mark wants the SDK licence's cover.
3. **The README drops the SDK requirement** and the first-run screen asks for
   the game folder only.
4. **Developers still use the SDK**, found by this chain (today's minus the
   game flag): `DAUNTLESS_SDK_DIR`, then `settings.json` `[paths].sdk`, then
   an in-project `sdk/`. One accessor, used only by tests and `tools/`. A guard
   test fails if the shipped game calls it.
5. **The SDK is required to work on the codebase**, as a game install is.
   Tests may require it; they do not need a no-SDK skip path. Where the
   test machinery already treats BC content as absent (the content-free
   GitHub CI), SDK-backed tests follow the same existing mechanism as
   game-content tests; no new SDK-specific skip logic is built.
6. **Dirty installs: known list, warn.** Only modules on a committed list of
   the 1,201 stock relative paths load from the game's `scripts/` folder. Stray
   `.py` files and unknown `.pyc` there are ignored: mods go through the Mods
   system, never through the install. Each listed path also carries a content
   hash. A stock `.pyc` whose hash does not match still loads, but logs ONE
   warning naming the file, so a modded install shows up in a bug report.
   Other retail versions (another patch level, a non-English or digital
   release) therefore still run.
7. **An unliftable stock `.pyc` stops boot** with a message naming the file.
   The game never runs with a stock module silently missing. (How and when:
   §4.3, the builder's-check calls.)
8. **The SDK's sample tutorial (`Custom/Tutorial`) stays a TEST fixture.**
   17 test files run its missions (M1Basic, M2Objects, M3Gameflow) as scenes,
   and retail BC does not ship them. The TEST loader alone may load that
   sample, and its TGL, from the SDK through the dev chain (decision 4; the
   SDK is a development requirement, decision 5). Every real stock module still comes lifted from the
   install, in tests too. The game never sees the sample: the dev mission
   picker loses its "Tutorial" family.

## 3. Goals, non-goals, anti-goals

**Goals**
- Boot, campaign, Quick Battle and every mod path work with no SDK anywhere on
  the machine.
- Tests run stock scripts the same way the game does (lifted), so the suite
  tests what players run.
- The "game never reads the SDK" rule is enforced by a guard test, not by
  memory.

**Non-goals**
- Supporting the SDK's tutorial sample mission in the GAME (tests keep it,
  decision 8), or the regional config files when they are absent from the
  install. A regional retail install is expected to carry its own regional
  `.pyc`; that is unverified (§8).
- Changing how mods load. Mod `.py` / `.pyc` overrides, the claimed namespaces
  and the mod policy rules keep their current precedence over stock.
- Removing the SDK from development. It stays the readable reference and the
  oracle's input.

**Anti-goals (a failure even if it works)**
- The game reading the SDK in any path, including a dev-only one shipped in
  the package.
- Lifted stock text, or anything derived from it, written to disk anywhere
  (repo, cache, logs beyond a module name and path). The tree goes straight to
  `compile()`, as for mods today.
- An old-style modded install's changed or extra scripts loading silently as
  stock.
- A stock module that fails to lift being skipped instead of stopping boot.

## 4. Design

### 4.1 Where stock scripts come from

A new accessor names the stock script root: the game root's `scripts/`
folder, resolved at use like every other path (`engine/paths.py`; never
captured at import). It replaces `paths.sdk_scripts()` for every runtime
caller. `sdk_scripts()`, `sdk_root()`, `sdk_data()` and `sdk_scripts_in()`
leave `engine/paths.py`'s runtime surface (see §4.6 for where the dev
accessor lives).

The **stock manifest** is a committed, GENERATED file listing each retail
module path (relative, canonical spelling) with the **set of known content
hashes** for it. Today that set holds one hash per path, from Mark's GOG
install; a second verified retail build is added by appending its hashes, not
by replacing the list. It holds names and hashes only, never BC content.
Modules the project root shadows (`App`, `LoadBridge`, and any later root
shim) are left out: they never load from the install, and leaving them out
keeps an instrumented install (`tools/setup.py` replaces `scripts/App.pyc`)
from looking modded. A tool generates the manifest from a configured clean
install; never hand-edit. Hash algorithm, file format and location: builder's
call (the mesh fixes' FNV-1a 64 is the existing precedent).

**Drift test** (skips without a game folder): if every listed file in the
configured install hashes to a known value, regenerating from it must
reproduce the committed manifest exactly; that catches a hand edit. An
install with unknown hashes (a contributor's different retail build) skips
with the files named instead of failing, so a different build never breaks
someone's suite.

### 4.1a Boot integrity check (calls made after the builder check)

Stock modules import lazily (most at mission load or warp), so decision 7 is
enforced by a check at boot, right after the game root resolves and before
the SDK finder is installed:

- Hash every manifest file in the install: about 60 ms for all 1,201
  (measured 2026-11-11, warm cache).
- **A listed file missing** stops boot, naming it (same treatment as an
  unliftable file: its first import would otherwise fail mid-game).
- **A hash outside the known set** logs decision 6's one warning, then the
  file is lifted once, now, to prove it lifts. A clean known install lifts
  nothing at boot. A different build pays up to ~4 s on launch; the builder
  may cache a "this hash lifts" verdict per hash in `paths.cache_dir()` (a
  verdict only, never lifted text) to pay that once.
- **A stop is shown on the first-run "Select Bridge Commander Install"
  screen** (`engine/ui/first_run_panel.py`), with the problem and the file
  named, because it is an install problem and that screen already lets the
  player pick another folder. The same line goes to the log. Headless/tests
  raise a clear error instead.
- Every listed file is proven at boot, so a stock import cannot fail later
  for these reasons.

### 4.2 The loaders

Both `_SDKFinder` twins (`tools/mission_harness.py` and `tests/conftest.py`;
`tests/unit/test_sdk_finder_twins_stay_in_sync.py` holds them together) change
in lockstep:

- **Stock resolution is by manifest, not by disk walk.** A stock module exists
  iff its path is in the manifest; it is loaded from the game's `scripts/`
  folder, matched case-insensitively. Packages are directories with an
  `__init__.pyc` in the manifest. The implicit-relative-import fallback (bare
  `import X` found by a unique match anywhere) searches the manifest, not an
  `rglob` over `.py`.
- **`_module_tree` lifts stock `.pyc`** through the same `engine.py15` path as
  mod `.pyc` and then the same transform chain. The "Only `_mod_override_spec`
  ever hands this a `.pyc`; stock always loads from SDK source" rule is
  retired, along with "Mod files only" in CLAUDE.md's Python 1.5 row and the
  `engine/py15` docstrings.
- **Hash check** happens where the bytes are already read for the lift: on a
  mismatch, one `[sdk-loader]` line per file per process, naming the file and
  saying it differs from retail (the install may be modded), then load it.
- **Unliftable stock** raises a dedicated error naming the file (decision 7);
  §4.1a makes sure that happens at boot, not mid-game. Mod `.pyc` keep their
  existing one-line refusal and fallback behaviour.
- **Test loader only** (`tests/conftest.py`): modules under `Custom/Tutorial`
  that the manifest does not list load from SDK source via the dev accessor
  (decision 8). This is the twins' one sanctioned difference;
  `test_sdk_finder_twins_stay_in_sync.py` names it explicitly rather than
  being loosened.
- **Mod precedence is unchanged**: claimed namespaces, then mod overrides,
  then stock. Sibling lookups for implicit relative imports consider `.pyc`
  stock siblings.
- `engine/sdk_code_cache.py` keeps working unchanged in principle: it keys on
  the file's stamp; the file is now a `.pyc`.
- Module `__file__` / `co_filename` become the `.pyc` path. Tracebacks show
  that path with line numbers from the bytecode's `SET_LINENO` table, which
  match the SDK source a developer has.

### 4.3 Runtime callers of the old SDK path

Each moves to the stock root or the manifest. Known list (builder re-greps):

| Caller | Today | Becomes |
|---|---|---|
| `engine/appc/ai_native.py` `_stock_file` | SDK `AI/Preprocessors.py` path compared to `co_filename` | the stock `AI/Preprocessors.pyc` path. ⚠️ The native-AI A/B (`tests/integration/test_native_ai_ab.py`) and the walker differentials must stay green: the stock-identity gate is what makes stock preprocessors run native |
| `engine/missions/discovery.py` + `host_loop._get_mission_registry` | finds `<dir>/<dir>.py` and greps source for `def Initialize(pMission)` | finds `<dir>/<dir>.pyc` in the manifest and detects a module-level `Initialize` whose first argument is `pMission` from the bytecode (lift, or read the code object directly; builder's call) |
| `tools/mission_harness.discover_missions` | same grep over `.py` | same as above |
| `engine/bridge_selection._stock_ship_stems` | lists SDK `ships/*.py` | manifest `ships/*` |
| `engine/mods.py` `_TARGET_FOR["scripts"]`, `install`, classify | maps a mod's `Scripts/` onto the SDK root to tell override from new | onto the stock root/manifest; the kind label `"sdk"` may stay or be renamed (builder's call; it is a label, not a path) |
| `engine/appc/localization.py` | SDK `Build/Data/TGL` candidate | dropped |
| `engine/missions/name_resolver.py` `TGL_ROOTS` | SDK TGL first | game `data/TGL` only |
| `engine/dev_character_viewscreen.py` | reads SDK `.py` text (latin-1) to find characters | from lifted stock or the stock root's code (dev feature, still shipped: must not need the SDK) |
| `engine/dev_missions/ship_preview.py` | prints SDK paths | stock root paths |
| `engine/host_loop.py` (boot hand-off, setup_sdk, `_paths.sdk_scripts_in(resolution.sdk)`) | | stock root |

### 4.4 Path resolution and the first-run screen

- `Resolution` resolves the game root only; `complete` means the game is
  valid. `CLI_FLAGS`, `ENV_VARS`, `_PROJECT_DIR`, `_VALIDATORS`, the picker's
  "picked" source and the "swapped root" hint lose their SDK entries.
- Game-folder validation additionally requires the scripts folder (a marker
  such as `scripts/MissionLib.pyc`, matched case-insensitively). An install
  without its scripts can no longer boot.
- `--sdk-dir` passed to the game: accepted and ignored with one log line, so
  an old shortcut does not stop boot (builder may choose to drop the flag
  outright if argument parsing makes that cleaner; say which).
- `settings.json` `[paths].sdk` is left in the file untouched (the dev chain
  reads it) and never written by the game.
- First-run panel (`engine/ui/first_run_panel.py`, its JS/CSS), the native
  folder-picker message (`native/src/platform/folder_picker.cc`) and the
  host's `--sdk-dir` comments (`native/src/host/host_main.cc`) drop the SDK.
- `scripts/package.py`: the env-scrub list may keep `DAUNTLESS_SDK_DIR`
  (harmless); its comments about the SDK finder are updated.

### 4.5 Player docs

`docs/packaging/README.txt`: the requirements list, GETTING STARTED steps and
the first-run description drop the SDK (renumber the steps). The "Use a clean
copy" section now also covers scripts and mentions the warning a changed
stock script logs. The licence paragraph that names the SDK stays. The boot
notice's pinned wording is untouched.

### 4.6 Developers: the dev SDK accessor

- Lives outside `engine/` (e.g. `tools/dev_sdk.py`; builder's call on the
  name): returns the SDK root via decision 4's chain, and raises a clear
  error naming the chain ("no BC SDK configured: set DAUNTLESS_SDK_DIR or
  settings.json [paths].sdk; the SDK is required for development") when none
  resolves.
- **Guard test**: nothing under `engine/`, no file the package ships
  (`scripts/package.py`'s list, which includes `tools/mission_harness.py`),
  and neither SDK finder twin's runtime path imports or calls it. Parse,
  don't grep (the `test_path_indirection.py` precedent).
- `tests/unit/test_path_indirection.py` keeps its "never spell `sdk` as a path
  segment" rule; the dev accessor is the one place that knows the SDK layout.

### 4.7 Tests and tools

About 45 test and tool files touch the SDK path today (§9 lists them). Each is
sorted into:

- **About stock scripts** (most): switch to the stock root / manifest /
  lifted modules. E.g. mission discovery, registry, hardpoint parser, officer
  placement, ship catalog stock content, set-course bake, golden A/B side.
- **Using the SDK's sample tutorial** (decision 8; 17 files, e.g.
  `test_gameloop_harness.py`, `test_frame_rate_independence.py`,
  `tests/integration/tutorial/`, `tests/missions/conftest.py`'s tutorial TGL,
  `test_host_loop_unit.py` pinning `host_loop.SHIP_GATE_MISSION`): unchanged;
  the test loader serves the sample from the SDK. `engine/missions/discovery.py`
  keeps "Custom/Tutorial" in its family table (harmless when absent);
  `SHIP_GATE_MISSION` stays, as tests are its only callers (builder checks).
- **About the SDK itself**: keep the SDK through the dev accessor. At least the stock oracle (`test_py15_stock_oracle.py`), the
  constants generator (`tools/gen_app_constants.py` reads SDK `App.py`), and
  `tools/setup.py` (instrumentation installs into the real game from SDK
  `App.py`).
- **About path resolution** (`test_paths_*`, `test_first_run_panel.py`,
  `test_host_loop_first_run.py`, `test_packaged_readonly_e2e.py`,
  `test_mods_*`, `write_audit.py`): rewritten for game-only resolution.

New tests:
- **No-SDK boot**: with the SDK made unreachable (no env var, no settings key,
  no in-project folder: the test's own temp settings), setup_sdk + a few
  missions (an E1 mission, Quick Battle, one with a mod `.pyc` override) load
  and tick headless. This keeps the lifted route honest on developer machines
  that all have an SDK.
- Manifest: listed-only loading (a stray `.py` and an unknown `.pyc` in a fake
  install tree are ignored), hash-mismatch warns once and loads, unliftable
  stock stops with the file named.
- The guard test (§4.6) and the manifest drift test.

Per CLAUDE.md: focused test files plus the cheap tree guards only during
development; no gate and no whole-suite runs on this branch.

### 4.8 Expected, accepted differences

- Hardpoint and other floats move at the 12th significant digit (retail
  bytecode holds `%.12g`; spec 2026-11-11 §2.1). The first base-vs-HEAD A/B
  across this branch shows that drift once; it is toward what BC ran. Any
  committed bit-exact expectation that moves is re-recorded with that reason
  in the commit.
- `TimingGraph` comes from the retail build, which was compiled from a
  different source than the SDK ships (oracle `_SOURCE_DIFFERS`).
- `string` is in the retail list; the stdlib-shadow pre-import in `setup_sdk`
  stays.

### 4.9 Docs to update

CLAUDE.md (the BC content paths row and section, the Python 1.5 row's "Mod
files only", Setup), `engine/paths.py` module docstring, the path resolution
and first-run picker specs (a superseded note pointing here), and the
`engine/py15` docstrings.

## 5. Constraints

- Resolve paths at use; never spell `game`/`sdk` as a path segment outside
  the allowed places (`test_path_indirection.py`).
- Python 1.5 compat transforms unchanged; lifted and parsed trees take the
  identical pipeline.
- Never write lifted text or BC-derived values to disk; the manifest holds
  only relative paths and hashes.
- The shared-checkout git rules in CLAUDE.md (no destructive git, explicit
  pathspecs). Work stays in the worktree.
- Native AI stock-identity, native combat and every bit-exact differential
  stay green with their oracles unchanged except for §4.8's float drift.

## 6. Left to the builder

Names of the stock-root accessor, the manifest file and its format, the hash
function, the dev accessor module; whether mission detection lifts or reads
code objects; whether `--sdk-dir` is ignored or removed; whether the mods kind
label is renamed; how to stage the work into plan tasks.

## 7. Verification

- Focused tests + tree guards green.
- A headless no-SDK boot (the new test) and, before calling it done, Mark's
  live run in the worktree with the SDK path removed from that worktree's
  `settings.json`: first-run screen asks for one folder, E1M1 intro, a Quick
  Battle, the LC Intrepid mod's `.pyc` torpedoes.

## 8. Unknowns

- Whether other retail builds (other patch levels, non-English, digital
  re-releases) ship byte-identical `.pyc`. The hash warning will reveal it;
  a German install may also carry `GermanConfig.pyc` that the English-built
  manifest does not list (it would be ignored; the English config path is
  used, as today).
- Whether other retail builds list the same module paths. A build missing a
  listed module stops at boot (§4.1a) until its manifest entry is reviewed.

## 9. Files touching the SDK path today (2026-11-11 grep)

engine: `appc/ai_native.py`, `appc/localization.py`, `bridge_selection.py`,
`dev_character_viewscreen.py`, `dev_missions/ship_preview.py`, `host_loop.py`,
`missions/name_resolver.py`, `missions/discovery.py` (via host_loop),
`mods.py`, `paths.py`, `ui/first_run_panel.py`.
native: `src/host/host_main.cc`, `src/platform/folder_picker.cc`.
scripts: `package.py`.
tools: `bake_impulse_glow.py`, `bake_set_course_catalog.py`,
`bake_star_colors.py`, `bake_warp_glow.py`, `golden_ab_side.py`,
`mission_harness.py`, `pick_simplest_mission.py`, `setup.py`,
`systems/survey.py`, `tgl_harness.py`.
tests: `conftest.py`, `helpers/write_audit.py`,
`host/test_host_loop_first_run.py`, `integration/test_bake_set_course_catalog.py`,
`integration/test_e1m1_ship_identity.py`, `integration/test_hardpoint_parser.py`,
`integration/test_officer_placement_sdk.py`,
`integration/test_packaged_readonly_e2e.py`, `integration/test_sdk_bridge_load.py`,
`integration/test_ship_catalog_stock_content.py`, `missions/conftest.py`,
`missions/test_discovery.py`, `missions/test_registry.py`,
`missions/test_tgl_harness.py`, `tools/test_golden_ab_side.py`,
`tools/test_pick_simplest_mission.py`,
`unit/test_combat_stress_avoidance_default.py`,
`unit/test_dev_key_collisions.py`, `unit/test_first_run_panel.py`,
`unit/test_mods_boot.py`, `unit/test_mods_sdk_finder.py`,
`unit/test_paths_late_reconfigure.py`, `unit/test_paths_picked_source.py`,
`unit/test_paths_resolve.py`, `unit/test_paths_validate.py`,
`unit/test_preprocess_done_is_lethal.py`, `unit/test_py15_stock_oracle.py`,
`unit/test_sdk_finder_claimed_reentry.py`,
`unit/test_sdk_finder_twins_stay_in_sync.py`,
`unit/test_structure_parts_cache_root.py`, `unit/test_wc_modifier_constants.py`.
