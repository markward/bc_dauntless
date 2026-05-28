# ShipDisplay Panel — Design

**Status:** design drafted, awaiting user review
**Date:** 2026-05-28
**Author:** Mark Ward (with Claude)
**Prior art:** [`2026-05-24-cef-integration-design.md`](./2026-05-24-cef-integration-design.md) (CEF host loop + composite pass), [`2026-05-19-sdk-ui-shim-design.md`](./2026-05-19-sdk-ui-shim-design.md) (SDK widget shim layer).
**Visual reference:** [`docs/ui_designs/03-shields-readout.md`](../../ui_designs/03-shields-readout.md) (palette + states). Layout in that mockup is superseded by the placement decision in §3 — player anchored to the bottom-right tactical cluster, target as a top-left overlay (the original BC layout, matching the canonical screenshot).
**SDK contract:** [`docs/ui_designs/SDK_UI_API.md`](../../ui_designs/SDK_UI_API.md) (palette tokens, widget factory API, event dispatch).

## 1. Goal

Implement the SDK `ShipDisplay` widget as a CEF panel in `engine/ui/`, rendering both instances the SDK constructs (`pTCW.GetShipDisplay()` for the player ship, `pTCW.GetEnemyShipDisplay()` for the current target). The panel honours the full SDK composite — hull integrity bar, six-quadrant shield silhouette, subsystem damage list — and exposes the SDK widget factory surface so unmodified bridge scripts continue to work.

The player instance anchors in the bottom-right tactical cluster (left of the Weapons Settings and Weapons Display panels, matching the canonical BC layout). The target instance floats at the top-left of the viewport with an additional crosshair + range + speed badge and a minimize affordance.

## 2. Non-goals

- Click-to-target on the ship silhouette. Future spec.
- Animated hit-flash on shield quadrants, animated hull bar bucket transitions. CSS transitions can be layered on later without API changes.
- Sound on damage / shield-hit events. Owned by the audio layer.
- Per-resolution layout tuning. CSS handles resolutions fluidly via vh/vw.
- Save/load support for panel state. Panels are reconstructed from SDK state at bridge load; no `__getstate__` work.
- Honouring `SetPosition`, `AlignTo`, `Resize`, or the SDK's chained layout protocol. CSS owns layout; rationale in §6.
- Mod-driven custom positioning. Speculative; add only if a real mission script needs it.

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Python (host loop)                                           │
│                                                              │
│  engine/ui/ship_display_panel.py                             │
│    ShipDisplayPanel(Panel)        ← one class, two instances │
│      role="player"  ──┐                                      │
│      role="target"  ──┤                                      │
│                       │  register on PanelRegistry           │
│                       │  as "ship-player" + "ship-target"    │
│                       ▼                                      │
│                                                              │
│  Each tick:                                                  │
│    snapshot = (hull%, shield_face_pcts×6, damage_states,     │
│                ship_name, affiliation, range_m, speed_kph)   │
│    if snapshot != last:                                      │
│      emit setShipDisplay('<role>', {...}) JS                 │
│                                                              │
│  App.ShipDisplay_Create(...) shim                            │
│    returns a ShipDisplayPanel — registered & owned by the    │
│    TacticalControlWindow shim, exposes SetShipID,            │
│    UpdateForNewShip, GetShieldsDisplay, GetDamageDisplay,    │
│    GetHealthGauge — the full SDK surface from §2 of          │
│    SDK_UI_API.md.                                            │
├──────────────────────────────────────────────────────────────┤
│ HTML/CEF                                                     │
│                                                              │
│  native/assets/ui-cef/panels/ship_display/                   │
│    ship_display.html      template w/ two DOM containers     │
│    ship_display.css       quadrant colours, hull bar,        │
│                           target-only extras keyed by        │
│                           [data-role="target"]               │
│    ship_display.js        setShipDisplay(role, state)        │
│    silhouettes/           per-species SVGs                   │
│                                                              │
│  DOM containers:                                             │
│    #ship-display-player   anchored bottom-right cluster      │
│    #ship-display-target   anchored top-left, hidden when     │
│                           no target / minimized              │
└──────────────────────────────────────────────────────────────┘
```

One Python class, one HTML/CSS/JS bundle, two registered panels distinguished by `role`. The SDK shim layer wraps each registered panel as the return value of `App.ShipDisplay_Create()`, mirroring how the SDK already instantiates the widget twice.

The player container sits inside the existing bottom-right tactical-cluster anchor (next to where Weapons Settings + Weapons Display will go). The target container is fixed-positioned at top-left with its own anchor.

## 4. Widget class shape

```python
# engine/ui/ship_display_panel.py

