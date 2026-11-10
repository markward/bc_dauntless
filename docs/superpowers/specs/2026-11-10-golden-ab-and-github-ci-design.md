# Retire the recorded golden fights; add a golden A/B tool and GitHub CI

Status: design, 2026-11-10. Agreed with Mark in conversation; calls marked
**(my call)** were made by the author and are open to Mark's correction.

## 1. Why

The recorded golden fights (`tests/fixtures/golden_fights/*.darwin.json.gz`,
checked by `tests/integration/test_golden_fights.py` and
`tests/integration/test_native_subsystems_scene.py`) were built as the oracle
for retiring fire control's Python copy: record the Python arm, check the
native arm against it. That job is finished; the Python arm is deleted. What
is left is a bit-exact, every-tick, every-float change detector, and it now
costs more than it returns:

- **Merge conflicts.** Almost every gameplay change re-records several scenes
  on purpose (23 re-record commits on `main` since 2026-11-03). A recording
  is a binary file, so two branches that both re-record cannot merge; the
  only resolution is to record again on the merged tree (`e8d2c880a` did
  exactly that).
- **Repository growth.** The recordings are gzipped JSON (0.5–25 MB each
  uncompressed), and gzip defeats git's delta compression, so each re-record
  stores the whole file again: ~124 MB of a 270 MB pack in 8 days, 81 MB of
  it already on `origin/main`.
- **No CI, no other platform.** They need BC content (never on GitHub) and
  exist only for `darwin`; on any other platform the check skips (ruling R9).
  They have never compared a Windows or Linux run.

Cross-platform bit-exactness is **not a goal**: clang/arm64 contracts
multiply-adds into FMA by default and MSVC/x64 does not, each platform's libm
rounds transcendental functions its own way (Python's `math` included), and a
one-ulp difference in a long fight grows into a different fight. Bit-exact is
achievable, and useful, only within one machine.

What Mark wants from CI, in his words: to learn **whether a change has broken
anything** before opening the diff, on contributor PRs and on pushes to main.

## 2. Goals

1. Stop committing per-tick recordings. No new recording is ever added.
2. An on-demand **golden A/B**: run the same scenes at a base commit and at
   HEAD on the same machine and report where they first differ. This is how a
   refactor, perf or native-port branch proves "no behaviour change", and how
   a behaviour change describes itself.
3. **GitHub Actions CI**, deliberately small: build on macOS, Windows and
   Linux, and run the project's rules checks (tree guards, drift tests, a
   file-size rule). No gameplay or unit tests run on GitHub in this work.
4. CI results honest about what they cover: a green tick means "builds on
   all three platforms and keeps the rules", never "the game still works".

## 3. Non-goals

- Rewriting git history to remove the 81 MB already pushed. Public repo,
  ~900 downloads, outside contributors: a rewrite breaks every clone, fork
  and open PR. Stopping now caps the cost; `git filter-repo` stays possible
  later and is no harder for waiting.
- Cross-platform bit-exact simulation.
- Running anything that needs BC content (game files or SDK) on GitHub's
  machines. Uploading BC content anywhere, including as a secret or cache, is
  out.
- A self-hosted runner with BC installed (which would let the merge gate run
  on PRs). Possible later step; not in this work. This Mac is never that
  runner: it is used for performance testing.
- A licensable test NIF from the community (Mark will ask later) so the NIF
  loader can be tested without BC. The mesh-fix drift test can never use it: its inputs are the stock
  hulls by content hash.
- Running unit or gameplay tests on GitHub. Planned once and cut on
  2026-11-10 (§7.4): classifying ~19,000 tests into CI and local lists, and
  keeping per-platform failure ledgers, would have added a "classify before
  you can merge" chore to every new test file, the kind of friction this
  spec exists to remove, for a signal limited to tests that never touch BC
  content.
- Replacing the merge gate or the full gate. Both keep their rules
  (CLAUDE.md "Test gate"). CI adds a signal; it does not move the gate.

## 4. Anti-goals (would make this a failure even if it works)

- CI that is green while testing nothing: a check that skips counts as
  failed, never passed.
- CI that needs BC content, or quietly downloads or caches it.
- A golden A/B that runs as part of a gate, per task, or automatically on this
  machine (it is CPU-heavy and wrecks perf baselines).
- A replacement for the recordings that conflicts on merge in a new form
  (e.g. committed digests that still need re-recording).
