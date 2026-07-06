# Power Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `engpower` CEF panel to the locked v28 design (design-system chrome, row-is-slider, used/available bar pair with spanning damage column, battery glyphs, conditional tractor/cloak siphons).

**Architecture:** Python `EngineeringPowerPanel` computes ALL data (new payload schema per the spec's formula table); JS renders the v28 mockup verbatim and adds custom drag handling on the slider rows. Zero engine/appc changes.

**Tech Stack:** Python (engine/ui panel + tests), vanilla JS/CSS (runtime-loaded, no build), locked mockup `docs/ui_designs/06-engineer-panel-v2.html` as the visual source of truth.

**Spec:** `docs/superpowers/specs/2026-07-06-power-panel-redesign-design.md`
**Branch:** `feat/power-management` (continue on it).

## Global Constraints

- Shared denominator `D = authored_output + main_conduit_cap + backup_conduit_cap` (RAW property values via `power.GetProperty()`; health/charge scaling only where the spec's table says).
- USED excludes tractor/cloak (SDK `PowerDisplay.Update` demand math); clamps at the available extent with the damage-red overload tint.
- Track pre-scaling: slider fill `width = pct/1.25`; the 100 % hairline sits at 80 % of the track.
- Conditional presence: tractor row+line only when `GetTractorBeamSystem()` non-null AND `GetNumWeapons() > 0`; cloak row+line only when `GetCloakingSubsystem()` non-null.
- Visual values (colours, sizes, radii, tick geometry) are copied VERBATIM from `docs/ui_designs/06-engineer-panel-v2.html` — divergence is a fidelity bug.
- Panel stays menu-gated + hit-region-gated via the existing `is_showing()`; drag-safe rules (build-once DOM, no updates mid-drag) retained.
- After host_loop/panel edits: `uv run pytest tests/host tests/unit -q` green; JS/CSS have no automated tests (payload contract is the tested seam).
- Suite ripple rule: payload keys change — update existing engpower tests in the same commit; never orphan.

---

### Task 1: Payload v2 — the spec's formula table in `_snapshot`

**Files:**
- Modify: `engine/ui/engineering_power_panel.py` (lines ~75–120 `_snapshot`; `__init__`)
- Test: `tests/unit/test_engineering_power_panel.py` (rewrite payload-shape tests; keep dispatch/gating tests)

**Interfaces:**
- Consumes: `power.GetProperty()` data-bag getters (`GetPowerOutput/GetMainConduitCapacity/GetBackupConduitCapacity` — RAW authored values), `power.GetPowerOutput()` (health-scaled), `GetMainBatteryPower()/GetMainBatteryLimit()` (+backup), group systems' `GetNormalPowerWanted()×GetPowerPercentageWanted()`, `tractor._wants_power()`, `cloak.IsTryingToCloak()`.
- Produces the payload consumed by Task 3's JS, exactly:

```python
{
  "visible": True,
  "sliders": [ {"key": "weapons", "label": "Weapons", "pct": 1.15, "present": True}, ...4 groups, label "Shields" for the shield group ],
  "grid": {
    "damage": 0.083,                    # (authored_out - live_out) / D
    "available": {"warp_core": 0.29, "main": 0.33, "reserve": 0.083},   # /D each
    "used": [ {"key": "weapons", "frac": 0.22}, {"key": "engines", ...}, {"key": "sensors", ...}, {"key": "shields", ...} ],   # /D each
    "overload": False                   # True when raw used total exceeded available total (used already clamped)
  },
  "batteries": {
    "main":    {"charge": 0.65, "draining": True},
    "reserve": {"charge": 1.0,  "draining": False}
  },
  "tractor": {"present": True, "active": True},
  "cloak":   {"present": False, "active": False}
}
```

Notes for the implementer:
- All fractions rounded to 4 dp (diff stability, existing convention).
- `available.main = main_conduit_raw × (main_battery/limit) / D`; reserve likewise; `warp_core = live_output / D`.
- `used[i].frac = Σ(normal × pct) / D` per group; if the sum of used fracs exceeds `damage-excluded available total` (`sum(available.values())`), scale ALL used fracs by `available_total/used_total` and set `overload: True`.
- `draining`: track battery trend across snapshots — store `self._batt_prev = {"main": value, "reserve": value}` and `self._batt_dir = {...}`; when the new value differs from prev, set dir = (new < prev), update prev. `draining = dir`. (Batteries only change at power-interval fire; direction persists between changes.)
- `tractor.present = tractor is not None and tractor.GetNumWeapons() > 0`; `cloak.present = cloak is not None`. Drop the old `power_used`/`columns` keys entirely.
- Keep `visible` gating (menu + player + power) untouched.

- [ ] **Step 1: Rewrite the payload tests (failing first)**

Replace `test_payload_shape_and_diffing` and the tractor/cloak payload tests in `tests/unit/test_engineering_power_panel.py` with tests against the v2 schema. Extend the existing `_fake_player()` fixture (keep its construction style) so the power property carries authored values output 1000 / conduits 1200 & 200 / limits 250000 & 80000, and set condition + battery levels per case:

```python
def _payload(panel):
    js = panel.render_payload()
    assert js.startswith("setEngineeringPower(")
    return json.loads(js[len("setEngineeringPower("):-2])


def test_grid_fractions_healthy_full_batteries():
    panel = _panel()                     # helper: _fake_player + is_engineering_open=lambda: True
    p = _payload(panel)
    D = 1000.0 + 1200.0 + 200.0
    assert p["grid"]["damage"] == 0.0
    assert abs(p["grid"]["available"]["warp_core"] - round(1000.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["main"] - round(1200.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["reserve"] - round(200.0 / D, 4)) < 1e-9
    assert [u["key"] for u in p["grid"]["used"]] == ["weapons", "engines", "sensors", "shields"]
    assert p["grid"]["overload"] is False


def test_damage_column_from_core_condition():
    panel, power = _panel_with_power()
    power.SetCondition(power.GetMaxCondition() * 0.5)     # 50% health
    p = _payload(panel)
    D = 2400.0
    assert abs(p["grid"]["damage"] - round(500.0 / D, 4)) < 1e-9
    assert abs(p["grid"]["available"]["warp_core"] - round(500.0 / D, 4)) < 1e-9


def test_available_battery_segments_shrink_with_charge():
    panel, power = _panel_with_power()
    power.SetMainBatteryPower(125000.0)                   # 50% charge
    p = _payload(panel)
    assert abs(p["grid"]["available"]["main"] - round(1200.0 * 0.5 / 2400.0, 4)) < 1e-9


def test_used_overload_clamps_and_flags():
    panel, player = _panel_with_player()
    for key, _label, getters in _GROUPS:                  # crank demand way past supply
        for s in _systems(player, getters):
            s.SetNormalPowerPerSecond(5000.0)
    p = _payload(panel)
    used_total = sum(u["frac"] for u in p["grid"]["used"])
    avail_total = sum(p["grid"]["available"].values())
    assert p["grid"]["overload"] is True
    assert abs(used_total - avail_total) < 1e-3


def test_battery_draining_trend():
    panel, power = _panel_with_power()
    _payload(panel)                                       # snapshot 1: baseline
    power.SetMainBatteryPower(power.GetMainBatteryPower() - 500.0)
    panel.invalidate() if hasattr(panel, "invalidate") else None
    p = _payload(panel)
    assert p["batteries"]["main"]["draining"] is True
    assert p["batteries"]["reserve"]["draining"] is False


def test_tractor_presence_requires_emitters():
    panel, player = _panel_with_player(tractor_weapons=0)
    assert _payload(panel)["tractor"]["present"] is False


def test_shields_label_renamed():
    p = _payload(_panel())
    assert [s["label"] for s in p["sliders"]] == ["Weapons", "Engines", "Sensor Array", "Shields"]
```

Adapt helper names to the fixture file's real conventions (`_fake_player` exists; add the power-property authored values there). The diffing test (`render_payload() is None` when unchanged) stays — update its key expectations.

- [ ] **Step 2: Run to verify failures** — `uv run pytest tests/unit/test_engineering_power_panel.py -v` → FAIL (old schema).

- [ ] **Step 3: Implement `_snapshot` v2** per the Interfaces block. Structure:

```python
def _snapshot(self):
    ...visibility gating unchanged...
    prop = power.GetProperty()
    authored_out = float(prop.GetPowerOutput() or 0.0)
    main_cond = float(prop.GetMainConduitCapacity() or 0.0)
    back_cond = float(prop.GetBackupConduitCapacity() or 0.0)
    denom = authored_out + main_cond + back_cond
    live_out = power.GetPowerOutput()
    main_frac = power.GetMainBatteryPower() / power.GetMainBatteryLimit() if power.GetMainBatteryLimit() > 0 else 0.0
    ...reserve likewise...
    available = {
        "warp_core": round(live_out / denom, 4) if denom > 0 else 0.0,
        "main": round(main_cond * main_frac / denom, 4) if denom > 0 else 0.0,
        "reserve": round(back_cond * res_frac / denom, 4) if denom > 0 else 0.0,
    }
    used = []
    for key, _label, getters in _GROUPS:
        demand = sum(s.GetNormalPowerWanted() * s.GetPowerPercentageWanted() for s in self._systems(player, getters))
        used.append({"key": key, "frac": demand / denom if denom > 0 else 0.0})
    avail_total = sum(available.values())
    used_total = sum(u["frac"] for u in used)
    overload = used_total > avail_total > 0.0
    if overload:
        scale = avail_total / used_total
        for u in used:
            u["frac"] *= scale
    for u in used:
        u["frac"] = round(u["frac"], 4)
    ...damage, batteries trend via self._batt_prev/_batt_dir, tractor/cloak presence...
```

`GetMaxCondition` on the power subsystem exists (ShipSubsystem base). Initialise `self._batt_prev = {}` and `self._batt_dir = {"main": False, "reserve": False}` in `__init__`.

- [ ] **Step 4: Full suites** — `uv run pytest tests/unit/test_engineering_power_panel.py -v` then `uv run pytest tests/host tests/unit -q` → PASS (fix any host-test payload-key ripples in the same commit; `tests/host/test_power_display_sdk.py` doesn't read the CEF payload, but the routing test asserts dispatch, not shape — verify).

- [ ] **Step 5: Commit** — `git add -A engine/ui tests/ && git commit -m "feat(ui): engpower payload v2 — grid fractions, battery trends, presence"`

---

### Task 2: Tractor/Cloak toggle dispatch

**Files:**
- Modify: `engine/ui/engineering_power_panel.py` (`dispatch_event`, ~line 157)
- Test: `tests/unit/test_engineering_power_panel.py`

**Interfaces:**
- Consumes: `engine/appc/weapon_config.py` — `toggle_tractor(ship)` (line 248), `toggle_cloak(ship)` (line 267): the SAME helpers the weapons-display panel maps via its `_CONFIG_ACTIONS` (`engine/ui/weapons_display_panel.py:54-59`, dispatch at 121-135). Import the module at call time so tests can patch it (that file's stated convention).
- Produces: actions `toggle:tractor` and `toggle:cloak` (arriving as `engpower/toggle:tractor` through PanelRegistry, prefix stripped).

- [ ] **Step 1: Failing tests**

```python
def test_toggle_tractor_routes_to_weapon_config(monkeypatch):
    panel, player = _panel_with_player()
    calls = []
    import engine.appc.weapon_config as wc
    monkeypatch.setattr(wc, "toggle_tractor", lambda ship: calls.append(ship))
    assert panel.dispatch_event("toggle:tractor") is True
    assert calls == [player]


def test_toggle_cloak_routes_to_weapon_config(monkeypatch):
    panel, player = _panel_with_player()
    calls = []
    import engine.appc.weapon_config as wc
    monkeypatch.setattr(wc, "toggle_cloak", lambda ship: calls.append(ship))
    assert panel.dispatch_event("toggle:cloak") is True
    assert calls == [player]


def test_toggle_without_player_is_owned_noop():
    panel = EngineeringPowerPanel(get_player=lambda: None, is_engineering_open=lambda: True)
    assert panel.dispatch_event("toggle:tractor") is True
```

- [ ] **Step 2: Run** — FAIL (`dispatch_event` returns False for unknown action).

- [ ] **Step 3: Implement** in `dispatch_event`, before the `set:` parsing:

```python
        if action in ("toggle:tractor", "toggle:cloak"):
            player = self._get_player()
            if player is not None:
                from engine.appc import weapon_config
                if action == "toggle:tractor":
                    weapon_config.toggle_tractor(player)
                else:
                    weapon_config.toggle_cloak(player)
                self._last_pushed = None
            return True
```

- [ ] **Step 4: Suites** — targeted file + `uv run pytest tests/host tests/unit -q` → PASS.

- [ ] **Step 5: Commit** — `git add -A engine/ui tests/ && git commit -m "feat(ui): engpower tractor/cloak toggles reuse weapon_config helpers"`

---

### Task 3: JS + CSS rewrite to the v28 mockup

**Files:**
- Rewrite: `native/assets/ui-cef/js/engineering_power.js`, `native/assets/ui-cef/css/engineering_power.css`
- Modify: `native/assets/ui-cef/index.html` (replace the `#engpower-root` inner skeleton + doc comment)
- Test: none automated (JS/CSS are runtime-loaded); the payload contract is Task 1's tests. Verify `uv run pytest tests/host -q` stays green (no Python touched).

**Interfaces:**
- Consumes: Task 1 payload (schema in Task 1's Interfaces block), Task 2 actions.
- Produces: `setEngineeringPower(payload)` rendering the v28 design; outbound `dauntlessEvent('engpower/set:<key>:<value>')` on row drag and `dauntlessEvent('engpower/toggle:tractor'|'engpower/toggle:cloak')` on toggle click.

**The visual source of truth is `docs/ui_designs/06-engineer-panel-v2.html`** — open it and lift the CSS (classes `.row/.track/.fill/.thumbline/.mark100/.ticks/.grid-wrap/.dmg-col/.bars-col/.used-bar/.pu-bar/.pu-rel/.btick/.pu-labels/.bgroup/.toggle-col/.btoggle/.cline-on/.cline-off/.pillar/.pcol/.pbump/.pfill/.pname/.ppct` and the exact colour values) VERBATIM into `engineering_power.css`, namespaced under `#engpower-root` (prefix every rule; keep the existing `position:fixed; top:8px; right:8px; width:540px` root — note the width grows from 240 to ~540: **also update the click hit-region constants in `engine/host_loop.py` (`_TR_W` block added in commit 422516af) to `540 + 16` in this task**, and run `uv run pytest tests/unit/test_engineering_power_panel.py tests/host -q` after).

Behavioural requirements (JS):

1. **Static skeleton in index.html** (build-once): 4 slider rows with `data-key`, tick row, grid block (damage col + used bar + available bar + 3 bticks + label row), bottom group (main glyph, toggle col with two `.btoggle` divs + two line divs, reserve glyph). Rows/toggles hidden via `style.display='none'` when `present` is false (weapons rows always present; tractor/cloak per payload — when only one is present it centres alone: the toggle-col keeps its layout, the missing row+line just hides).
2. **setEngineeringPower(p)**: update-only (no innerHTML rebuilds): fills' widths (`pct/1.25` for sliders; grid fracs normalised — damage `p.grid.damage/(damage+availTotal)` of the grid width, available segments each `frac/(damage+availTotal)` etc. so the whole grid spans full width), thumb positions, % labels, btick lefts, label-row span widths (fade a label below 40 px via opacity 0), used segments' widths + overload tint class, battery fills/percent/▼, toggle state text + line class (`.cline-on` solid+glow / `.cline-off` dashed swap by class, colours fixed per battery).
3. **Row drag**: on `pointerdown` on a `.track`: `setPointerCapture`, set `_epDragging=key`; on `pointermove`/`pointerdown` compute `pct = clamp(offsetX/track.width, 0, 1) * 1.25`, snap to 0.05, update the local fill/thumb/label immediately, and fire `dauntlessEvent('engpower/set:'+key+':'+pct.toFixed(2))` (throttle to one event per animation frame); on `pointerup` clear `_epDragging`. While `_epDragging === key`, `setEngineeringPower` must NOT update that row (replaces the old activeElement guard).
4. **Toggle clicks**: `.btoggle` onclick → `dauntlessEvent('engpower/toggle:tractor')` / `('engpower/toggle:cloak')`.
5. Keep: hide root when `payload.visible !== true`; no console.log (swallowed in CEF).

- [ ] **Step 1: Write the CSS** (verbatim lift, namespaced). **Step 2: Rewrite index.html skeleton + JS** per the contract. **Step 3: Update the host_loop hit-region width + comment.** **Step 4:** `uv run python -m py_compile engine/host_loop.py && uv run pytest tests/host tests/unit -q` → PASS. **Step 5: Commit** — `git add -A native/assets engine/host_loop.py && git commit -m "feat(ui): engpower v28 render — grid bars, battery glyphs, siphon lines, row drag"`

---

### Task 4: Design-system canon update

**Files:**
- Modify: `docs/ui_designs/06-engineer-panel.html` (replace content with `06-engineer-panel-v2.html`'s), `docs/ui_designs/06-engineer-panel.md` (rewrite), `docs/ui_designs/07-power-transmission-grid.md` (retire → pointer stub), `docs/ui_designs/07-power-transmission-grid.html` (delete), `docs/ui_designs/README.md` (index rows 06 + 07)
- Delete: `docs/ui_designs/06-engineer-panel-v2.html` (its content moves into 06)

**Steps:** (docs only, no tests)

- [ ] **Step 1:** `git mv -f docs/ui_designs/06-engineer-panel-v2.html docs/ui_designs/06-engineer-panel.html`
- [ ] **Step 2:** Rewrite `06-engineer-panel.md` from the spec's "Visual structure" + "Data contract" sections (same skeleton as the other design docs: Structure ASCII, palette tokens table, anatomy specs, runtime contract = the Task 1 payload schema). State the deviations from the old canon explicitly: headerless, sliders-first, used/available pair replaces the single POWER USED bar, warp-core pillar removed, toggles between batteries with siphon lines, conditional presence rule.
- [ ] **Step 3:** Replace `07-power-transmission-grid.md`'s body with a 4-line retirement note pointing at 06 ("folded into the engineer panel's used/available bar pair, 2026-07-06 redesign; see 06-engineer-panel.md"); `git rm docs/ui_designs/07-power-transmission-grid.html`. Update README index: 06 description → "Engineering: sliders + used/available grid + battery glyphs + siphon toggles"; 07 row → "(retired — folded into 06)".
- [ ] **Step 4: Commit** — `git add -A docs/ui_designs && git commit -m "docs(ui): 06 engineer-panel canon replaced by v28 redesign; 07 folded in"`

---

### Task 5: Gate + live-verify

- [ ] **Step 1:** `scripts/check_tests.sh` → exits 0 (any non-ledger failure is this branch's regression — fix before proceeding).
- [ ] **Step 2:** Live-verify checklist (Mark, in-game — relaunch `./build/dauntless`):

```
[ ] Panel matches docs/ui_designs/06-engineer-panel.html (Engineering menu open)
[ ] Rows drag smoothly; thumb + % track the pointer; 100% hairline at 80%
[ ] Tick labels sit at true positions (100% under the hairline)
[ ] Damage column appears after warp-core damage, spanning BOTH bars
[ ] Used segments move with sliders; overload tint at saturation
[ ] Available MAIN/RESERVE segments shrink as batteries drain
[ ] Battery glyphs: bumps, rounded, ▼ while draining, main 1.5x wider
[ ] Tractor toggle engages/disengages; line solid+glow ↔ dashed
[ ] Galaxy shows NO cloak row; warbird shows both rows
[ ] Top-right clicks land on the panel across its full 540px width
```

- [ ] **Step 3:** Commit any fixes; stop for the finishing-a-development-branch decision (branch also carries the whole power-management feature).

## Self-Review Notes

- Spec coverage: visual structure → T3+T4; data contract table → T1; interaction → T1 (set path unchanged) + T2 + T3; conditional presence → T1 (payload) + T3 (render); canon update → T4; testing section → T1/T2 tests + T5 gate + live list. Out-of-scope items have no tasks — correct.
- Hit-region width change (panel 240→540) discovered during planning and folded into T3 — it would otherwise re-break click-through.
- Type consistency: payload keys in T1's schema match T3's render contract; action strings `toggle:tractor`/`toggle:cloak` consistent across T2/T3.