ROLE_PLAYER = "player"
ROLE_TARGET = "target"

class ShipDisplayPanel(Panel):
    """CEF view for one ShipDisplay instance — player or target.

    The SDK creates two ShipDisplay widgets per game
    (TacticalControlWindow's pShipDisplay + pEnemyShipDisplay). We
    mirror that by instantiating this class twice and registering each
    as a distinct panel.
    """

    def __init__(self, role: str):
        super().__init__()
        assert role in (ROLE_PLAYER, ROLE_TARGET)
        self._role = role
        self._ship_id: int = App.NULL_ID
        self._last_snapshot: Optional[tuple] = None
        # SDK-mandated child handles (returned by GetShieldsDisplay /
        # GetDamageDisplay / GetHealthGauge — see §5).
        self._shields = _ShieldsSubview(self)
        self._damage  = _DamageSubview(self)
        self._gauge   = _HullGaugeSubview(self)
        # Target-only state
        self._minimizable: bool = (role == ROLE_TARGET)
        self._minimized:   bool = False

    @property
    def name(self) -> str:
        return "ship-" + self._role          # "ship-player" / "ship-target"

    # SDK widget API (mirrors Tactical/Interface/ShipDisplay.py)
    def SetShipID(self, ship_id: int) -> None: ...
    def GetShipID(self) -> int: ...
    def UpdateForNewShip(self) -> None: ...
    def GetShieldsDisplay(self) -> "_ShieldsSubview": ...
    def GetDamageDisplay(self)  -> "_DamageSubview":  ...
    def GetHealthGauge(self)    -> "_HullGaugeSubview": ...
    def SetMinimizable(self, v: int) -> None: ...    # target only; no-op for player
    def SetMinimized(self, v: int) -> None:   ...    # target only; no-op for player
    def IsMinimized(self) -> int: ...

    # Panel framework
    def render_payload(self) -> Optional[str]: ...
    def dispatch_event(self, action: str) -> bool: ...
```

`_ShieldsSubview`, `_DamageSubview`, `_HullGaugeSubview` are thin objects that exist only so the SDK can call `pShipDisplay.GetShieldsDisplay().UpdateForNewShip()` etc. They forward mutations back to the parent panel — they don't render anything independently, because the parent emits one consolidated snapshot per tick.

**Snapshot tuple shape** (used directly as the cache key):

```python
(
    ship_id,
    ship_name,         # "USS Galaxy", "Warbird-2", or "" when no target
    affiliation,       # "FRIENDLY" | "ENEMY" | "NEUTRAL" | "UNKNOWN" | "NONE"
    species_icon_key,  # e.g. "Galaxy" — picks the silhouette
    hull_pct,          # 0.0 – 1.0
    shields_pct,       # tuple of six floats, indexed FRONT..RIGHT
    damage_states,     # tuple of (subsystem_name, state) pairs, sorted
    range_m,           # target only; None for player
    speed_kph,         # target only; None for player
    minimized,         # target only; False for player
    visible,           # mirrors self.visible (e.g. False when no target)
)
```

`affiliation` drives the title-bar colour token. `species_icon_key` swaps the silhouette between Galaxy / Warbird / Akira etc.

## 5. SDK shim wiring

The SDK calls `App.ShipDisplay_Create(...)` to construct each instance, and `App.ShieldsDisplay_Create(...)` / `App.DamageDisplay_Create(...)` / `App.STFillGauge_Create(...)` to construct the children. These factories must keep working — the SDK code in `sdk/Build/scripts/Tactical/Interface/ShipDisplay.py` is not modified, per the SDK_UI_API.md §4.4 contract.

**Construction path:**

```python
# engine/sdk_ui/widgets/ship_display.py (new file)
from engine.ui.ship_display_panel import ShipDisplayPanel, ROLE_PLAYER, ROLE_TARGET
from engine.sdk_ui.host_panels import g_panel_registry

# Module-level counter — the SDK calls ShipDisplay_Create twice during
# bridge construction (LoadBridge.py builds pShipDisplay first, then
# pEnemyShipDisplay). We hand out player on the first call, target on
# the second. Reset on bridge teardown.
_create_count = 0

def ShipDisplay_Create(*args, **kwargs):
    global _create_count
    role = ROLE_PLAYER if _create_count == 0 else ROLE_TARGET
    _create_count += 1
    panel = ShipDisplayPanel(role)
    g_panel_registry.register(panel)
    return panel