- A file-size rule that blocks legitimate art: the repo already holds 32
  files over 1 MB (textures, sprites, bridge maps, `scuff_normal.tga` at
  12 MB).

## 5. Part A — retire the recordings

**Delete** `tests/fixtures/golden_fights/` (11 files) and the record/compare
path: `golden_fight.record`, `check`, `path`, `_load`, `_encode`, `_decode`,
`header`, the `UPDATE_COMBAT_GOLDEN` / `COMBAT_GOLDEN_REASON` /
`COMBAT_GOLDEN_ARM` switches, and the tests that exist only to test that
machinery (`test_golden_missing_platform_skips` and its neighbours).

**Keep** everything else in `tests/helpers/golden_fight.py`: the scene table,
`run_scene` and the row builders (`_pose_rows`, `_stage_rows`, `_k1_state`,
…). They are reused by `tests/helpers/native_ai_ab.py` (the native AI A/B)
and `tests/unit/test_native_motion_differential.py`, and they are what the
golden A/B (Part B) runs.

**Keep the invariants the golden tests also asserted**, as ordinary tests
with no recording: every scene runs with no `k1_no_fire`, no dropped row, no
`TurnGoal` hand-back and no native subsystem skip. Same for
`test_native_subsystems_scene.py`: keep its non-recording assertions, drop
its whole-log golden. Whether each scene stays a separate test, and which
gate tier it lands in, is the builder's call within the gate-tier rules.

**Keep the Python-motion vs native-motion check, live (my call).**
`test_motion_branches_python_motion_arm` today runs `motion_branches` with
`DAUNTLESS_NATIVE_MOTION=0` and checks it against the native recording. It is
the only whole-scene proof that kernel M matches `ship_motion.py` bit for bit,
and CLAUDE.md keeps `ship_motion.py` as the reference. It becomes a two-arm
comparison with no recording: both arms run in the same test, each in its own
child process (the `native_ai_ab` pattern), and their rows must be identical.
It costs about twice the scene's runtime in whichever tier it lands. Any other
test that compares an arm against a recording rather than a regression
fixture gets the same treatment; the builder lists them in the plan.

**Register `native_subsystems_scene` as a scene (my call).** Today
`test_native_subsystems_scene.py` adds it to `golden_fight.SCENES` with
`monkeypatch.setitem` at test time, so a tool that walks `SCENES` would never
see it. Move it into `SCENES` so the golden A/B covers the native subsystem
stage.

**Leave alone (my call):** the other recorded fixtures are small and rarely
change, so they are not the problem this spec solves:
`tests/fixtures/k1_dispatch/` (40 files, 540 KB, 4 commits, 0.3 MB of
history), `tests/fixtures/render_goldens/` (124 KB, 2 commits), the beam
trace golden (`DAUNTLESS_RECORD_TRACE_GOLDEN`), the stock particle
descriptors and `mod_layouts`. The new size rule (§7.2) stops any of them
growing into the same problem. Mark may choose to retire `k1_dispatch` too;
it has the same origin (Python arm recorded, native checked).

**Gate tiers.** Removed tests will leave stale entries in
`tests/gate_tiers/deep_pytest.txt`, which `test_gate_tiers.py` rejects. The
lists are generated, never hand-edited: the builder must find the sanctioned
way to drop entries for deleted tests (check `tools/gate_tiers.py`; if it has
none, add a prune that only removes entries whose test no longer exists, and
say so in the plan).

**Docs to update** (every mention found by grep on 2026-11-10): CLAUDE.md
(the "Native combat mirror" row cites `tests/integration/test_golden_fights.py`;
the "Native AI tree engine" row mentions goldens),
`docs/reference/engine/native-motion/golden-fights-for-motion.md`,
`docs/reference/engine/native-combat/{k1-retirement-map,k2-beams-map,k3-k4-map,weapon-state-map}.md`,
`docs/reference/engine/native-motion/radius-scale-audit.md`,
`docs/reference/architecture/{test-suite-audit,test-suite-memory}.md`,
and the comment in `native/tests/combat/k1_fire_control_test.cc`. Historical
specs and plans stay as written. `tests/docs/test_doc_consistency.py` must
still pass.

From the merge of this work on, a commit that changes gameplay describes its
change in the commit message (first divergent tick, what differs), as the
re-record commits' reasons do today, optionally pasted from a golden A/B
report.

