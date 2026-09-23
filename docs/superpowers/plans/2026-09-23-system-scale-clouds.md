# System-scale clouds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a system map a `clouds` list — volumes carrying BC's own
MetaNebula numbers — so Vesuvi's debris and Belaruz's nebula exist at system
scale instead of only inside their regions.

**Architecture:** A `Cloud` is a set of `Volume`s. Each volume has a shape, a
`profile`, and four params; the params are the only thing that decides what a
volume does to a ship inside it. BC's authored pocket becomes a pinned volume in
system coordinates (`origin_region` set), and each cloud gains one large volume
— a sphere for Vesuvi, a lobe for Belaruz — shipped with zeroed params until the
`mist` profile is tuned. The generator derives what it can and reads the rest
from `overrides.cloud`, the same mechanism `overrides.star` already uses.

**Tech Stack:** Python 3, `uv run pytest`, existing `engine/systems/` +
`tools/systems/` modules. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-system-scale-clouds-design.md`
(extends `docs/superpowers/specs/2026-09-22-in-system-navigation-design.md`)

## Global Constraints

- **Never spell `game` or `sdk` as a path segment** in `engine/`, `tools/`, or
  `tests/conftest.py`. Ask `paths.sdk_scripts()` / `paths.game_asset(rel)`.
  Enforced by `tests/unit/test_path_indirection.py`.
- **Never capture a path at import time** in `engine/`. `map_dir()` and
  `descriptions_path()` compute per call; anything new does the same.
- **`validate()` never raises.** It returns a list of `Problem`s. A malformed
  map must be reported by rule name, never by traceback. New rules run *after*
  `malformed-geometry` and must tolerate absent/garbage values.
- **BC's numbers are copied, never chosen.** `debris` and `nebula` profile
  params come from the SDK scripts verbatim. Task 3's cross-check test is what
  makes that a fact rather than a claim.
- **Read BC's Python 1.5 scripts as TEXT.** Never import them, never `ast`-parse
  them. `tools/systems/survey.py` is regex-and-string only.
- **Shared checkout.** Stage with an explicit pathspec. Never `git add -A`,
  `git add .`, `git checkout -- <path>`, `git restore`, `git stash`,
  `git clean`, or `git reset --hard`. To mutate a file temporarily: `cp` to
  `/tmp`, edit, restore by `cp`, and `diff` to prove the restore.
- **Gate with `scripts/check_tests.sh`**, never `run_tests.sh` alone, and never
  call a failure "pre-existing" by eyeball. Expect
  `OK — no new failures. 1 known failure(s) still baselined.`
- **Regenerating must not move anything else.** After Task 6,
  `git status --porcelain engine/systems/maps` shows **only** `belaruz.json`
  and `vesuvi.json`.

## What the survey is up against (measured, 2026-09-23)

Four SDK sets build a `MetaNebula`, not two:

| Set | Nebulae in file | Spheres | `SetupDamage` | Reaches our data? |
|---|---|---|---|---|
| `Belaruz1_S.py` | 1 | 1 | absent | **yes** — region |
| `Vesuvi4_S.py` | 1 | 1 | `(150.0, 20.0)` | **yes** — region |
| `Multi5_S.py` | **4** | 13 | absent | no |
| `Multi6_S.py` | 1 | 4 | **`(1.0)` — one arg** | no |

The two `Multi*` sets never reach a map because they are single-set arenas
(`Multi5.py` + `Multi5_S.py`, no numbered children), so the survey finds zero
regions for them. They are still the only test fixtures in existence for two
real parsing hazards, and Task 1 uses them as such.

**Out of scope:** the seven `multi*.json` maps are empty shells — one fabricated
`brown_dwarf` and no regions at all. Whether they should be generated is a
separate question and this plan does not touch them.

## File Structure

| File | Responsibility |
|---|---|
| `tools/systems/survey.py` | **Modify.** Capture BC's four MetaNebula numbers; scope spheres to their own nebula. |
| `engine/systems/map.py` | **Modify.** `Volume`, `Cloud`, `SystemMap.clouds`, JSON round-trip. |
| `engine/systems/clouds.py` | **Create.** The three profiles and their params. Data only, no I/O. |
| `engine/systems/validate.py` | **Modify.** Four new rules. |
| `tools/systems/layout.py` | **Modify.** Build `Cloud`s from surveyed nebulae plus the override. |
| `tools/gen_system_maps.py` | **Modify.** `cloud_from(m)`, fed to `layout()` like `star_from(m)`. |
| `engine/systems/maps/{belaruz,vesuvi}.json` | **Modify.** Overrides authored by hand; bodies/regions regenerated. |
| `engine/systems/descriptions.json` | **Modify.** One factual correction (Task 7). |

---

### Task 1: The survey reads BC's MetaNebula numbers, and scopes spheres correctly

**Why.** Two defects block everything downstream. `_nebula` takes the **first**
`MetaNebula_Create` in a file but **every** `AddNebulaSphere` in that file — so
Multi5's four nebulae would merge into one object with the first one's colour
and all thirteen spheres. And the four numbers that decide what a cloud *does*
(visibility, sensor density, hull damage, shield damage) are not captured at all.

**Files:**
- Modify: `tools/systems/survey.py` (`_nebula`, ~line 142)
- Test: `tests/tools/test_system_survey.py`

**Interfaces:**

- Produces: `_nebula(text) -> dict | None` with keys
  `color: tuple[float,float,float]`, `spheres: list[tuple]`,
  `visibility_gu: float`, `sensor_density: float`,
  `damage_hull_per_s: float`, `damage_shield_per_s: float | None`,
  `extra_nebulae: int`.
- `SurveyedRegion.nebula` keeps its `dict | None` type and its name. Only the
  dict's contents grow.
- `damage_shield_per_s` is `None` — meaning **unknown**, not zero — when
  `SetupDamage` is called with a single argument. Absent `SetupDamage` is a real
  zero on both axes: BC set up no damage. Do not collapse those two cases.
- `extra_nebulae` is the number of `MetaNebula_Create` calls in the file **beyond
  the first** (0 for every campaign region). The first nebula is the one
  returned; Task 4 reports a non-zero count as an ambiguity rather than guessing
  how to merge them.

**Ruling to implement, not to revisit:** the region keeps ONE nebula. A file with
several is reported, not merged and not modelled as a list. Only `Multi5` has
more than one, and it is not a region.

- [ ] **Step 1: Write the failing tests**

Add to `tests/tools/test_system_survey.py`:

```python
def test_nebula_captures_bcs_four_authored_numbers():
    """visibility and sensor density are MetaNebula_Create args 4 and 5;
    damage comes from the separate SetupDamage call."""
    text = (
        'pNebula = App.MetaNebula_Create(155.0 / 255.0, 90.0 / 255.0, '
        '185.0 / 255.0, 145.0, 10.5, "a.tga", "b.tga")\n'
        'pNebula.SetupDamage(150.0, 20.0)\n'
        'pNebula.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)\n'
    )
    neb = survey._nebula(text)
    assert neb["visibility_gu"] == pytest.approx(145.0)
    assert neb["sensor_density"] == pytest.approx(10.5)
    assert neb["damage_hull_per_s"] == pytest.approx(150.0)
    assert neb["damage_shield_per_s"] == pytest.approx(20.0)