def ShipDisplay_Cast(obj):
    return obj if isinstance(obj, ShipDisplayPanel) else None

def ShieldsDisplay_Create(*args, **kwargs):
    return _ShieldsSubview(parent=None)   # parent wired by SetShieldsDisplay

def DamageDisplay_Create(*args, **kwargs):
    return _DamageSubview(parent=None)

def STFillGauge_Create(*args, **kwargs):
    return _HullGaugeSubview(parent=None)
```

`SetHealthGauge` / `SetDamageDisplay` / `SetShieldsDisplay` on `ShipDisplayPanel` adopt the orphan sub-view (set its `parent` to `self`). After that, mutations on the sub-view back-propagate to the panel — `pShieldsDisplay.UpdateForNewShip()` calls `self.parent._invalidate()` which forces a re-emit on the next tick.

**Bridge teardown:** when the SDK calls `pTCW.SetDestroyed()` or similar (game-over / mission-end), the shim deregisters both panels and resets `_create_count = 0` so the next bridge load starts clean.

**Mutator coverage:**

| Handle | SDK methods we honour |
|---|---|
| `ShipDisplayPanel` | `SetShipID`, `GetShipID`, `SetShipIDVar`, `SetMinimizable`, `SetMinimized`, `IsMinimized`, `GetShieldsDisplay`, `GetDamageDisplay`, `GetHealthGauge`, `SetHealthGauge`, `SetDamageDisplay`, `SetShieldsDisplay`, `SetVisible`, `SetNotVisible`, `IsVisible` |
| `_ShieldsSubview` | `UpdateForNewShip`, `RemoveEvents`, `SetSkipParent`, `SetVisible`, `SetNotVisible` |
| `_DamageSubview` | `UpdateForNewShip`, `RemoveEvents`, `SetSkipParent`, `RepositionUI`, `HideIcons`, `ShowIcons` |
| `_HullGaugeSubview` | `SetFillColor`, `SetEmptyColor`, `SetObject` (binds to `pShip.GetHull()`), `SetVisible`, `SetNotVisible` |

**No-op mutators** (return without effect; their semantics are owned by CSS): `SetPosition`, `SetFixedSize`, `Resize`, `AlignTo`, `Layout`, `InteriorChangedSize`, `SetBatchChildPolys`, `SetMaximumSize`, `SetUseFocusGlass`, `SetNoFocus`, `SetBorderWidth/Height`. The dimension getters `GetLeft`, `GetTop`, `GetWidth`, `GetHeight`, `GetBorderWidth`, `GetBorderHeight` return constants from a per-role table so any chaining math in SDK code resolves without crashing, but the values are not authoritative for layout.

Rationale: stock BC only recalculates positions for resolution changes, menu state changes, and minimize toggles, and in every case the math reduces to "anchor to a corner, chain by widths." CSS anchors + flex handle all three fluidly. The only argument for honouring `SetPosition` would be speculative mod support, which can be added later if a real mission script needs it.

## 6. HTML / CSS

**File layout** under `native/assets/ui-cef/panels/ship_display/`:

```
ship_display.html      template fragment included by bridge.html
ship_display.css       all visual styling; uses palette tokens only
ship_display.js        exposes window.setShipDisplay(role, state)
silhouettes/           per-species SVGs (Galaxy, Warbird, Akira, …)
```

**DOM skeleton** (one container per role):

```html
<section class="bc-panel ship-display" id="ship-display-player" data-role="player">
  <header class="bc-panel__header">
    <span class="bc-panel__title" data-bind="title">PLAYER</span>
    <button class="bc-panel__minimize" data-event="ship-target/minimize-toggle" hidden>▼</button>
  </header>
  <div class="bc-panel__body">
    <div class="ship-display__silhouette-stack">
      <svg class="ship-display__silhouette" data-bind="silhouette"><!-- SVG inline --></svg>
      <div class="ship-display__shield shield--top"    data-bind="shield-top"></div>
      <div class="ship-display__shield shield--bottom" data-bind="shield-bottom"></div>
      <div class="ship-display__shield shield--front"  data-bind="shield-front"></div>
      <div class="ship-display__shield shield--rear"   data-bind="shield-rear"></div>
      <div class="ship-display__shield shield--left"   data-bind="shield-left"></div>
      <div class="ship-display__shield shield--right"  data-bind="shield-right"></div>
    </div>
    <ul class="ship-display__damage" data-bind="damage-list"></ul>
    <div class="ship-display__hull-bar">
      <div class="ship-display__hull-fill" data-bind="hull-fill"></div>
      <span class="ship-display__hull-pct" data-bind="hull-pct">100%</span>
    </div>
    <!-- target-only -->
    <div class="ship-display__target-extras" data-bind="target-extras" hidden>
      <span data-bind="range">— km</span>
      <span data-bind="speed">— kph</span>
    </div>
  </div>
