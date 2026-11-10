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
3. **GitHub Actions CI** that answers as much of "did this break anything?"
   as can be answered without BC content:
   - **Layer 1, rules check:** the project's tree guards and drift tests, plus
     new repo-hygiene rules.
   - **Layer 2, build and content-free tests:** build on macOS, Windows and
     Linux; run the C++ and Python tests that need no BC content.
4. CI results honest about what they cover: a green tick means "builds
   everywhere, keeps the rules, passes the content-free tests", never "the
   game still works".

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
  loader can be tested without BC. Layer 2 should make it easy to add, nothing
  more. The mesh-fix drift test can never use it: its inputs are the stock
  hulls by content hash.
- Replacing the merge gate or the full gate. Both keep their rules
  (CLAUDE.md "Test gate"). CI adds a signal; it does not move the gate.

## 4. Anti-goals (would make this a failure even if it works)

- CI that is green while testing nothing: mass skips counted as passes.
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

There are no workflows today (`.github/` does not exist).

### 7.1 Constraints found in the code

- `tests/conftest.py` **fails fast** without both BC roots, on purpose (no
  800 silent skips). Every pytest test, the tree guards included, is behind
  it today.
- The conftest's autouse fixture calls `native_combat.configure()` and
  `native_motion.configure()`, which need the built `_dauntless_host`
  module. So pytest in CI runs after a build, unless the builder finds a
  clean way to run the pure guards without one.
- About 52 of the 256 gtest source files reference the content root
  (`native/tests/support/content_root.h`); the rest may still need a GL
  context or CEF (`renderer_tests`, `ui_cef_gpu_tests`). GitHub runners have
  no GPU.
- The build fetches CEF (pinned, hashed; ~hundreds of MB per platform),
  pybind11, nlohmann_json and OpenAL Soft. Intel macOS has no CEF hash; the
  macOS runner must be arm64.
- `.gitattributes` forces LF everywhere; the drift tests rely on it, which
  matters on the Windows runner.

### 7.2 Layer 1 — rules check

Runs on every PR and every push to `main`. Linux. Target: a few minutes once
the build is cached.

Content:

1. The existing tree guards and drift tests that need no BC content:
   `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`,
   `tests/tools/test_raw_key_reads.py`, `tests/unit/test_gate_tiers.py`,
   `tests/docs/`, and the drift tests `test_app_icon_drift.py`,
   `test_dauntless_dialogue_drift.py`, `test_rock_catalogue_drift.py`,
   `test_sprite_drift.py`, `test_viewscreen_font_drift.py`. **Not**
   `test_mesh_fixes_drift.py` (reads stock NIFs). Each must actually pass with
   no BC content; one that turns out to read content is dropped from CI and
   the plan says so.
2. **`tests/known_failures.txt` holds no failure entries** (the ledger rule).
3. **File-size rule (my call on thresholds):**
   - any file under `tests/` added or changed by the PR over **256 KB** fails;
   - any other added or changed file over **5 MB** fails unless its path is
     listed in a committed allowlist (`tools/ci/large_files.txt`, path +
     reason). The allowlist is seeded with today's files over 5 MB;
   - the job summary always lists every added/changed file over 1 MB, so
     growth is visible without failing.

### 7.3 Layer 2 — build and content-free tests

Runs on every PR and every push to `main`, one job per platform: macOS arm64,
Windows x64, Linux x64.