## 6. Part B — the golden A/B tool

**What it does.** Runs the golden scenes at two commits on this machine and
reports, per scene, whether they are identical and if not where they first
differ.

**Interface (my call on names):**

```
uv run python tools/golden_ab.py [--base <rev>] [--scene <name> ...] [--ticks N]
```

- `--base` defaults to `git merge-base HEAD main`. HEAD is the current
  working tree, uncommitted changes included (that is what a developer wants
  to check).
- No `--scene` = every scene in `golden_fight.SCENES`.
- Exit 0 when every scene is identical, 1 when any differs, 2 on a tool error
  (build failed, scene crashed on one side). A crash on one side is reported
  as such, never as "differs".

**How (decided):**

- The base side runs in a temporary `git worktree` of `<base>` with **its own
  build** of the native module. Never a symlinked `build/`: a worktree whose
  `build/` points at main's runs main's Python (known trap). Read-only git
  plus `git worktree add/remove` only; never any command in CLAUDE.md's
  banned list.
- Each side runs each scene in a **child process** (as `native_ai_ab` does),
  so native global state never crosses sides or scenes, and writes its rows
  to a file outside the repo (`paths.cache_dir()` or a temp dir). Rows are
  the existing row builders' output: floats as `.hex()`, so equality is bit
  equality.
- Both sides use the same BC content roots and the same Python environment.
- **Each side runs its own scene and row code (my call).** The child driver
  is the tool's own (HEAD's `tools/`), and it calls the side's own
  `golden_fight.run_scene` and row builders, as that commit wrote them. The
  question asked is "how does this commit's engine behave in this commit's
  scene", and running HEAD's harness against older engine code would mix the
  two. If `tests/helpers/golden_fight.py` (or anything it imports from
  `tests/helpers/`) differs between base and HEAD, the report says so on its
  first line and names the files, because a difference may then come from the
  harness. A scene present on only one side is reported as "only in base" or
  "only in HEAD", never as "differs". A base whose `golden_fight` lacks
  `run_scene` or `SCENES` in today's shape is a tool error that names the
  oldest usable commit; there's no requirement to reach further back.
- **HEAD is built before it runs (my call).** A stale `build/` would give a
  false "identical", which is the worst outcome this tool can have. So the
  tool runs the project's normal incremental build of the current tree's
  `build/` before running HEAD's side (the one build tree, no second build
  directory for HEAD), and stops with an error if the build fails. On the
  shared main checkout, "the current tree" includes other sessions'
  uncommitted edits. So run the tool from the branch's own worktree, which
  has its own `build/`, and the tool's help text says so.

**Left to the builder:** how the base build is made cheap enough to use
(cache base builds by commit under `paths.cache_dir()`, build only the
targets the scenes need, reuse an existing worktree); whether scenes run in
parallel (default serial: this machine is shared for perf work); how worktree
and cache are cleaned up.

**The report.** One line per scene: `identical` or `differs`. For each scene
that differs:

- the first differing tick, and for that tick each differing field as
  `ship / subsystem-or-field : base value → head value`, floats shown as
  decimals (hex in brackets), at most ~20 fields;
- how many ticks differ in total, and the last differing tick;
- whether the first difference is in poses, events, calls or stage state
  (the row kinds the scene records), so "the motion changed" reads at a
  glance.

The report is plain text on stdout, suitable for pasting into a commit
message. A `--json` option is the builder's call.

**When it is run.** On demand only, by a person or a session doing
refactor, perf or native-port work, before merging, to show the branch
changes nothing (or exactly what it changes). It is never part of either
gate, CI, or a per-task loop, and never run unasked on this machine.

## 7. Part C — GitHub Actions CI

There are no workflows today (`.github/` does not exist). Mark's question
was whether CI would make things easier; it does only where the signal is
real and the upkeep is near zero. So Part C is builds plus rules checks, and
nothing that needs a list maintained by hand or by generator.

### 7.1 Constraints found in the code

- `tests/conftest.py` **fails fast** without both BC roots, on purpose. CI
  satisfies it with a **fake install**: a temp tree holding only the markers
  `engine.paths` validates, built by the same code as the existing
  `fake_bc_install` fixture. The conftest itself is unchanged.
- The conftest's autouse fixture configures native combat, which needs the
  built `_dauntless_host` module, so the pytest rules checks run after the
  build.