</section>
```

The target container is identical markup with `data-role="target"`, anchored top-left. The minimize chevron is `hidden` on the player container.

**Palette mapping** — the only place SDK semantics map to colour tokens. Tokens come from [SDK_UI_API.md §1](../../ui_designs/SDK_UI_API.md); literal RGB values are never written into this CSS.

```css
.ship-display {
  --title-color: var(--bc-row-text-bright);
}
.ship-display[data-affiliation="FRIENDLY"] { --title-color: var(--bc-target-friendly); }
.ship-display[data-affiliation="ENEMY"]    { --title-color: var(--bc-target-name); }
.ship-display[data-affiliation="NEUTRAL"]  { --title-color: var(--bc-sensor-neutral); }
.ship-display[data-affiliation="NONE"]     { --title-color: var(--bc-no-target); }

.ship-display[data-hull="healthy"]  .ship-display__hull-fill { background: var(--bc-hull-healthy); }
.ship-display[data-hull="damaged"]  .ship-display__hull-fill { background: var(--bc-hull-damaged); }
.ship-display[data-hull="critical"] .ship-display__hull-fill { background: var(--bc-hull-critical); }

.ship-display__shield[data-integrity="full"]    { opacity: 1.0; background: var(--bc-shields); }
.ship-display__shield[data-integrity="damaged"] { opacity: 0.6; background: var(--bc-hull-damaged); }
.ship-display__shield[data-integrity="down"]    { opacity: 0.0; }

.ship-display__silhouette { color: var(--bc-shields); }
.ship-display[data-role="target"] .ship-display__silhouette { color: var(--title-color); }

.damage-row[data-state="damaged"]   { color: var(--bc-damage-damaged); }
.damage-row[data-state="disabled"]  { color: var(--bc-damage-disabled); }
.damage-row[data-state="destroyed"] { color: var(--bc-damage-destroyed); }
```

Shield-quadrant elements are positioned absolute over the silhouette (top/bottom/front/rear/left/right corresponding to compass directions on a top-down ship view). Bucket thresholds: `full` ≥ 75 %, `damaged` 1–75 %, `down` 0 %. Tunable, will calibrate by feel.

`ship_display.js`:

```js
window.setShipDisplay = function(role, state) {
  const root = document.getElementById('ship-display-' + role);
  if (!root) return;
  root.hidden = !state.visible;
  if (!state.visible) return;
  root.dataset.affiliation = state.affiliation;
  root.dataset.hull = bucketForHull(state.hull_pct);
  root.dataset.minimized = state.minimized ? 'true' : 'false';
  root.querySelector('[data-bind=title]').textContent = state.ship_name || 'NO TARGET';
  root.querySelector('[data-bind=hull-fill]').style.width = (state.hull_pct * 100) + '%';
  root.querySelector('[data-bind=hull-pct]').textContent = Math.round(state.hull_pct * 100) + '%';
  // …shield faces (six setAttribute calls), damage list rebuild,
  //   silhouette swap, target extras range/speed text…
};
```

CSS keys off `data-minimized="true"` to collapse the body to a header strip.

## 7. Per-tick data flow

The host loop runs `panel_registry.render_all()` once per tick. For each `ShipDisplayPanel`:

```python
def render_payload(self) -> Optional[str]:
    snap = self._snapshot()
    if snap == self._last_snapshot:
        return None
    self._last_snapshot = snap
    return _emit_js(self._role, snap)