def test_absent_setup_damage_is_a_real_zero():
    """Belaruz 1 never calls SetupDamage. That is BC saying 'this cloud does no
    damage', not BC leaving a value unspecified."""
    text = ('pNebula = App.MetaNebula_Create(100.0 / 255.0, 99.0 / 255.0, '
            '146.0 / 255.0, 200.0, 6.5, "a.tga", "b.tga")\n'
            'pNebula.AddNebulaSphere(-17.1, 844.7, -30.3, 900.0)\n')
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == 0.0
    assert neb["damage_shield_per_s"] == 0.0


def test_single_argument_setup_damage_leaves_the_shield_rate_unknown():
    """Multi6 calls SetupDamage(1.0). One argument means BC did not author a
    shield rate -- which is NOT the same as authoring zero."""
    text = ('pNebula = App.MetaNebula_Create(0.125, 0.125, 0.75, 75.0, 0.5, '
            '"a.tga", "b.tga")\n'
            'pNebula.SetupDamage(1.0)\n'
            'pNebula.AddNebulaSphere(50.0, 150.0, 150.0, 250.0)\n')
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == pytest.approx(1.0)
    assert neb["damage_shield_per_s"] is None


def test_spheres_belong_to_their_own_nebula():
    """THE BUG THIS TASK EXISTS FOR. Multi5 builds four MetaNebulae in one
    file. Collecting every AddNebulaSphere in the file gives the first nebula
    all thirteen spheres and a radius spanning the whole set."""
    text = (
        'pNebula = App.MetaNebula_Create(0.125, 0.75, 0.125, 143.0, 0.5, "a", "b")\n'
        'pNebula.AddNebulaSphere(200.0, 0.0, 0.0, 200.0)\n'
        'pNebula = App.MetaNebula_Create(0.75, 0.75, 0.125, 143.0, 0.5, "a", "b")\n'
        'pNebula.AddNebulaSphere(310.0, -125.0, -125.0, 150.0)\n'
        'pNebula.AddNebulaSphere(230.0, 125.0, 125.0, 150.0)\n'
    )
    neb = survey._nebula(text)
    assert len(neb["spheres"]) == 1
    assert neb["spheres"][0] == pytest.approx((200.0, 0.0, 0.0, 200.0))
    assert neb["extra_nebulae"] == 1


def test_damage_of_a_later_nebula_does_not_leak_onto_the_first():
    """Same scoping rule, applied to SetupDamage rather than spheres."""
    text = (
        'pNebula = App.MetaNebula_Create(0.1, 0.2, 0.3, 100.0, 1.0, "a", "b")\n'
        'pNebula.AddNebulaSphere(0.0, 0.0, 0.0, 50.0)\n'
        'pNebula = App.MetaNebula_Create(0.4, 0.5, 0.6, 100.0, 1.0, "a", "b")\n'
        'pNebula.SetupDamage(999.0, 999.0)\n'
    )
    neb = survey._nebula(text)
    assert neb["damage_hull_per_s"] == 0.0
```

Add the real-SDK cross-check, which is the one that proves the parser against
BC rather than against a fixture:

```python
def test_the_real_vesuvi_and_belaruz_scripts_parse_as_expected():
    """Guards the parser against the actual game files, not a hand-written
    approximation of them."""
    systems = survey.survey_all()
    vesuvi4 = next(r for r in _system(systems, "Vesuvi").regions
                   if r.set_name == "Vesuvi4")
    assert vesuvi4.nebula["damage_hull_per_s"] == pytest.approx(150.0)
    assert vesuvi4.nebula["damage_shield_per_s"] == pytest.approx(20.0)
    assert vesuvi4.nebula["visibility_gu"] == pytest.approx(145.0)
    assert vesuvi4.nebula["extra_nebulae"] == 0

    belaruz1 = next(r for r in _system(systems, "Belaruz").regions
                    if r.set_name == "Belaruz1")
    assert belaruz1.nebula["damage_hull_per_s"] == 0.0
    assert belaruz1.nebula["sensor_density"] == pytest.approx(6.5)