- The build fetches CEF (pinned, hashed, hundreds of MB per platform),
  pybind11, nlohmann_json, OpenAL Soft and FreeType. Intel macOS has no CEF
  hash, so the macOS runner must be arm64. Cache the FetchContent downloads.
- `.gitattributes` forces LF everywhere; Windows must not override it.
- Debug is the canonical build type (some digest tests are bit-exact only at
  -O0); CI builds Debug so a later test step would not need a second build.

### 7.2 Builds

Every PR and every push to `main`, one job per platform: Linux x64, macOS
arm64, Windows x64 (MSVC). Each runs the project's normal configure and
build (`cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug` plus the Python pins,
then `cmake --build build -j`), CEF on, and fails if the build fails. That
is the whole job on macOS and Windows.

### 7.3 Rules checks (Linux job, after its build)

1. The existing tree guards and drift tests, run with pytest against the
   fake install: `tests/unit/test_path_indirection.py`,
   `tests/unit/test_install_write_guard.py`, `tests/tools/test_raw_key_reads.py`,
   `tests/unit/test_gate_tiers.py`, `tests/docs/`, and the drift tests
   `test_app_icon_drift.py`, `test_dauntless_dialogue_drift.py`,
   `test_rock_catalogue_drift.py`, `test_sprite_drift.py`,
   `test_viewscreen_font_drift.py`. **Not** `test_mesh_fixes_drift.py` (reads
   stock NIFs). This is a fixed list in the workflow. Any skip fails the step
   (`-rs` plus a check of the summary, or pytest's own option the builder
   picks). A check that turns out to need BC content is removed from the
   list in the same change, and the plan's hand-off says so.
2. **`tests/known_failures.txt` holds no failure entries**: every
   non-comment line starts with `skip:` or `optional-mod:`.
3. **File-size rule (my call on thresholds):**
   - any file under `tests/` added or changed over **256 KB** fails;
   - any other added or changed file over **5 MB** fails unless listed in
     `tools/ci/large_files.txt` (path + reason), seeded with today's files
     over 5 MB;
   - the job summary lists every added or changed file over 1 MB.

The rules checks run on Linux only **(my call)**: they test the tree, not
the platform. Running them on Windows too (where the drift tests would also
catch line-ending trouble) is a later option.

### 7.4 What was cut, and why (decided by Mark, 2026-11-10)

An earlier version of this section ran every test that needs no BC content:
two generated lists classifying all ~16,000 Python and ~3,000 C++ tests, a
merge-tier guard failing on any unclassified test, a classify command, and
shrink-only failure ledgers per platform. Mark asked whether it would make
things easier; it would not. Every new test file would need classifying
before it could merge, a chore of the same kind as re-recording goldens; the
ledgers would mean debugging failures that exist only on GitHub's runners (no
GPU, fake install); and the signal covers only tests that never touch BC
content, while Mark merges locally and pushes `main` only occasionally. The
earlier ruling on ledgers (Windows and macOS go live with failures listed) is
moot with them.

If the build-only CI proves useful, running tests on GitHub is a separate,
later spec, starting from which tests are worth it.

### 7.5 Workflow behaviour

- Triggers: `pull_request` (never `pull_request_target`: contributor code
  must never run with repo secrets), `push` to `main`, and
  `workflow_dispatch`. Permissions `contents: read`; no secrets.
- Fork PRs from first-time contributors wait for approval (GitHub's default
  for public repos); keep it.
- Merging is not blocked on CI by branch protection **(my call)**: Mark
  merges locally and pushes, and the merge gate stays the authority.
- Each job's summary begins: "Builds and rules checks only: no unit or
  gameplay tests run on GitHub."

## 8. Order of work

1. Part A (retire the recordings), first: it unblocks merges now.
2. Part B (golden A/B), so refactor branches have a replacement before they
   need one.
3. Part C: the Linux build and rules checks, then the macOS and Windows
   builds.

Each part merges on its own. Per CLAUDE.md, no gate runs per task; focused
tests plus the tree guards during development.

## 9. Open for later

- Running tests on GitHub (§7.4), if the build-only CI earns its keep.
- Self-hosted runner with BC content for the merge gate on PRs.
- The community test NIF and the cross-platform behaviour scenes.
- History rewrite, if repo size ever becomes a real problem.