def _snapshot(self) -> tuple:
    ship = self._resolve_ship()                   # role-dependent — see below
    if ship is None:
        return (None, "", "NONE", "", 0.0, (0,)*6, (), None, None, False, False)

    hull = ship.GetHull()
    hull_pct = hull.GetCondition() / max(hull.GetMaxCondition(), 1e-6)

    sh = ship.GetShieldSubsystem()
    shields_pct = tuple(
        sh.GetSingleShieldPercentage(face)
        for face in range(sh.NUM_SHIELDS)         # FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT
    )

    damage = _collect_damage_states(ship)         # ((subsys_name, state), ...)
    species = _species_key(ship)                  # "Galaxy" / "Warbird" / ...
    name = ship.GetName()
    affiliation = _affiliation_string(ship)       # "FRIENDLY"|"ENEMY"|"NEUTRAL"|"UNKNOWN"

    range_m, speed_kph = (None, None)
    if self._role == ROLE_TARGET:
        range_m   = _range_to_player(ship)
        speed_kph = _ship_speed_kph(ship)

    return (ship.GetObjID(), name, affiliation, species, hull_pct,
            shields_pct, damage, range_m, speed_kph,
            self._minimized, True)
```

**Ship resolution by role:**

```python
def _resolve_ship(self):
    import MissionLib
    player = MissionLib.GetPlayer()
    if self._role == ROLE_PLAYER:
        return player
    if player is None:
        return None
    target = player.GetTarget()
    # SDK sensor-knowledge gate (ShieldsDisplay.SetShipIcon at
    # sdk/Build/scripts/Tactical/Interface/ShieldsDisplay.py:329-338):
    # unknown target renders as "UNKNOWN OBJECT" with hidden icons.
    if target is not None and not player.GetSensorSubsystem().IsObjectKnown(target):
        return None
    return target
```

**Damage states** come from walking the ship's named subsystems. The set surfaced in v1 mirrors the original BC engineering panel: `Engines`, `Weapons`, `Sensors`, `Shield Generator`. Each emits `("damaged" | "disabled" | "destroyed")` from the Phase 1 `IsDamaged()` / `IsDisabled()` / `IsDestroyed()` flags; healthy subsystems are omitted from the tuple. Order is fixed (Engines, Weapons, Sensors, Shield Generator) so the cache key is stable. Hull is not in this list — it has its own bar.

**Idempotency:** snapshot equality short-circuits the JS emit. With 60 Hz ticks but state that changes only on hits or regen ticks, most ticks emit nothing — same pattern as `engine/ui/sensors_panel.py`. Hull-bar bucket transitions (healthy → damaged → critical) only fire JS when the bucket actually flips.

**Invalidation triggers** (force next tick to re-emit):
- `SetShipID(new_id)` — target swap, even if visually identical
- `UpdateForNewShip()` from any sub-view — SDK explicitly asks for a refresh
- `panel_registry.invalidate_all()` on CEF page reload
- `dispatch_event("minimize-toggle")` — minimized state flipped

**Tick budget:** the snapshot is six dict reads + six float divides + a subsystem walk (≤ 8 subsystems). Two instances. Comfortably sub-millisecond per tick.

## 8. Event dispatch

Only one user-driven event in v1: clicking the minimize chevron on the **target** panel.

```html
<button class="bc-panel__minimize" data-event="ship-target/minimize-toggle">▼</button>
```

CEF dispatch fires `dauntlessEvent("ship-target/minimize-toggle")`. The PanelRegistry routes by slash-prefix — `ship-target` matches the target panel's `name`, action `"minimize-toggle"` lands in:

```python
def dispatch_event(self, action: str) -> bool:
    if action == "minimize-toggle" and self._role == ROLE_TARGET:
        self._minimized = not self._minimized
        self._last_snapshot = None      # force re-emit
        return True
    return False