```

Follow the file's existing convention for reaching the SDK and for skipping when
it is absent — copy whatever `tests/tools/test_system_survey.py` already does;
do **not** invent a new path lookup, and do not write `sdk` as a path segment.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/tools/test_system_survey.py -v`
Expected: the five new unit tests fail on `KeyError` / wrong sphere count.

- [ ] **Step 3: Implement**

Replace `_nebula`'s body. `_META_NEBULA_CALL`, `_ADD_NEBULA_SPHERE`,
`_split_top_level` and `_eval_num` already exist and are unchanged.

```python
_SETUP_DAMAGE = re.compile(r'SetupDamage\((.*?)\)', re.DOTALL)


def _nebula(text: str):
    """This region's MetaNebula, if its static file builds one.

    BC's own parameter order, from the comment block the artists left in
    Vesuvi4_S.py: r, g, b, visibility distance, sensor density, internal
    texture, external texture. Damage is separate, via SetupDamage.

    A file may build SEVERAL MetaNebulae -- Multi5 builds four. Each owns only
    the AddNebulaSphere and SetupDamage calls that follow it, so the text is
    sliced at the create calls before anything is collected. Collecting across
    the whole file instead gave the first nebula every sphere in the set.
    Only the first is returned; `extra_nebulae` counts the rest so the caller
    can report them rather than silently drop them.
    """
    joined = "\n".join(_uncommented(text))
    creates = list(_META_NEBULA_CALL.finditer(joined))
    if not creates:
        return None

    first = creates[0]
    # Everything from the first create up to the next one (or end of file).
    end = creates[1].start() if len(creates) > 1 else len(joined)
    scope = joined[first.end():end]

    args = _split_top_level(first.group(1))
    color = tuple(_eval_num(a) for a in args[:3])
    visibility = _eval_num(args[3]) if len(args) > 3 else 0.0
    sensor_density = _eval_num(args[4]) if len(args) > 4 else 0.0

    hull, shield = 0.0, 0.0
    dm = _SETUP_DAMAGE.search(scope)
    if dm:
        parts = _split_top_level(dm.group(1))
        hull = _eval_num(parts[0]) if parts and parts[0] else 0.0
        # One argument means BC authored no shield rate. That is unknown, not
        # zero -- absent SetupDamage is the case that means zero.
        shield = _eval_num(parts[1]) if len(parts) > 1 else None

    spheres = []
    for sm in _ADD_NEBULA_SPHERE.finditer(scope):
        parts = _split_top_level(sm.group(1))
        if len(parts) != 4:
            continue
        spheres.append(tuple(_eval_num(p) for p in parts))

    return {
        "color": color,
        "spheres": spheres,
        "visibility_gu": visibility,
        "sensor_density": sensor_density,
        "damage_hull_per_s": hull,
        "damage_shield_per_s": shield,
        "extra_nebulae": len(creates) - 1,
    }
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/tools/test_system_survey.py -v` — all pass.

- [ ] **Step 5: Prove the scoping fix is load-bearing**

Back up, mutate, watch it fail, restore, prove the restore:

```bash
cp tools/systems/survey.py /tmp/survey_bak.py
# Edit _nebula: change `scope` back to `joined` on the sphere loop only.
uv run pytest tests/tools/test_system_survey.py -v   # MUST fail on sphere scoping
cp /tmp/survey_bak.py tools/systems/survey.py
diff tools/systems/survey.py /tmp/survey_bak.py      # MUST be empty
```

Report which tests failed. If the suite stays green with the mutation in place,
the test is not guarding the fix — fix the test, not the mutation.

- [ ] **Step 6: Commit**

```bash
git add tools/systems/survey.py tests/tools/test_system_survey.py
git commit -m "fix(systems): scope nebula spheres to their own MetaNebula, and read BC's four params"
```

---

### Task 2: `Volume` and `Cloud` in the map format

**Files:**
- Modify: `engine/systems/map.py`
- Test: `tests/unit/test_system_map.py`

**Interfaces:**

- Consumes: nothing from Task 1 (the survey dict shape is a tools-side concern).
- Produces:

```python
@dataclass
class Volume:
    shape: str                      # "sphere" | "lobe"
    geometry: dict = field(default_factory=dict)
    profile: str = ""               # "debris" | "nebula" | "mist"
    params: dict = field(default_factory=dict)
    origin_region: str | None = None


@dataclass
class Cloud:
    name: str
    display_name: str
    kind: str                       # "debris_shell" | "nebula_field"
    color: tuple = (0.0, 0.0, 0.0)
    volumes: list = field(default_factory=list)
    regions: list = field(default_factory=list)
```

  and `SystemMap.clouds: list = field(default_factory=list)`, plus
  `SystemMap.cloud(name)` mirroring the existing `body()` / `region()` lookups
  (return the match or `None`).

- `from_json` tolerates a map with **no** `clouds` key and yields `clouds == []`.
  Thirty of the thirty-two checked-in maps have no clouds and must keep loading
  without regeneration.
- `to_json` already uses `asdict`, so `clouds` serialises with no change — but
  tuples round-trip as lists, so `_cloud_from_json` must re-tuple `color` the
  way `_appearance_from_json` re-tuples its own.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_map_with_no_clouds_key_still_loads():
    """Thirty checked-in maps predate clouds. They must not need regenerating
    to stay readable."""
    text = json.dumps({"system": "Ona", "bodies": [], "regions": []})
    assert map.from_json(text).clouds == []