1. **Build** with the project's normal command (`cmake -B build -S . &&
   cmake --build build -j`), Release or the project default — the builder
   picks and says why. Cache CEF and the FetchContent downloads.
2. **Content-free gtests:** run each gtest binary from a generated list of
   tests that pass with no BC content and no GPU.
3. **Content-free pytest:** on Linux at least (all three if cheap): the tests
   from a generated list that pass with no BC content.

**No silent skips (anti-goal §4).** CI never runs "everything and lets
content tests skip". It runs an explicit list, and **any test on the list
that skips or errors fails the job**.

**Every test is classified; a new test is classified by rule (my call).**
There are two GENERATED lists, never hand-edited: `content_free` (passes with
no BC content) and `needs_content`. Every test (pytest node ID; each gtest
case) is on exactly one of them. A guard test, cheap and in the merge tier,
fails on:
- a test on neither list ("unclassified"), with the command that fixes it;
- a listed test that no longer exists.

The classify command runs **only the unclassified tests**, in the no-content
mode, on this machine, and adds each to the list its result puts it on. That
is a handful of focused tests, not a suite run, so it is allowed under the
"focused tests only" rule, and a developer or contributor runs it in the same
change that adds the test. This matches the gate tiers' "in by rule, not by
memory": a new content-free test reaches CI the moment it is classified,
which is in the change that adds it. One list serves all three platforms. A
content-free test that fails on Windows, macOS or Linux CI is a real failure
on that platform, never a reason to drop it from the list. (How the first
Windows and macOS runs treat the failures they will surface is §7.5.)

To run pytest with no BC content at all, the conftest needs an explicit,
narrow CI mode (an env var) in which it skips the fail-fast and SDK set-up
but **only collects tests on the list**. Outside that mode the fail-fast is
unchanged. The builder designs the mode; the fail-fast's purpose must
survive it.

**The first classification** means running every test once with no content
roots. That is a whole-suite run, which CLAUDE.md forbids unasked on this
machine. So it runs on a GitHub Linux runner **(my call)**: a manually
triggered (`workflow_dispatch`) job that uploads the two lists as an artifact
for a person to commit. It costs this machine nothing, and it is the
environment the lists are for (no GPU, no content). The same job is how the
lists are rebuilt wholesale later. After the first time, the classify command
above keeps them current.

**Layer 2 should make later additions easy:** a licensed test NIF (§3)
dropped into a fixtures directory is picked up by a content-free test, and
cross-platform behaviour scenes (short scenes on made-up ships, checking
outcomes within a tolerance) can be added as ordinary tests on the list.
Building those scenes is not in this work.

### 7.4 Workflow behaviour

- Triggers: `pull_request` (not `pull_request_target`: contributor code must
  never run with repo secrets) and `push` to `main`. No secrets are needed.
- Fork PRs from first-time contributors wait for approval (GitHub's default
  for public repos); keep that default.
- Merging is not blocked on CI by branch protection **(my call)**: Mark
  merges locally and pushes, and the merge gate stays the authority. CI
  reports; it does not gate.
- Each job's summary states plainly what was and was not tested
  ("content-free tests only; gameplay scenes need BC content and were not
  run"), so a green tick is never read as more than it is.

### 7.5 First runs on each platform: failures are listed, printed, and only shrink

Decided by Mark: the Windows and macOS jobs go live even though their first
runs will surface failing content-free tests (parts of Windows have never
run). The failures are listed and printed on every run until they are fixed.

- Each platform has its own ledger, `tools/ci/failing_<platform>.txt`: test
  ID plus a one-line reason. It is **separate from `tests/known_failures.txt`**,
  which stays empty and is still checked by layer 1. These ledgers record
  platform bugs that CI found, not baselines for the gates.
- A ledger is seeded **once**, from that platform's first full run of the
  `content_free` list. After that it can **only shrink**:
  - a failure not on the ledger fails the job (a new regression, to fix, not
    to list);
  - a listed test that now passes fails the job with "remove it from the
    ledger", so a fix is recorded the moment it lands;
  - no tool or workflow appends entries after seeding.
- Every run's job summary prints the platform's ledger in full (count first,
  then each test and reason), so the open platform bugs are never out of
  sight.
- The same mechanism applies to Linux **(my call)**, though Linux is
  expected to seed with few or no entries.
- Fixing ledger entries is ordinary bug work, outside this spec. Filing them
  as GitHub issues follows CLAUDE.md's issue rules (only when Mark asks).

## 8. Order of work

1. Part A (retire the recordings), first: it unblocks merges now.
2. Part B (golden A/B), so refactor branches have a replacement before they
   need one.
3. Part C layer 1, then layer 2 (Linux first, then macOS, then Windows).

Each part merges on its own. Per CLAUDE.md, no gate runs per task; focused
tests plus the tree guards during development.

## 9. Open for later

- Self-hosted runner with BC content for the merge gate on PRs.
- The community test NIF and the cross-platform behaviour scenes.
- History rewrite, if repo size ever becomes a real problem.