```

Re-emit pushes new state; CSS keys off `data-minimized="true"` to collapse the body to a header strip (matching how the original BC minimization affordance worked at [TacticalControlWindow.py:265-282](../../../sdk/Build/scripts/Tactical/Interface/TacticalControlWindow.py)).

**SDK-driven minimize:** the SDK can also call `pEnemyShipDisplay.SetMinimized(1)` directly (it does this in low-resolution branches of the original code). That mutator sets the same flag and invalidates the cache, so the SDK path and the user click path converge on one state.

No other events in v1 — the panel is read-only otherwise.

## 9. Testing

**Unit tests** — `tests/test_ship_display_panel.py`:

- `test_snapshot_changes_only_when_state_changes` — two snapshots back-to-back, second `render_payload` returns `None`.
- `test_hull_bucket_thresholds` — 100 % → `healthy`, 70 % → `healthy`, 69 % → `damaged`, 25 % → `damaged`, 24 % → `critical`, 0 % → `critical`.
- `test_target_role_no_target_returns_visible_false` — `MissionLib.GetPlayer().SetTarget(None)` → `snapshot.visible == False`.
- `test_target_role_unknown_target_emits_unknown_affiliation` — `SensorSubsystem.IsObjectKnown(target) == 0` → `affiliation="UNKNOWN"`, `name=""`, silhouette hidden.
- `test_shield_face_indices_match_sdk` — assert tuple ordering in the snapshot matches `ShieldSubsystem.FRONT_SHIELDS .. ShieldSubsystem.RIGHT_SHIELDS` (0..5) from `engine/appc/subsystems.py:1444-1450`. Note: the SDK's `ShieldsDisplay.Create` adds icons in a different visual stacking order (TOP first); our snapshot follows the subsystem face indices, not the SDK display order.
- `test_minimize_toggle_invalidates_cache` — `dispatch_event("minimize-toggle")` → next `render_payload` returns non-None even with no other state change.
- `test_setshipid_invalidates_cache` — `SetShipID(new_id)` → next `render_payload` re-emits.
- `test_subview_mutators_back_propagate` — `panel.GetShieldsDisplay().UpdateForNewShip()` invalidates the parent panel's cache.
- `test_player_role_ignores_minimize_calls` — `SetMinimized(1)` on a `ROLE_PLAYER` panel is a no-op.

**Integration tests** — `tests/test_ship_display_integration.py`:

- `test_two_panels_register_under_correct_names` — first `App.ShipDisplay_Create` → `"ship-player"`; second → `"ship-target"`.
- `test_sdk_construction_path_runs_without_exceptions` — replay the construction sequence from [ShipDisplay.py:Create](../../../sdk/Build/scripts/Tactical/Interface/ShipDisplay.py): `STFillGauge_Create` → `DamageDisplay_Create` → `ShieldsDisplay_Create` → `SetHealthGauge` → `SetDamageDisplay` → `SetShieldsDisplay`. Assert no exceptions and that all three sub-views back-reference the parent panel.
- `test_setshipid_propagates_to_subviews` — `SetShipID` on parent calls `GetShieldsDisplay().UpdateForNewShip()` (matches [ShipDisplay.py:132-159](../../../sdk/Build/scripts/Tactical/Interface/ShipDisplay.py)).

**Visual smoke** — manual via `./build/dauntless`:

1. Launch with the default mission. Confirm the player ShipDisplay renders in the bottom-right cluster with all six shield quadrants green and hull bar at 100 %.
2. Take a hit (fire-trace mission). Confirm the impacted facing dims / transitions colour and hull bar updates.
3. Target an enemy ship. Confirm the top-left target overlay appears with the enemy's name in red and silhouette swap to Warbird.
4. Untarget. Confirm target overlay collapses to hidden.
5. Click the target minimize chevron. Confirm only the header strip remains; click again to expand.
6. Damage a subsystem. Confirm the damage row appears in the appropriate state colour.

The visual smoke isn't automatable (CEF render path isn't in the test harness), but each step maps to a specific snapshot transition that the unit tests already cover — visual failure means a CSS or JS regression, not a Python state-machine bug.

## 10. Affected files

**New:**

- `engine/ui/ship_display_panel.py` — the `ShipDisplayPanel` class + sub-views.
- `engine/sdk_ui/widgets/ship_display.py` — `ShipDisplay_Create`, `ShieldsDisplay_Create`, `DamageDisplay_Create`, `STFillGauge_Create`, `ShipDisplay_Cast` factories.
- `native/assets/ui-cef/panels/ship_display/ship_display.html`
- `native/assets/ui-cef/panels/ship_display/ship_display.css`
- `native/assets/ui-cef/panels/ship_display/ship_display.js`
- `native/assets/ui-cef/panels/ship_display/silhouettes/` — at minimum Galaxy + Warbird SVGs for v1 smoke; species coverage extends as missions need.
- `tests/test_ship_display_panel.py`
- `tests/test_ship_display_integration.py`

**Modified:**

- `App.py` — re-export `ShipDisplay_Create`, `ShipDisplay_Cast`, `ShieldsDisplay_Create`, `DamageDisplay_Create`, `STFillGauge_Create` from `engine.sdk_ui.widgets.ship_display`.
- `engine/sdk_ui/host_panels.py` — wire bridge teardown to deregister ShipDisplay panels and reset the `_create_count` counter.
- `native/assets/ui-cef/bridge.html` — include the ship_display fragment with both DOM containers in the correct anchor positions.

**Updated docs:**

- `docs/ui_designs/03-shields-readout.md` — annotate that the side-by-side mockup is superseded by the original BC layout (player in cluster, target top-left). Update the diagram to reflect that.