def test_clouds_round_trip_through_json():
    m = map.SystemMap(system="Vesuvi", clouds=[map.Cloud(
        name="Vesuvi Debris", display_name="Vesuvi Debris Field",
        kind="debris_shell", color=(0.6, 0.35, 0.72),
        volumes=[map.Volume(shape="sphere",
                            geometry={"center_gu": [0.0, 0.0, 0.0],
                                      "radius_gu": 61567.0},
                            profile="mist",
                            params={"visibility_gu": 0.0})],
        regions=["Vesuvi1", "Vesuvi4"])])
    back = map.from_json(map.to_json(m))
    assert back.clouds[0].kind == "debris_shell"
    assert back.clouds[0].color == (0.6, 0.35, 0.72)      # tuple, not list
    assert back.clouds[0].volumes[0].geometry["radius_gu"] == 61567.0
    assert back.clouds[0].volumes[0].origin_region is None


def test_cloud_lookup_by_name():
    m = map.SystemMap(system="Vesuvi", clouds=[
        map.Cloud(name="Vesuvi Debris", display_name="d", kind="debris_shell")])
    assert m.cloud("Vesuvi Debris").kind == "debris_shell"
    assert m.cloud("nope") is None
```

- [ ] **Step 2: Run them and confirm they fail** —
`uv run pytest tests/unit/test_system_map.py -v`

- [ ] **Step 3: Implement** per the Interfaces block. Add `_volume_from_json`
and `_cloud_from_json` beside the existing `_appearance_from_json` /
`_nebula_from_json` helpers, and wire `clouds=[...]` into `from_json`'s
`SystemMap(...)` construction.

- [ ] **Step 4: Run the tests and confirm they pass**, then
`uv run pytest tests/unit/test_system_map.py tests/unit/test_system_maps_valid.py -v`
to confirm all 32 existing maps still load.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/map.py tests/unit/test_system_map.py
git commit -m "feat(systems): Cloud and Volume in the system-map format"
```

---

### Task 3: The three profiles, and a test that proves two of them are BC's

**Why.** The spec's whole claim is that `debris` and `nebula` carry BC's
authored numbers verbatim. A constant in our tree is not evidence of that. The
cross-check test is what turns the claim into a fact, and what stops the numbers
being quietly tuned later.

**Files:**
- Create: `engine/systems/clouds.py`
- Test: `tests/unit/test_cloud_profiles.py` (shape), `tests/tools/test_system_survey.py` (cross-check)

**Interfaces:**

- Produces: `engine.systems.clouds.PROFILES` — a dict of profile name to params
  dict — and `params_for(profile: str) -> dict`, returning a **copy** so callers
  cannot mutate the table.
- Params keys, in this order: `visibility_gu`, `sensor_density`,
  `damage_hull_per_s`, `damage_shield_per_s`.
- `mist` ships with all four at `0.0` and a comment saying the numbers are
  deferred and must be survivable at sustained exposure. A zeroed `mist` volume
  renders and does nothing, which is exactly the behaviour this plan commits to.
