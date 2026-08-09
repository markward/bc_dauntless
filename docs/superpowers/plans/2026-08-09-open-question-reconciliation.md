# Open-Question Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish, from code, which of the project's 26 open questions and 6 gap-claim docs are actually still open; correct the record; and leave machine-checked guards so the counts cannot drift silently again.

**Architecture:** Evidence-first sweep. Our code and tests answer "did we build it"; the `stbc-reference` MCP answers "what should it do"; SDK scripts answer "is anything calling this". Phase 1 establishes truth per gap area, Phase 2 lands corrections as reviewable commits, and the plan terminates in a triage report that scopes Phase 3.

**Tech Stack:** Python 3 / pytest, markdown docs, `stbc-reference` MCP tools, `scripts/check_tests.sh` gate.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-09-open-question-reconciliation-design.md`. Read it before Task 1.
- **Branch:** `fix/open-question-reconciliation` (already created, 4 commits in).
- **Evidence standard:** no item changes status without a code citation (`file.py:line`) or a passing test. Prose docs are NEVER evidence about our own implementation.
- **Shared checkout:** stage with explicit pathspecs only. NEVER `git add -A`, `git add .`, `git stash`, `git clean`, `git reset --hard`, `git checkout -- <path>`, `git restore`. `.gitignore` and `.claude/` belong to other sessions — do not touch or stage them.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest AND ctest, diffs against `tests/known_failures.txt`). NOT `scripts/run_tests.sh`, which is pytest-only. Read `tests/known_failures.txt` for the baseline; never trust a remembered failure count.
- **Permitted status outcomes:** `resolved` (cite code/test) · `genuinely open` (cite absence + callers) · `superseded` (question no longer applies) · `dead surface` (SWIG binding only, zero SDK call sites).
- **MCP discipline:** refusals are real outcomes — record them, never rephrase to extract a guess. Renderer is out of scope by design. If an answer does not name the specific class/offset/constant asked about, re-ask naming the spec document before concluding anything is undocumented.
- **Never claim done without running the gate.** Audio and renderer items cannot be verified headlessly and must be reported as needing Mark's live run.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `tests/docs/__init__.py` | package marker | 1 |
| `tests/docs/test_doc_consistency.py` | mechanical guards: declared counts must match actual contents | 1, 9 |
| `docs/gap_analysis.md` | OQ statuses + "Still open" summary | 1–7, 9 |
| `docs/open_questions.md` | 4 instrumentation questions | 6 |
| `docs/stub_heatmap.md` | `markedResolvedOn` dates | 8 |
| `docs/engine/*.md` | gap assertions only (not format/RE content) | 7 |
| `CLAUDE.md` | OQ totals at lines 38 and 64 | 1, 9 |
| `docs/superpowers/plans/2026-08-09-triage-report.md` | Phase 3 scope | 9 |

---

### Task 1: Doc-consistency guards and count corrections

Purely mechanical — no research. Establishes the ratchet that makes later drift a test failure.

**Files:**
- Create: `tests/docs/__init__.py`
- Create: `tests/docs/test_doc_consistency.py`
- Modify: `docs/gap_analysis.md:723`
- Modify: `CLAUDE.md:38`, `CLAUDE.md:64`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/docs/test_doc_consistency.py` with helpers `oq_headings(text) -> list[str]` and `unmarked_oqs(text) -> list[str]`, reused in Task 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/docs/__init__.py` as an empty file. Then create `tests/docs/test_doc_consistency.py`:

```python
"""Mechanical guards on self-reported counts in project docs.

These exist because gap_analysis.md, CLAUDE.md and stub_heatmap.md each declare
counts that drifted from their own contents, which produced confident, wrong
scoping work. A declared number that disagrees with the table under it is a bug.
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAP_ANALYSIS = PROJECT_ROOT / "docs" / "gap_analysis.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
HEATMAP = PROJECT_ROOT / "docs" / "stub_heatmap.md"

# A status marker is a green tick (resolved) or a warning sign (partial).
STATUS_MARKERS = ("✅", "⚠")


def oq_headings(text: str) -> list[str]:
    """Every '**OQ-N.M — ...**' heading line in the document, verbatim."""
    return re.findall(r"^\*\*OQ-\d+\.\d+.*$", text, flags=re.MULTILINE)


def unmarked_oqs(text: str) -> list[str]:
    """OQ headings carrying no status marker — i.e. still open."""
    return [h for h in oq_headings(text) if not any(m in h for m in STATUS_MARKERS)]


def test_still_open_count_matches_unmarked_oqs():
    """The '(N)' on the 'Still open' line must equal the OQs lacking a marker."""
    text = GAP_ANALYSIS.read_text(encoding="utf-8")
    match = re.search(r"Still open:.*?\((\d+)\)", text)
    assert match, "gap_analysis.md has no 'Still open: ... (N)' summary line"
    declared = int(match.group(1))
    actual = unmarked_oqs(text)
    assert declared == len(actual), (
        f"gap_analysis.md declares {declared} still open but {len(actual)} OQ "
        f"headings carry no status marker: {[h[:40] for h in actual]}"
    )


def test_claude_md_oq_total_matches_gap_analysis():
    """CLAUDE.md's OQ total must equal the OQ headings in gap_analysis.md."""
    total = len(oq_headings(GAP_ANALYSIS.read_text(encoding="utf-8")))
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    match = re.search(r"Gap analysis OQs \((\d+) total\)", claude)
    assert match, "CLAUDE.md has no '### Gap analysis OQs (N total)' heading"
    assert int(match.group(1)) == total, (
        f"CLAUDE.md claims {match.group(1)} OQs; gap_analysis.md has {total}"
    )


def test_heatmap_header_open_count_matches_table():
    """Regression guard: header 'Open: N' must equal open-roadmap row count.

    This currently PASSES (229 == 229). It is here to keep it that way.
    """
    text = HEATMAP.read_text(encoding="utf-8")
    match = re.search(r"Open: (\d+),", text)
    assert match, "stub_heatmap.md header has no 'Open: N,' count"
    declared = int(match.group(1))

    # The open roadmap is the section before '## Resolved'.
    open_section = text.split("## Resolved")[0]
    rows = re.findall(r"^\| \d+ \|", open_section, flags=re.MULTILINE)
    assert declared == len(rows), (
        f"heatmap header declares {declared} open rows; table has {len(rows)}"
    )
```

- [ ] **Step 2: Run tests to verify the first two fail**

Run: `uv run pytest tests/docs/test_doc_consistency.py -v`

Expected: `test_still_open_count_matches_unmarked_oqs` FAILS (declares 5, actual 6).
`test_claude_md_oq_total_matches_gap_analysis` FAILS (claims 21, actual 26).
`test_heatmap_header_open_count_matches_table` PASSES (229 == 229).

If the heatmap test fails, stop — the header genuinely drifted since this plan was written; record the real numbers and adjust before continuing.

- [ ] **Step 3: Correct the declared counts**

In `docs/gap_analysis.md:723`, change `(5)` to `(6)`. The line lists six items — OQ-3.1, 3.2, 3.3, 6.1, 8.3, 8.4 — because `OQ-3.1–3.3` is a three-item range.

In `CLAUDE.md:38`, change `8 gaps, 21 open questions, solution paths` to `8 gaps, 26 open questions, solution paths`.

In `CLAUDE.md:64`, change `### Gap analysis OQs (21 total)` to `### Gap analysis OQs (26 total)`.

- [ ] **Step 4: Run tests to verify all pass**

Run: `uv run pytest tests/docs/test_doc_consistency.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. Any failure not in `tests/known_failures.txt` is a regression from this task — fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add tests/docs/__init__.py tests/docs/test_doc_consistency.py docs/gap_analysis.md CLAUDE.md
git commit -m "test(docs): guard self-reported OQ counts against contents

gap_analysis.md declared 5 still-open OQs while listing 6; CLAUDE.md claimed 21
OQs against 26 present. Both corrected and now machine-checked."
```

---

### Task 2: Audit OQ-3.1, 3.2, 3.3 (renderer / NIF)

**Files:**
- Modify: `docs/gap_analysis.md:223-240`
- Test: add guards only where a "resolved" conclusion has no existing test

**Interfaces:**
- Consumes: `unmarked_oqs()` from Task 1 (to confirm the three are currently unmarked).
- Produces: status markers on OQ-3.1/3.2/3.3; evidence lines cited in the triage report (Task 9).

- [ ] **Step 1: Establish truth for OQ-3.1 (BC NIF compatibility with OpenMW loader)**

The question presupposes we would use OpenMW's loader. Confirm we wrote our own:

```bash
grep -rn "openmw\|OpenMW" native/ engine/ docs/ --include=*.cc --include=*.h --include=*.py --include=*.md | head
ls native/src/nif/ 2>/dev/null || find native -name "*nif*" -maxdepth 3
```

Expected: our own NIF loader under `native/`, no OpenMW dependency. If so the question is **superseded** — not "answered". Record the loader path as evidence.

- [ ] **Step 2: Establish truth for OQ-3.2 (damage geometry tagging)**

```bash
grep -rn "SetDamageResolution" engine/ sdk/Build/scripts/ | head
grep -rln "voxel\|HullCarve" native/src/renderer/ engine/ | head
```

Cross-reference `docs/engine/nif-voxel-format.md` and `docs/engine/nibinaryvoxeldata-format-v3.1.md`. Decide whether the voxel hull-damage work answered "how is damage geometry marked in the NIF", or only "how do we carve damage". These are different questions — if only the latter, OQ-3.2 stays **genuinely open** with that distinction recorded.

- [ ] **Step 3: Establish truth for OQ-3.3 (character body/head assembly)**

```bash
grep -rn "ReplaceBodyAndHead" engine/ | head
grep -rn "def .*body.*head\|weld\|rigid" native/src/renderer/*character* engine/appc/characters.py 2>/dev/null | head
uv run pytest tests/ -k "character and (head or body or skin)" -v
```

If tests exist and pass, OQ-3.3 is **resolved** — cite the test node IDs. If the behaviour is implemented but untested, write one guard test asserting a body+head assembly produces a single renderable with the head node present, then cite it.

- [ ] **Step 4: Consult the MCP only where code cannot answer**

Renderer is out of scope for the reference by design. Expect refusal. Ask at most once, for OQ-3.2 only, since NIF node naming is a *format* question rather than a renderer one:

`ask_reference("What is the node naming convention that marks damage geometry in a ship NIF?", area="format")`

Record the answer or the refusal verbatim in the triage notes. Do not rephrase to extract a guess.

- [ ] **Step 5: Apply status markers**

Edit each of the three OQ headings in `docs/gap_analysis.md` to carry ✅ (resolved), ⚠️ (partial), or an explicit `— superseded` note, and add a one-line evidence citation under each. Update the "Still open" count on line 723 to match; `test_still_open_count_matches_unmarked_oqs` enforces this.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add docs/gap_analysis.md
# add any new guard test path written in Step 3
git commit -m "docs(oq): audit OQ-3.1-3.3 against the renderer we actually built"
```

---

### Task 3: Audit OQ-8.3 (MorphBody) and OQ-8.4 (animation catalogue)

**Files:**
- Modify: `docs/gap_analysis.md:653-666`

**Interfaces:**
- Produces: status markers on OQ-8.3/8.4; a dead-surface determination for `MorphBody`.

- [ ] **Step 1: Establish truth for OQ-8.3 (MorphBody)**

```bash
grep -rn "MorphBody" sdk/Build/scripts/ engine/ | grep -v "^sdk/Build/scripts/App.py"
```

Prior finding: the only hit outside `App.py` is a comment in `engine/appc/characters.py`. If that holds, `MorphBody` is **dead surface** — present in the SWIG binding, called by nothing in 1,228 SDK files. Record the exact grep output as evidence.

- [ ] **Step 2: Establish truth for OQ-8.4 (animation catalogue)**

```bash
grep -rn "LoadAnimation" engine/ | head -20
uv run pytest tests/ -k "anim" -v 2>&1 | tail -20
```

The OQ asks for a static manifest of every `LoadAnimation` path. Determine whether the shipped animation system made this moot (we load by path at runtime and missing files are handled) or whether a manifest is still needed. Cite the loader and its missing-asset behaviour.

- [ ] **Step 3: Apply status markers and evidence lines**

Same edit shape as Task 2 Step 5. `MorphBody`, if dead surface, gets a ✅ with the note that it is deliberately unimplemented and why — so it is not rediscovered as a gap.

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add docs/gap_analysis.md
git commit -m "docs(oq): audit OQ-8.3 MorphBody and OQ-8.4 animation catalogue"
```

---

### Task 4: Audit OQ-6.1 (DynamicMusic transition model)

The most likely genuine survivor. This task **establishes scope only** — it does not build.

**Files:**
- Modify: `docs/gap_analysis.md:465-471`

- [ ] **Step 1: Establish what exists**

```bash
grep -rn "DynamicMusic" engine/ | head
wc -l sdk/Build/scripts/DynamicMusic.py
grep -rn "crossfade\|fade_in\|fade_out\|SetVolume" engine/appc/*audio* engine/audio/ 2>/dev/null | head
ls tests/audio/
```

Determine three things separately: (a) is `DynamicMusic` stubbed as a module, (b) does our audio backend support crossfading at all, (c) do music state changes reach the backend today.

- [ ] **Step 2: Check both stub lists**

Whole SDK modules can be silently stubbed in two places that must agree:

```bash
grep -n "DynamicMusic" tools/mission_harness.py tests/conftest.py
```

If `DynamicMusic` is module-stubbed, note that unstubbing the whole module is forbidden by project convention — the behaviour must be reimplemented at the equivalent engine hook instead.

- [ ] **Step 3: Consult the MCP for the transition model**

`ask_reference("What does the dynamic music system do when gameplay state changes, and how are music transitions sequenced?", area="behaviour")`

Audio coverage may be thin; a refusal is a real outcome. If it answers, record the crossfade semantics — they scope the build.

- [ ] **Step 4: Record status and a scope estimate**

Mark OQ-6.1 with its true status and, if genuinely open, add a scope note covering: does the audio backend need a crossfade capability it lacks, and roughly how large that is. The spec's escalation rule applies — if this is subsystem-sized, it goes to Mark with an estimate rather than being absorbed silently.

- [ ] **Step 5: Run the gate and commit**

Run: `scripts/check_tests.sh` (expect exit 0)

```bash
git add docs/gap_analysis.md
git commit -m "docs(oq): audit OQ-6.1 DynamicMusic and scope the transition model"
```

---

### Task 5: Audit OQ-2.2 (warp physics) and OQ-2.3 (tractor beam physics)

Both currently ⚠️ partial — confirm whether they still are.

**Files:**
- Modify: `docs/gap_analysis.md:142-175`

- [ ] **Step 1: Establish truth for OQ-2.3 (tractor beams)**

```bash
grep -rn "tractor" engine/appc/*.py | head
uv run pytest tests/ -k "tractor" -v 2>&1 | tail -20
```

Tractor beams shipped (hold/tow/pull/push/dock). If the tests cover the force model, promote ⚠️ to ✅ citing them. If only the modes shipped and the force law is still tuned-by-feel, it stays ⚠️ with that stated precisely.

- [ ] **Step 2: Establish truth for OQ-2.2 (warp-exit velocity)**

```bash
grep -rn "warp" engine/appc/*.py | grep -i "velocity\|exit\|speed" | head
uv run pytest tests/ -k "warp" -v 2>&1 | tail -20
```

The teleport half is confirmed; the warp-exit velocity half was deferred to Phase 2. Determine which half is now true.

- [ ] **Step 3: Consult the MCP for warp-exit velocity if code is inconclusive**

`ask_reference("What velocity does a ship have when it leaves warp?", area="behaviour")`

- [ ] **Step 4: Record status, run gate, commit**

Run: `scripts/check_tests.sh` (expect exit 0)

```bash
git add docs/gap_analysis.md
git commit -m "docs(oq): audit OQ-2.2 warp-exit velocity and OQ-2.3 tractor physics"
```

---

### Task 6: Verify the closed OQs and `open_questions.md`

18 OQs are marked ✅ and 2 ⚠️. This is a spot-check for closures that later work may have invalidated — not a re-derivation.

**Files:**
- Modify: `docs/open_questions.md`, `docs/gap_analysis.md` (only where a closure no longer holds)

- [ ] **Step 1: Cross-check the two documents agree**

`docs/open_questions.md` Q1–Q4 duplicate `gap_analysis.md` OQ-7.1–7.4. Confirm both say the same thing:

```bash
grep -n "60 Hz\|0.204\|2%" docs/open_questions.md docs/gap_analysis.md
```

- [ ] **Step 2: Spot-check the load-bearing closures**

For each of OQ-1.3 (save format), OQ-4.4 (sequence execution), OQ-5.2 (torpedo arc geometry), confirm a test or implementation still backs the claim:

```bash
uv run pytest tests/ -k "save or sequence or torpedo" -v 2>&1 | tail -30
```

Any closure with neither test nor implementation gets **reopened** and recorded — a ✅ with no backing evidence is precisely the defect this branch exists to fix.

- [ ] **Step 3: Run the gate and commit**

Run: `scripts/check_tests.sh` (expect exit 0)

```bash
git add docs/open_questions.md docs/gap_analysis.md
git commit -m "docs(oq): verify closed OQs still hold and reconcile the two OQ documents"
```

---

### Task 7: Audit the gap assertions in `docs/engine/*.md`

Only gap **assertions** are in scope. Format and RE reference content is NOT re-derived.

**Files:**
- Modify: `docs/engine/aieditor-ai-surface-and-gaps.md`, `docs/engine/damagetool-and-hull-damage-gaps.md`, and any of the other four that assert a gap

- [ ] **Step 1: Fix the known-false claim first**

`docs/engine/aieditor-ai-surface-and-gaps.md` asserts `GetCloakingSubsystem` is "stubbed `None`". It is implemented at `engine/appc/ships.py:992`. Correct it, and add the MCP confirmation that `ShipClass_GetCloakingSubsystem` dispatches at `0x0060a4b0`.

- [ ] **Step 2: Check the document's other three claims**

```bash
grep -rn "RandomAI" engine/appc/ai.py engine/appc/ai_driver.py | head
grep -rn "class Condition" engine/appc/*.py | wc -l
```

The doc claims `RandomAI` is never dispatched and that ~10 Condition rows are unverified. Confirm or correct each against code.

- [ ] **Step 3: Check `damagetool-and-hull-damage-gaps.md`**

It marks Gaps 1, 2 and 4 as DONE and Gap 3 as subsumed. Verify the DONE claims against `engine/appc/visible_damage.py` and `engine/appc/hull_carve.py`, and confirm the noted absence of a native `HullCarveField::clear()`:

```bash
grep -rn "clear" native/src/renderer/hull_carve* 2>/dev/null | head
```

- [ ] **Step 4: Record the cloak dead-surface finding**

In `docs/engine/aieditor-ai-surface-and-gaps.md`, record that `CloakingSubsystem_{Get,Set}CloakTime` and `_{Get,Set}ShieldDelay` exist in the SWIG binding with zero SDK call sites and are deliberately unimplemented, and that per the MCP layout answer `g_cloakTime` (`0x8e4e1c`) and `g_shieldDelay` (`0x8e4e20`) are class-static globals — one shared cloak cadence for all ships, not per-instance fields.

- [ ] **Step 5: Run the gate and commit**

Run: `scripts/check_tests.sh` (expect exit 0)

```bash
git add docs/engine/aieditor-ai-surface-and-gaps.md docs/engine/damagetool-and-hull-damage-gaps.md
git commit -m "docs(engine): correct stale gap assertions against current code"
```

---

### Task 8: Heatmap triage

**Files:**
- Modify: `docs/stub_heatmap.md` (`markedResolvedOn` column only)

- [ ] **Step 1: Select candidates mechanically**

Candidate = `lastSeenOn` at least 14 days before the newest run in the header (currently 2026-08-06), i.e. runs continued and this stub stopped being hit.

```bash
uv run python - <<'PY'
import re, datetime, pathlib
text = pathlib.Path("docs/stub_heatmap.md").read_text(encoding="utf-8")
newest = datetime.date(2026, 8, 6)
open_section = text.split("## Resolved")[0]
for row in re.findall(r"^\| \d+ \|.*$", open_section, flags=re.MULTILINE):
    cells = [c.strip() for c in row.split("|")]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", cells[6] if len(cells) > 6 else "")
    if not m:
        continue
    seen = datetime.date(*map(int, m.groups()))
    if (newest - seen).days >= 14:
        print((newest - seen).days, "days stale:", cells[2], cells[3], cells[4])
PY
```

- [ ] **Step 2: Verify each candidate in code**

For every candidate, find the implementation or the fix that stopped it being hit. `Planet.GetCloakingSubsystem` is the worked example: fixed by class-based resolution at `engine/appc/sensor_detection.py:42-50`.

A candidate with no identifiable fix STAYS OPEN with a note. Do not mark it — `markedResolvedOn` arms a regression check, and a wrong date silently disarms that detector for that stub.

- [ ] **Step 3: Date only the verified rows**

Write `2026-08-09` into `markedResolvedOn` for verified rows only. No bulk marking.

- [ ] **Step 4: Run the gate and commit**

Run: `scripts/check_tests.sh` (expect exit 0)

```bash
git add docs/stub_heatmap.md
git commit -m "docs(heatmap): mark verified-resolved stubs, one code citation each"
```

---

### Task 9: Completeness guard and triage report

**Files:**
- Modify: `tests/docs/test_doc_consistency.py`
- Modify: `CLAUDE.md:64` region (open-OQ status table)
- Create: `docs/superpowers/plans/2026-08-09-triage-report.md`

**Interfaces:**
- Consumes: `oq_headings()`, `unmarked_oqs()` from Task 1.
- Produces: the triage report that scopes the Phase 3 plan.

- [ ] **Step 1: Write the failing completeness test**

Append to `tests/docs/test_doc_consistency.py`:

```python
def test_every_unmarked_oq_is_listed_as_still_open():
    """An OQ with no status marker must appear on the 'Still open' line.

    Catches the drift where an OQ is silently left unmarked and drops out of
    the summary, becoming invisible to scoping.
    """
    text = GAP_ANALYSIS.read_text(encoding="utf-8")
    match = re.search(r"Still open: (.*?) \(\d+\)", text)
    assert match, "gap_analysis.md has no 'Still open: ... (N)' summary line"
    summary = match.group(1)
    for heading in unmarked_oqs(text):
        ident = re.match(r"\*\*(OQ-\d+\.\d+)", heading).group(1)
        number = ident.split("-")[1]
        major = number.split(".")[0]
        # Accept either an explicit mention or a range covering it,
        # e.g. 'OQ-3.1-3.3' covers OQ-3.2.
        assert ident in summary or f"OQ-{major}." in summary, (
            f"{ident} carries no status marker but is absent from the "
            f"'Still open' summary: {summary}"
        )
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/docs/test_doc_consistency.py -v`

Expected: passes if Tasks 2–7 kept the summary line in sync; fails naming any OQ that was left unmarked and unlisted. Fix `docs/gap_analysis.md:723` until green.

- [ ] **Step 3: Update the CLAUDE.md OQ status block**

Rewrite the `### Gap analysis OQs` section of `CLAUDE.md` to reflect the audited reality: which are closed by static analysis, by instrumentation, superseded, dead surface, and which genuinely remain. Keep the `(N total)` figure correct — Task 1's test enforces it.

- [ ] **Step 4: Write the triage report**

Create `docs/superpowers/plans/2026-08-09-triage-report.md` with one row per audited item:

| Item | Status | Evidence (`file:line` or test) | Phase 3? |
|---|---|---|---|

End it with the ordered Phase 3 survivor list, each with a scope estimate, and an explicit note for any item needing Mark's live verification because it cannot be checked headlessly.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add tests/docs/test_doc_consistency.py CLAUDE.md docs/superpowers/plans/2026-08-09-triage-report.md
git commit -m "docs(oq): completeness guard, corrected CLAUDE.md status, triage report

Terminates Phase 2. The triage report scopes the Phase 3 build plan."
```

---

## After this plan

Report the triage table to Mark. Phase 3 — building every survivor — gets its own plan written against the triage report, because its tasks cannot be specified until the survivor set is known. The escalation rule from the spec applies: any survivor that proves subsystem-sized goes back to Mark with an estimate rather than being absorbed into a branch that was scoped as an audit.