- Pure data. No file I/O, no path lookups, no imports from `tools/`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_cloud_profiles.py`:

```python
def test_bc_profile_numbers():
    assert clouds.params_for("debris") == {
        "visibility_gu": 145.0, "sensor_density": 10.5,
        "damage_hull_per_s": 150.0, "damage_shield_per_s": 20.0}
    assert clouds.params_for("nebula") == {
        "visibility_gu": 200.0, "sensor_density": 6.5,
        "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def test_mist_is_declared_and_inert():
    """Named in the design, numbers deferred. Zeroed means it renders and does
    nothing, which is the behaviour this change ships."""
    assert clouds.params_for("mist") == {
        "visibility_gu": 0.0, "sensor_density": 0.0,
        "damage_hull_per_s": 0.0, "damage_shield_per_s": 0.0}


def test_params_for_returns_a_copy():
    clouds.params_for("debris")["damage_hull_per_s"] = 1.0
    assert clouds.params_for("debris")["damage_hull_per_s"] == 150.0


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        clouds.params_for("fog")
```

`tests/tools/test_system_survey.py` — the cross-check:

```python
def test_the_bc_profiles_match_what_the_sdk_actually_says():
    """engine/systems/clouds.py claims debris and nebula are BC's numbers,
    verbatim. This is the only test that can prove it: it reads the real game
    scripts and compares. If it fails, either someone tuned a constant that is
    not ours to tune, or the survey parser drifted."""
    systems = survey.survey_all()
    vesuvi4 = next(r for r in _system(systems, "Vesuvi").regions
                   if r.set_name == "Vesuvi4")
    belaruz1 = next(r for r in _system(systems, "Belaruz").regions
                    if r.set_name == "Belaruz1")
    for region, profile in ((vesuvi4, "debris"), (belaruz1, "nebula")):
        expected = clouds.params_for(profile)
        for key in expected:
            assert region.nebula[key] == pytest.approx(expected[key]), \
                f"{profile}.{key} does not match {region.set_name}"
```

- [ ] **Step 2: Run them and confirm they fail** (module does not exist).

- [ ] **Step 3: Implement** `engine/systems/clouds.py` per the Interfaces block.
Document each profile's source in a comment — which set it came from, and that
`nebula`'s zeroes are an absent `SetupDamage`, not a chosen value.

- [ ] **Step 4: Run both test files and confirm they pass.**

- [ ] **Step 5: Prove the cross-check bites**

```bash
cp engine/systems/clouds.py /tmp/clouds_bak.py
# Edit: change debris damage_hull_per_s from 150.0 to 151.0
uv run pytest tests/tools/test_system_survey.py -v   # MUST fail, naming debris.damage_hull_per_s
cp /tmp/clouds_bak.py engine/systems/clouds.py
diff engine/systems/clouds.py /tmp/clouds_bak.py     # MUST be empty
```

- [ ] **Step 6: Commit**

```bash
git add engine/systems/clouds.py tests/unit/test_cloud_profiles.py \
        tests/tools/test_system_survey.py
git commit -m "feat(systems): three cloud profiles, two of them checked against the SDK"
```

---

### Task 4: `layout()` builds the clouds

**Files:**
- Modify: `tools/systems/layout.py`
- Test: `tests/tools/test_system_layout.py`

**Interfaces:**

- Consumes: `Cloud` / `Volume` (Task 2), `clouds.params_for` (Task 3), the
  enriched `SurveyedRegion.nebula` (Task 1).
- Produces: `layout(s, tuning=None, pins=None, star=None, cloud=None)`.
  `cloud` is the `overrides.cloud` dict or `None`; it is the fifth keyword and
  every existing call site keeps working unchanged.
- Also produces: `ambiguities(s, tuning=None)` gains a row when a region's
  `nebula["extra_nebulae"] > 0`.

**The override's shape:**

```json
"cloud": {
  "name": "Vesuvi Debris Field",
  "display_name": "Vesuvi Debris Field",
  "kind": "debris_shell",
  "why": "..."
}
```

and for a lobe, additionally:

```json
"geometry": { "near_gu": 20000.0, "far_gu": 220000.0, "radius_gu": 160000.0 }
```

`why` is documentation and is never read by code.

**Construction rules — implement exactly these:**

1. A cloud is built only when at least one region carries a `nebula`. No nebula,
   no cloud, and `m.clouds` stays empty. This is the case for 30 of 32 systems.
2. **The pocket volume, per nebula-carrying region.** For each sphere in
   `region.nebula["spheres"]`, emit a `Volume` with `shape="sphere"`,
   `geometry={"center_gu": anchor + sphere_xyz, "radius_gu": sphere_r}`,
   `origin_region=region.set_name`, and the profile chosen by BC's own damage:
   `"debris"` when `damage_hull_per_s > 0`, else `"nebula"`. Params come from
   `clouds.params_for(profile)` — never from the survey dict, so the validator
   in Task 5 compares two independent sources rather than a value against
   itself.
3. **The large volume**, one per cloud, `profile="mist"`, params from
   `clouds.params_for("mist")` (all zero), `origin_region=None`:
   - `kind == "debris_shell"` → `shape="sphere"`,
     `geometry={"center_gu": [0,0,0], "radius_gu": R}` where **R is derived**:
     the greatest `|anchor| + region.radius_gu` across the cloud's member
     regions. Nothing declared.
   - `kind == "nebula_field"` → `shape="lobe"`, geometry is the override's
     `geometry` block **plus** an `axis` that is **derived**: the unit vector
     from the origin to the first pocket volume's centre.
4. `Cloud.color` is BC's `nebula["color"]` from the first member region,
   verbatim. `Cloud.regions` lists the member set names in placement order.
5. **No override ⇒ pocket volumes only.** A cloud with nebulae but no declared
   `kind` still exists and still carries its pockets; it simply has no large
   volume. Degrading to "no cloud at all" would silently lose BC's data.

**Ruling to implement, not to revisit:** the profile is chosen from BC's authored
damage, not declared in the override. There are two clouds, they differ on
exactly this axis, and deriving it means the data cannot disagree with BC.

- [ ] **Step 1: Write the failing tests**

```python
def _nebula_region(set_name="Vesuvi4", hull=150.0, shield=20.0,
                   vis=145.0, dens=10.5, spheres=((0.0, 1500.0, 0.0, 1500.0),)):
    return SurveyedRegion(
        set_name=set_name, ordinal=4, bodies=[], content_extent_gu=2067.0,
        player_start_gu=(0.0, 0.0, 0.0),
        nebula={"color": (0.61, 0.35, 0.73), "spheres": list(spheres),
                "visibility_gu": vis, "sensor_density": dens,
                "damage_hull_per_s": hull, "damage_shield_per_s": shield,
                "extra_nebulae": 0})


def test_no_nebula_anywhere_means_no_cloud():
    m = layout(SurveyedSystem(name="Ona", regions=[SurveyedRegion(
        set_name="Ona1", ordinal=1,
        bodies=[SurveyedBody("Ona 1", 120.0, "p.nif", (0.0, 500.0, 0.0), False)],
        content_extent_gu=0.0, player_start_gu=(0.0, 0.0, 0.0))]))
    assert m.clouds == []


def test_the_pocket_volume_sits_at_anchor_plus_bcs_offset():
    """The pinned volume. Its centre is the region's anchor plus BC's own
    set-local sphere -- that transform is the entire reason a system-scale
    cloud can exist without a second source of truth."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    anchor = m.region("Vesuvi4").anchor_gu
    pocket = [v for v in m.clouds[0].volumes if v.origin_region == "Vesuvi4"][0]
    assert pocket.geometry["center_gu"] == pytest.approx(
        (anchor[0] + 0.0, anchor[1] + 1500.0, anchor[2] + 0.0))
    assert pocket.geometry["radius_gu"] == pytest.approx(1500.0)


def test_the_profile_comes_from_bcs_damage_not_from_the_override():
    s_hot = SurveyedSystem(name="Vesuvi", regions=[_nebula_region(hull=150.0)])
    s_cold = SurveyedSystem(name="Belaruz", regions=[
        _nebula_region(set_name="Belaruz1", hull=0.0, shield=0.0,
                       vis=200.0, dens=6.5)])
    hot = layout(s_hot, cloud={"name": "V", "display_name": "V",
                               "kind": "debris_shell"})
    cold = layout(s_cold, cloud={"name": "B", "display_name": "B",
                                 "kind": "nebula_field",
                                 "geometry": {"near_gu": 1.0, "far_gu": 2.0,
                                              "radius_gu": 3.0}})
    assert [v.profile for v in hot.clouds[0].volumes
            if v.origin_region][0] == "debris"
    assert [v.profile for v in cold.clouds[0].volumes
            if v.origin_region][0] == "nebula"


def test_the_shell_radius_is_derived_from_its_member_regions():
    """Not declared. The shell reaches exactly as far as the debris does."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    region = m.region("Vesuvi4")
    expected = _norm(region.anchor_gu) + region.radius_gu
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    assert shell.shape == "sphere"
    assert shell.geometry["radius_gu"] == pytest.approx(expected)
    assert shell.geometry["center_gu"] == pytest.approx((0.0, 0.0, 0.0))


def test_the_large_volume_is_inert_until_mist_is_tuned():
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s, cloud={"name": "V", "display_name": "V", "kind": "debris_shell"})
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    assert shell.profile == "mist"
    assert all(value == 0.0 for value in shell.params.values())


def test_the_lobe_axis_points_at_bcs_pocket():
    s = SurveyedSystem(name="Belaruz", regions=[
        _nebula_region(set_name="Belaruz1", hull=0.0, shield=0.0)])
    m = layout(s, cloud={"name": "B", "display_name": "B", "kind": "nebula_field",
                         "geometry": {"near_gu": 20000.0, "far_gu": 220000.0,
                                      "radius_gu": 160000.0}})
    lobe = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    pocket = [v for v in m.clouds[0].volumes if v.origin_region][0]
    assert lobe.shape == "lobe"
    assert lobe.geometry["far_gu"] == pytest.approx(220000.0)
    centre = pocket.geometry["center_gu"]
    expected_axis = [c / _norm(centre) for c in centre]
    assert lobe.geometry["axis"] == pytest.approx(expected_axis)


def test_a_cloud_without_an_override_keeps_its_pockets():
    """Losing BC's authored data because nobody declared a kind would be the
    worst possible failure mode here."""
    s = SurveyedSystem(name="Vesuvi", regions=[_nebula_region()])
    m = layout(s)
    assert len(m.clouds) == 1
    assert [v.origin_region for v in m.clouds[0].volumes] == ["Vesuvi4"]
    assert all(v.origin_region for v in m.clouds[0].volumes)


def test_a_set_with_several_nebulae_is_reported_as_ambiguous():
    s = SurveyedSystem(name="Multi5", regions=[_nebula_region()])
    s.regions[0].nebula["extra_nebulae"] = 3
    assert any("nebula" in a.lower() for a in ambiguities(s))
```

- [ ] **Step 2: Run them and confirm they fail** —
`uv run pytest tests/tools/test_system_layout.py -v`

- [ ] **Step 3: Implement** per the construction rules. Build clouds in `_place`
**after** the region loop, so anchors are final. `_first_orbit_push()` calls
`_place` twice — confirm the second call's clouds are the ones kept, and that
the shell radius reflects the pushed anchors, not the pre-push ones.

- [ ] **Step 4: Run the tests and confirm they pass**, then the whole
`tests/tools/` directory to confirm nothing else moved.

- [ ] **Step 5: Prove the anchor transform is guarded**

```bash
cp tools/systems/layout.py /tmp/layout_bak.py
# Edit: drop the anchor from the pocket centre (use BC's set-local offset raw)
uv run pytest tests/tools/test_system_layout.py -v   # MUST fail
cp /tmp/layout_bak.py tools/systems/layout.py
diff tools/systems/layout.py /tmp/layout_bak.py      # MUST be empty
```

- [ ] **Step 6: Commit**

```bash
git add tools/systems/layout.py tests/tools/test_system_layout.py
git commit -m "feat(systems): layout builds clouds from BC's nebulae plus a declared kind"
```

---

### Task 5: Four validation rules

**Files:**
- Modify: `engine/systems/validate.py`
- Test: `tests/unit/test_system_map_validate.py`

**Interfaces:**

- Consumes: `Cloud`, `Volume` (Task 2), `clouds.PROFILES` (Task 3).
- `validate(m, *, sdk_set_names=None, pins=None)` — signature unchanged.
- Rules, by name:
  - `cloud-volume-agrees-with-region` — every volume with an `origin_region`
    must sit at `region.anchor_gu + region.nebula["spheres"][i]` (match by
    radius, within 1e-6 relative). This is the anti-drift guard.
  - `cloud-region-membership` — every name in `Cloud.regions` names a region in
    the map, and every region carrying a `nebula` is listed by exactly one cloud.
  - `cloud-pocket-inside-cloud` — every `origin_region` volume lies inside the
    cloud's largest volume. Skipped when the cloud has no large volume.
  - `cloud-profile-matches-params` — a volume's `params` equals
    `clouds.params_for(volume.profile)`. An unknown profile is itself a problem
    under this rule, not a `KeyError`.
- **`validate()` still never raises.** Every new rule must survive a cloud with
  a missing key, a non-numeric radius, a `geometry` that is not a dict, and a
  `volumes` list containing `None`. Reuse `_is_point3` and guard before
  arithmetic, exactly as `malformed-geometry` does for bodies.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pocket_that_drifted_from_its_region_is_caught():
    m = _cloud_map()
    m.clouds[0].volumes[0].geometry["center_gu"] = (1.0, 2.0, 3.0)
    assert "cloud-volume-agrees-with-region" in _rules(validate(m))


def test_a_cloud_naming_a_region_that_does_not_exist_is_caught():
    m = _cloud_map()
    m.clouds[0].regions = ["Nowhere1"]
    assert "cloud-region-membership" in _rules(validate(m))


def test_a_region_with_a_nebula_and_no_cloud_is_caught():
    """The failure this rule exists for: a cloud silently dropped during
    regeneration, leaving BC's nebula stranded on the region."""
    m = _cloud_map()
    m.clouds = []
    assert "cloud-region-membership" in _rules(validate(m))


def test_a_pocket_outside_its_own_shell_is_caught():
    m = _cloud_map()
    shell = [v for v in m.clouds[0].volumes if v.origin_region is None][0]
    shell.geometry["radius_gu"] = 1.0
    assert "cloud-pocket-inside-cloud" in _rules(validate(m))


def test_tuned_bc_params_are_caught():
    """BC's numbers are not ours to change."""
    m = _cloud_map()
    pocket = [v for v in m.clouds[0].volumes if v.origin_region][0]
    pocket.params["damage_hull_per_s"] = 5.0
    assert "cloud-profile-matches-params" in _rules(validate(m))


def test_an_unknown_profile_is_a_problem_not_a_crash():
    m = _cloud_map()
    m.clouds[0].volumes[0].profile = "fog"
    assert "cloud-profile-matches-params" in _rules(validate(m))


@pytest.mark.parametrize("wreck", [
    lambda c: setattr(c.volumes[0], "geometry", None),
    lambda c: c.volumes[0].geometry.__setitem__("center_gu", (1.0, 2.0)),
    lambda c: c.volumes[0].geometry.__setitem__("radius_gu", "big"),
    lambda c: setattr(c, "volumes", [None]),
    lambda c: setattr(c, "regions", None),
])
def test_a_malformed_cloud_is_reported_never_raised(wreck):
    """validate()'s contract. Callers are a CLI printing every problem and a
    test naming every problem; a traceback serves neither."""
    m = _cloud_map()
    wreck(m.clouds[0])
    problems = validate(m)          # must not raise
    assert any(p.rule.startswith("cloud-") or p.rule == "malformed-geometry"
               for p in problems)


def test_the_real_maps_validate_clean():
    for name in available():
        assert validate(load(name)) == [], name
```

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement.** Add the rules after the existing body/region rules.
Guard every value before arithmetic.

- [ ] **Step 4: Run the tests and confirm they pass**, plus
`uv run pytest tests/unit/test_system_map_validate.py tests/unit/test_system_maps_valid.py -v`.

- [ ] **Step 5: Commit**

```bash
git add engine/systems/validate.py tests/unit/test_system_map_validate.py
git commit -m "feat(systems): four cloud validation rules"
```

---

### Task 6: Wire the generator, author the two overrides, regenerate

**Files:**
- Modify: `tools/gen_system_maps.py`
- Modify: `engine/systems/maps/belaruz.json`, `engine/systems/maps/vesuvi.json`
- Test: `tests/unit/test_system_maps_valid.py`

**Interfaces:**

- Consumes: `layout(..., cloud=...)` (Task 4).
- Produces: `cloud_from(m)` — returns `m.overrides["cloud"]` or `None`, exactly
  mirroring `star_from(m)`, including the `m is None` guard.
- `generate()` passes `cloud=cloud_from(old) if old is not None else None`.
- `_merge_overrides` already carries the whole overrides block forward, so the
  hand-authored `cloud` block survives regeneration with no change there.

- [ ] **Step 1: Write the failing test**

```python
def test_the_two_cloud_systems_carry_their_clouds():
    vesuvi = load("vesuvi")
    assert len(vesuvi.clouds) == 1
    cloud = vesuvi.clouds[0]
    assert cloud.kind == "debris_shell"
    assert sorted(cloud.regions) == ["Vesuvi4"]
    pocket = [v for v in cloud.volumes if v.origin_region == "Vesuvi4"][0]
    assert pocket.profile == "debris"
    assert pocket.params["damage_hull_per_s"] == pytest.approx(150.0)
    shell = [v for v in cloud.volumes if v.origin_region is None][0]
    assert shell.shape == "sphere"
    assert shell.geometry["radius_gu"] == pytest.approx(61567.4, rel=1e-3)

    belaruz = load("belaruz")
    cloud = belaruz.clouds[0]
    assert cloud.kind == "nebula_field"
    pocket = [v for v in cloud.volumes if v.origin_region == "Belaruz1"][0]
    assert pocket.profile == "nebula"
    assert pocket.params["damage_hull_per_s"] == 0.0
    assert [v for v in cloud.volumes if v.origin_region is None][0].shape == "lobe"


def test_no_other_system_grew_a_cloud():
    for name in available():
        if name in ("vesuvi", "belaruz"):
            continue
        assert load(name).clouds == [], name
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Implement `cloud_from`** and wire it into `generate()`.

- [ ] **Step 4: Author the two overrides by hand**

Add a `cloud` key beside the existing `star` and `notes` entries in each map's
`overrides` block — **do not disturb those**.

`engine/systems/maps/vesuvi.json`:

```json
"cloud": {
  "name": "Vesuvi Debris Field",
  "display_name": "Vesuvi Debris Field",
  "kind": "debris_shell",
  "why": "A star destabilised from within threw its material out in every direction, so the wreckage is a shell rather than a disc. The radius is derived from the outermost region that carries debris; nothing here is declared but the shape."
}
```

`engine/systems/maps/belaruz.json`:

```json
"cloud": {
  "name": "Kacheeti Nebula",
  "display_name": "Kacheeti Nebula",
  "kind": "nebula_field",
  "geometry": { "near_gu": 20000.0, "far_gu": 220000.0, "radius_gu": 160000.0 },
  "why": "Belaruz is crossing a body of dust rather than having shed one, so the shape is directional, not centred on the star. The axis is derived from BC's authored pocket; near/far/radius are asserted -- sized to reach past Belaruz 4 at 121,181 GU so the outer system sits in thin material, as the system description claims. Retune freely."
}
```

BC names the waypoint in `Belaruz1.py` `Kacheeti Nebula`; use BC's name.

- [ ] **Step 5: Regenerate and verify**

```bash
uv run python tools/gen_system_maps.py --system Belaruz --system Vesuvi --list-ambiguities
uv run python -c "
from engine.systems.descriptions import available
from engine.systems.map import from_json
import json, pathlib
for n in ('vesuvi', 'belaruz'):
    m = from_json(pathlib.Path(f'engine/systems/maps/{n}.json').read_text())
    c = m.clouds[0]
    print(n, c.kind, c.regions, [(v.shape, v.profile, v.origin_region) for v in c.volumes])
"
```

Report the shell radius and the lobe axis.

- [ ] **Step 6: Confirm nothing else moved**

```bash
uv run python tools/gen_system_maps.py --check --list-ambiguities
git status --porcelain engine/systems/maps
```

Expected: all 32 `ok`, exit 0; the same seven clamped regions (Alioth6, Beol1,
Savoy2 min; Geble4, OmegaDraconis1, Savoy1, XiEntrades4 max); no region reaches
its star; and **only** `belaruz.json` and `vesuvi.json` modified.

- [ ] **Step 7: Commit**

```bash
git add tools/gen_system_maps.py engine/systems/maps/belaruz.json \
        engine/systems/maps/vesuvi.json tests/unit/test_system_maps_valid.py
git commit -m "feat(systems): generate Vesuvi's debris shell and Belaruz's nebula lobe"
```

---

### Task 7: Correct the Vesuvi description's phantom station

**Why.** `descriptions.json` says "The Federation survey station at Vesuvi IV
sits inside that cloud." There is no station in Vesuvi 4 — `Vesuvi4_S.py`
builds a nebula and twelve asteroids and nothing else. The Vesuvi outposts are
`GekiStation` in `Vesuvi5_S.py` (created and immediately damaged to 20 % hull)
and `Facility` in `Vesuvi6_S.py`. Player-facing text contradicting the data is
the drift this branch exists to stop.

**Files:**
- Modify: `engine/systems/descriptions.json` (the `vesuvi` entry's `detail`)
- Test: `tests/unit/test_system_descriptions.py`

**Ruling to implement, not to revisit:** only the station sentence changes. The
Belaruz entry's "out past the first planet" is a second known contradiction and
is **deliberately left alone** — it depends on approving the lobe's shape, which
is still open. Do not touch the `belaruz` entry.

- [ ] **Step 1: Write the failing test**

```python
def test_vesuvi_does_not_claim_a_station_it_does_not_have():
    """Vesuvi 4 holds a nebula and twelve asteroids. The outposts are at Geki
    (Vesuvi 5, authored at 20% hull) and Vesuvi 6."""
    detail = for_system("vesuvi")["detail"]
    assert "Vesuvi IV" not in detail
    assert "Geki" in detail
```

- [ ] **Step 2: Run it and confirm it fails.**

- [ ] **Step 3: Rewrite the sentence.** Replace

> The Federation survey station at Vesuvi IV sits inside that cloud -- still the
> only Starfleet outpost in the Maelstrom, still studying the thing that killed
> the star it was sent to watch.

with

> The Federation station at Geki took the event badly and still carries the
> damage -- it remains the Starfleet presence here, studying the thing that
> killed the star it was sent to watch.

Keep the rest of the entry, including the closing hazard warning, unchanged.

- [ ] **Step 4: Run the tests and confirm they pass** —
`uv run pytest tests/unit/test_system_descriptions.py -v`

- [ ] **Step 5: Gate** — `scripts/check_tests.sh`. Expect
`OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 6: Commit**

```bash
git add engine/systems/descriptions.json tests/unit/test_system_descriptions.py
git commit -m "fix(nav): Vesuvi's outpost is at Geki, not Vesuvi IV"
```

---

## Self-review

**Spec coverage.** `Cloud`/`Volume` → Task 2. Three profiles and the
"BC's numbers are never tuned" claim → Task 3. Envelope-plus-pockets
construction, the derived shell radius, and the derived lobe axis → Task 4. All
four named validation rules → Task 5. The two authored overrides and
regeneration → Task 6. Contradiction 1 → Task 7. **Deliberately not covered:**
`mist`'s numbers (spec defers them), seeding the shell with asteroids (spec
defers), contradiction 2 (depends on the open lobe question), and the empty
`multi*.json` maps (out of scope, flagged above).

**Type consistency.** `params` keys are the same four strings in the survey dict
(Task 1), `clouds.PROFILES` (Task 3), the `Volume.params` dict (Task 2), and the
validator (Task 5). `origin_region` is the discriminator between pocket and
large volume in Tasks 4, 5 and 6 — `None` means large, everywhere. `cloud_from`
mirrors `star_from` exactly, including the `m is None` guard.

**One deliberate redundancy.** Task 4 rule 2 takes params from
`clouds.params_for(profile)` rather than from the survey dict, even though the
survey now carries the same numbers. That is what lets Task 3's cross-check
catch a parser drift that would otherwise be invisible.

**Correction (final fix wave).** This paragraph originally also claimed the
redundancy is "what lets Task 5's `cloud-profile-matches-params` compare two
independent sources instead of a value against itself". That had the
relationship exactly backwards. Taking a pocket's params from
`clouds.params_for(profile)` and then validating them *against that same
table* is the tautology, not the cure: the rule as first written could never
fail for a generated map. The independent source for a pocket is its own
region's `Region.nebula` — BC's authored numbers from the survey — and that is
what the rule compares against now. The table comparison survives only for the
large volume, which has no region. See the design note's
`cloud-profile-matches-params` bullet.
