# Ship → bridge matrix (auto-select the player bridge) — design

**Status:** implemented by docs/superpowers/plans/2026-09-16-ship-bridge-matrix.md; awaiting live verification (§4 Live verification, items 1–5).
**Fidelity tier:** SDK-derived load mechanism (TIER SDK) + a Dauntless-native
selection service and settings UI that BC never had. The service is a
*deliberate deviation* from BC's manual two-button picker, at Mark's direction.

## Problem

In BC's QuickBattle the player picked the bridge by hand from a two-button
"Player Bridge" window (Galaxy / Sovereign). Once the community added bridges
the pick became a chore: you always want the bridge that suits the ship you
just chose. Dauntless never exposed that SDK window at all (it was left as an
"SP2 remainder"), so today every QuickBattle run gets the Galaxy bridge.

## What BC does (SDK evidence)

There is exactly **one** bridge-load mechanism in the 1228 SDK files:
`LoadBridge.Load("<ConfigScript>")` (`sdk/Build/scripts/LoadBridge.py:57`),
which `__import__`s `Bridge.<ConfigScript>` and calls its `CreateBridgeModel`,
`ConfigureCharacters`, `PreloadAnimations`. Two config scripts ship:
`Bridge/GalaxyBridge.py` (loads `data/Models/Sets/DBridge/…`) and
`Bridge/SovereignBridge.py` (EBridge). Community bridge mods ship the same
shape: a `scripts/Bridge/<X>.py` config script plus a set folder.

39 call sites, in two shapes:

| Caller | Argument | When | Reloaded later? |
|---|---|---|---|
| 33 campaign + 5 tutorial missions | a **string literal** at the top of `Initialize()` (`"GalaxyBridge"` E1–E2, `"SovereignBridge"` E3–E8) | before the player ship exists (E1M1 `:188` vs `CreatePlayerShip` `:793`) | no |
| QuickBattle (`QuickBattle.py:2928`) | the global `g_sBridgeType` | at the tail of `RecreatePlayer()`, after `CreatePlayerShip(g_sPlayerType…)` (`:2888`) | every Start, live player swap, End-Combat revert, boot `Initialize`, player-death respawn |

`RecreatePlayer()` has four callers: `Initialize` (`:744`), `StartSimulation2`
(`:3099`), `EndSimulation` (`:3225`), `ShipDestroyed` (`:3317`). Only the first
two pass through host code we own. The SDK's own picker (`SelectBridge`,
`:2948`) just assigns `g_sBridgeType`.

BC's player-facing labels: the "Player Bridge" window buttons were TGL
`"Galaxy"` and `"Sovereign"` (`data/TGL/QuickBattle/QuickBattle.tgl`); ship
names came from `data/TGL/Ships.tgl` (`BirdOfPrey` → *Bird of Prey*,
`KessokLight` → *Light Cruiser*). `DBridge` / `EBridge` never appear in UI.

## Decisions (with the reasoning that produced them)

1. **This is the default mechanism for every mode, not a QuickBattle feature.**
   Any mode that creates a player ship without dictating a bridge asks the
   service. QuickBattle is the first consumer; multiplayer or any future mode
   wires the same one-liner at its own player-creation point. Campaign and
   tutorial missions **override by construction**: their literal
   `LoadBridge.Load("…")` calls never consult the service, so no hook, no SDK
   edit, no fidelity risk.
2. **Ship universe = BC's own player-ship menu** (revised 2026-09-19; the
   first cut listed every `ships/<Name>.py` and the panel showed asteroids
   and starbases). `GeneratePlayerShipMenu` (SDK `QuickBattle.py:1622–1703`)
   hard-codes sixteen hulls — Akira, Ambassador, Galaxy, Nebula, Sovereign,
   BirdOfPrey, Vorcha, Marauder, Warbird, Galor, Keldon, CardHybrid,
   KessokLight, KessokHeavy, Shuttle, Transport — gated by unlock bitfields
   that default to everything-unlocked (`:1181`) and which nothing in our
   tree narrows. Mods extend that menu through Foundation's
   `RegisterQBPlayerShipMenu` (we model it: `playerMenuGroup` on the
   `ShipDefinition`, plugins loaded at boot before `bridge_pins`). So:
   `STOCK_PLAYER_SHIPS` ∪ Foundation player registrations, each kept only
   if its `ships/<stem>.py` exists in the SDK tree or the mod overlay. Keyed
   by script stem (what `CreatePlayerShip` / `g_sPlayerType` take); still
   mode-agnostic and needs no QuickBattle import. Rejected: the `ships/`
   directory scan (too wide — stations, probes, campaign one-offs are
   friend/enemy catalog entries only), QuickBattle's friendly table (it holds
   the starbases too), and a flyability heuristic (our invention).
3. **A pinned bridge that cannot be loaded ⇒ fall back to the default bridge,
   log once, keep the pin and show it as missing.** Never break the boot,
   always NAME what could not be resolved (the mod-support convention);
   never silently mutate a player's file on boot.
4. **A pin change takes effect at the next player (re)creation** — the moment
   BC itself loads the bridge. No "apply now"; no second load trigger BC
   doesn't have.
5. **QuickBattle consults the service by wrapping `RecreatePlayer` once**, so
   the matrix is evaluated at the moment of use for all four callers,
   including the two SDK-internal ones. Rejected: explicit syncs at every
   host write of `g_sPlayerType` (five sites that must stay in step — the
   "forgot one call site" bug class); hooking `LoadBridge.Load` itself
   (campaign literals would be indistinguishable from QuickBattle's default).
6. **Pins live in a dedicated `bridges.json`**, not in `settings.json`, so a
   player can back up and restore them at the filesystem level without
   dragging graphics/gameplay settings along. Not `Options.cfg` (SDK code
   saves that whole map at times we don't control).
7. **Labels are BC's own**: bridges show as *Galaxy* / *Sovereign*; ships via
   `Ships.tgl` with the script stem as fallback.

## Section 1 — The service: `engine/bridge_selection.py`

One module, no QuickBattle imports, three concerns.

### Bridge registry (derived, never persisted)

```python
BridgeInfo = namedtuple("BridgeInfo", "script_name label")
STOCK_BRIDGES = (BridgeInfo("GalaxyBridge", "Galaxy"),
                 BridgeInfo("SovereignBridge", "Sovereign"))

def available_bridges() -> list[BridgeInfo]   # STOCK_BRIDGES + _scan_mod_bridges()
def is_available(script_name) -> bool
```

Stock entries are a constant (a property of the SDK, not of the install).
Mod entries come from `_scan_mod_bridges()` at call time. Memoised for the
life of the process, keyed on `mods.current()` identity — the module reads
`mods.current()` at use, never captures it.

`_scan_mod_bridges()` **ships as a stub returning `[]`** in this feature. Its
contract is fixed here so the follow-up starts from a RED test:

- walk `mods.current()`'s case-folded index for `scripts/bridge/*.py`;
- keep a module only if its **source text** contains `def CreateBridgeModel(`
  — text, not import: importing a `Bridge/*.py` at panel-open time runs its
  top-level code (`import App`, model loads). This excludes the stock
  `*Handlers`, `*Properties`, `BridgeMenus`, `BridgeUtils`, `bridgeeffects`
  and `Characters/` by construction, not by a name list;
- label = script name with one trailing `Bridge` stripped (`VoyagerBridge` →
  *Voyager*), until a better-authored source exists;
- returns `[BridgeInfo]`, appended after the stock entries; a mod that
  re-declares a stock script name is dropped (stock wins), logged once.

### Ship universe (derived, never persisted)

```python
def available_ships() -> list[str]      # script stems, sorted, case-deduplicated
def ship_label(stem) -> str             # Ships.tgl string, else stem
```

`STOCK_PLAYER_SHIPS` (Decision 2) plus the `shipFile` of every Foundation
definition with `playerMenuGroup` set, each kept only if a matching
`ships/<stem>.py` exists in `paths.sdk_scripts()` or the mod overlay
(`mods.current()` index entries under `scripts/ships/`), matched
case-insensitively (the overlay is case-folded; the LC pack declares
`LCintrepid` against `LCIntrepid.py`) — a stock override keeps the stock
spelling, a mod registration takes its script's. Sorted by label. Resolved
at call time — no module-level path constant
(`tests/unit/test_path_indirection.py` guards this). `ship_label` reads
`data/TGL/Ships.tgl` through `paths.game_asset` via the existing
`engine.missions.tgl_reader`, cached per process.

### Pins and resolution

```python
DEFAULT_PINS = {"Galaxy": "GalaxyBridge",
                "Sovereign": "SovereignBridge",
                "Akira": "SovereignBridge"}
DEFAULT_BRIDGE = "GalaxyBridge"

class BridgePins:                       # thin façade over a SettingsStore
    def __init__(self, store: SettingsStore)
    def pins(self) -> dict[str, str]    # file present ⇒ its "pins" (authoritative, even {});
                                        # absent ⇒ copy of DEFAULT_PINS
    def resolve(self, ship_name) -> str
    def default_bridge(self) -> str     # the "default" section's bridge as written; absent ⇒ DEFAULT_BRIDGE
    def default_row(self) -> DefaultRow # (bridge, bridge_label, bridge_missing) for the panel
    def set_default_bridge(self, bridge) -> None  # raises UnknownBridge
    def add(self, ship, bridge) -> None # raises DuplicateShip / UnknownBridge
    def set_bridge(self, ship, bridge) -> None  # raises UnmappedShip / UnknownBridge; keeps file order
    def remove(self, ship) -> None
    def reset(self) -> None             # deletes the FILE
    def rows(self) -> list[PinRow]      # for the panel; see Section 3
```

`resolve(ship)`:

1. `bridge = pins().get(ship)`; if none ⇒ the **stored default**
   (`default_bridge()`, the panel's Default row; revised 2026-09-19 — it
   used to be the constant `DEFAULT_BRIDGE`).
2. if `not is_available(bridge)` ⇒ the stored default, and log **once per
   (ship, bridge) per process** via `dev_mode.log_swallowed`-style boot-report
   line: `bridge pin Akira -> VoyagerBridge not available; using GalaxyBridge`.
   The pin is **not** removed.
3. If the stored default is itself unavailable (a mod removed it) ⇒ the
   stock `DEFAULT_BRIDGE` (`GalaxyBridge`, always present), logged once; the
   stored value is kept and the Default row shows it *(missing)*.
4. Never raises. Keys compare **exactly** as written (the panel always writes
   canonical stems; a restored file behaves as when saved).

`add` rejects a ship already pinned (`DuplicateShip`) and a bridge not in
`available_bridges()` (`UnknownBridge`). The dict makes "each ship once"
structural; the guard keeps the panel honest. `set_bridge` re-points a row;
`set_default_bridge` re-points the Default row.

### Storage: `bridges.json`

```json
{
  "version": 1,
  "pins": {
    "Galaxy":    "GalaxyBridge",
    "Sovereign": "SovereignBridge",
    "Akira":     "SovereignBridge"
  },
  "default": { "bridge": "GalaxyBridge" }
}
```

`default` is written only once the Default row has been edited; a file
without it (every file from before 2026-09-19) reads as `GalaxyBridge`.

- Path from `bridge_selection.default_bridges_path()` — the single seam to
  move if the install dir is read-only. Sits next to `settings.json`
  (`settings_store.default_settings_path().parent / "bridges.json"`).
- Reuses `SettingsStore(path=…)`: atomic tmp+`os.replace` writes, corrupt
  file quarantined to `bridges.json.corrupt` and defaults used, schema
  stamp, unknown keys preserved. The store's section/key API fits as is:
  `"pins"` is the section and each ship stem is a key
  (`store.set("pins", ship, bridge)`, `store.has("pins", ship)`). "File
  present" means `store.has_section("pins")` — a one-line addition to
  `SettingsStore`, since `_section()` cannot distinguish absent from `{}`.
  `reset()` unlinks the file outright (through the store, so the in-memory
  document is cleared too), which makes "absent ⇒ defaults" the true
  first-launch state again.
- **Tolerant read** (the file is backed up, restored and hand-edited): a ship
  outside `available_ships()` — absent, or installed but not a player hull —
  stays and is shown as *(not playable)*;
  a bridge not available stays and is shown as *(missing)*. Nothing is
  pruned. Only a malformed file is quarantined.
- `settings.json` is untouched; no `SETTINGS` row is added, so
  `test_every_setting_key_is_unique_and_in_a_known_section` stays as is.

### Wiring

Constructed in `host_loop.run()` next to the `SettingsStore` (~`:7231`),
before `ConfigurationPanel`; held on the controller as
`controller.bridge_pins`. `_MissionLoader` receives it (or reads it off the
controller it already holds) for the QuickBattle hook.

## Section 2 — QuickBattle integration + runtime bridge swap

### The wrap

In `_MissionLoader.load_quickbattle`, immediately after
`import QuickBattle.QuickBattle as QB` and **before**
`QuickBattleGame.Initialize(game)`:

```python
bridge_selection.install_quickbattle_hook(QB, self._c.bridge_pins)
```

Replaces `QB.RecreatePlayer` with a wrapper that does
`QB.g_sBridgeType = pins.resolve(QB.g_sPlayerType)` and then calls the
original. Idempotent: the wrapper carries a marker attribute
(`_dauntless_bridge_hook = True`) and the installer returns early if the
current attribute already has it. `reset_sdk_globals` re-imports SDK modules
on every mission swap, so the install runs on **every** `load_quickbattle`,
not once per process. Precedent:
`engine/foundation/quickbattle._ensure_build_dialog_reinjects` wraps
`BuildDialog` the same way.

`_inject_quickbattle_player_defaults` keeps setting
`QB.g_sBridgeType = "GalaxyBridge"` — it is the SDK's own initial value and
is always overwritten at use. The panel's `_set_player_from_selection`,
`_sync_quickbattle_player_revert` and `start_quickbattle` need **no** change.

### Boot double-load is BC's own

`QuickBattle.Initialize` calls `LoadBridge.Load("GalaxyBridge")` literally
(`:715`) and then `RecreatePlayer()` (`:744`). With a Galaxy→Sovereign pin
the boot loads DBridge then immediately swaps to EBridge inside the same
`Initialize` — exactly what stock BC does whenever the player's bridge choice
isn't Galaxy. It is the first runtime swap the host sees.

### Runtime swap reconciliation (new host work — build and live-verify FIRST)

`g_sBridgeType` has been `"GalaxyBridge"` in every live run to date, so
`LoadBridge.Load`'s "set exists, different config" branch (`LoadBridge.py:70`
— unload old animations/sounds, `DeleteObjectFromSet("bridge"/"viewscreen")`,
`DeleteCameraFromSet("maincamera")`, create the new model, restore the
viewscreen camera) has **never run under our engine**. The host realises the
bridge only in the post-load hook.

Design:

- Factor the bridge-specific part of `_after_mission_loaded`
  (`engine/host_loop.py` ~`:7767`) into `_realize_bridge(controller, r)`:
  `bridge_sounds.load_bridge_module_sounds`, the maincamera eye/zoom harvest
  (`_BRIDGE_CAMERA_EYE` etc.), `realize_set(controller, r, bridge_set,
  is_bridge=True)`. The post-load hook calls it exactly as today.
- Add a per-tick check beside `_reconcile_runtime_instances`: remember
  `bridge_set.GetConfig()` at the last realise on the controller
  (`controller.realized_bridge_config`); when the live value differs, call
  `_realize_bridge` again and update the memo. `realize_set(is_bridge=True)`
  already tears down the prior model/viewscreen/officer instances when it
  meets a **fresh carrier** — which a runtime `LoadBridge.Load` produces —
  so no new renderer work.
- **Not** re-run on a swap: `wire_after_mission_load`,
  `resolve_officer_menu_layout`, the hit-reaction re-registration.
  `LoadBridge.Load` on an existing set neither rebuilds menus nor recreates
  characters; it only re-`ConfigureCharacters` them.
- Skipped in hologram-only mode and when there is no `"bridge"` set.

This is the riskiest piece and goes **first** in the plan, with its live
check before any UI work.

## Section 3 — The Bridges tab

A fourth tab in `ConfigurationPanel`: `("bridges", "Bridges")`, rendered by
`native/assets/ui-cef/js/configuration_panel.js` from the same
`setConfigurationPanel(...)` payload, styled with the existing `cp-*`
classes. **No native `<select>`** — no CEF panel in the tree uses one (OSR
dropdown popups need popup-surface handling we don't have); both pickers are
in-panel lists.

The tab body is **two views** (revised 2026-09-19 after the first pass
shipped both on one page). The UI vocabulary is *mapping* / *mapped*; "pin"
stays the internal name (`BridgePins`, `bridges.json`) and never appears in
panel copy.

**List view** (default):

```
 Mapped
  Galaxy          Galaxy                 [✎] [✕]
  Sovereign       Sovereign              [✎] [✕]
  Akira           Sovereign              [✎] [✕]
  LCIntrepid      Voyager  (missing)     [✎] [✕]
  Default         Galaxy                 [✎]

 [            Add Mapping             ]
 Changes apply the next time your ship is created.
                                     [Reset to Defaults]
```

The **Default** row is the bridge every unmapped ship gets. It is always
present — even with no ships mapped — has Edit but no Remove, and is the
one row Reset restores rather than deletes (Reset deletes the file, so it
goes back to Galaxy). Its Edit opens the edit view with "Default" as the
fixed label; Save calls `set_default_bridge`.

Row actions are icon buttons (pencil = *Edit mapping*, ✕ = *Remove
mapping*) with page-drawn hover text: the host's `CefDisplayHandler` has no
`OnTooltip`, so a `title=` attribute never shows under OSR — `[data-tip]`
draws its own via a CSS `::after`, on hover and on keyboard focus, to the
left of the button so the scrolling body cannot clip it.

**Add Mapping view** (after *Add Mapping*; the tab strip and the panel's
Done footer stay put — Cancel / Save sit at the foot of the tab body):

```
 Add Mapping
  Ship                       Bridge
  ┌──────────────────┐       ( ) Galaxy
  │ Ambassador       │       (•) Sovereign
  │ Bird of Prey     │
  │ Galor        ▲▼  │
  └──────────────────┘
                              [Cancel]  [ Save ]
```

**Edit Mapping view** (a row's *Edit*): the same view with the ship fixed —
its label sits where the ship list would be, the picker starts on the
row's current bridge (or the first available one if that bridge is gone),
and Save re-points the mapping in place. Rows flagged *(not playable)* /
*(missing)* can be edited; that is exactly when re-pointing is wanted.

```
 Edit Mapping
  Ship                       Bridge
  ┌──────────────────┐       (•) Galaxy
  │ Akira            │       ( ) Sovereign
  └──────────────────┘
                              [Cancel]  [ Save ]
```

### Rules (enforced in Python; the JS is dumb)

- The ship list **excludes ships already mapped** — "once" is structural,
  not a validation message. Save is disabled until a ship is selected (the
  bridge pre-selects); Save writes the mapping and returns to the list view,
  where the ship has dropped out of the add list.
- *Add Mapping* is disabled (with "Every ship is mapped.") when no unmapped
  ship remains; `bridge:add_open` is refused the same way for keyboard
  activation.
- Cancel, ESC, switching tab, Reset and closing the panel all leave the add
  view and discard the selection. ESC on the add view is its Cancel — it
  does **not** close the panel; only the list view's ESC does.
- Ship/bridge selection and Save are add-view controls: dispatched outside
  the view they are refused.
- Edit changes a row's bridge only (`BridgePins.set_bridge`, which keeps
  file order and refuses an unmapped ship); the ship of a mapping never
  changes — that is Remove + Add.
- A row whose bridge is unavailable carries `bridge_missing: true`; a row
  whose ship is not in `available_ships()` carries `ship_missing: true`. The
  JS renders the *(missing)* / *(not playable)* suffix on the same row
  with the same Remove button.
- Reset on this tab calls `BridgePins.reset()` — per-tab, like the others,
  so it cannot touch graphics or keybindings.
- Bridge radio defaults to the first available bridge (Galaxy) each time the
  add view opens, so a one-click Save is possible; ship selection starts
  empty.

### Panel plumbing

- `ConfigurationPanel.__init__` gains an optional `bridge_pins: BridgePins |
  None = None` collaborator (like `input_map` for Controls); construction
  without it is unchanged and the tab is simply not offered.
- `render_payload` adds a `bridges` block — `pins: [{ship, ship_label,
  bridge, bridge_label, ship_missing, bridge_missing}]`, `ships: [{id,
  label}]` (unpinned only), `bridges_available: [{id, label}]`,
  `adding`, `edit_ship`, `edit_default`, `default: {bridge, bridge_label,
  bridge_missing}`, `add_ship`, `add_bridge`, `can_add` — and folds it into the
  change-detection snapshot so the push happens only on change.
- Actions: `bridge:add_open`, `bridge:edit:<stem>`, `bridge:edit_default`, `bridge:cancel`,
  `bridge:ship:<stem>`, `bridge:bridge:<script>`, `bridge:add` (Save — adds,
  or re-points when editing), `bridge:remove:<stem>`, `reset:bridges`. All go through `dispatch_event`
  and are best-effort: a `DuplicateShip` / `UnknownBridge` from `add` (only
  reachable by a race with a hand-edit) is swallowed and the payload
  re-pushed.
- `_focusables` gains the tab's rows in rendered order per view — list
  view: each mapped row's Edit then Remove, the Default row's Edit, Add
  Mapping, Reset; add view:
  ship list (omitted when editing), bridge radios, Cancel, Save — so
  keyboard/gamepad navigation keeps
  working. Focus resets on a view change because the list changes shape.

## Section 4 — Testing

All headless; the gate is `scripts/check_tests.sh`.

- `tests/unit/test_bridge_selection.py` — default pins when the file is
  absent; authoritative when present, including `{}`; unpinned ship →
  `GalaxyBridge`; missing bridge → `GalaxyBridge` + exactly one log line +
  the pin is **not** removed; `add` rejects a duplicate ship and an unknown
  bridge; `reset` deletes the file; corrupt file quarantined to `.corrupt`
  and defaults used; labels from `Ships.tgl` with stem fallback; ship
  universe from SDK + mod overlay (fake install tree, `# paths-guard:`
  exempted), case-deduplicated; `_scan_mod_bridges` contract test (fake
  `mods/x/scripts/Bridge/FooBridge.py` with and without
  `def CreateBridgeModel(`) — marked `xfail(strict=True)` naming the
  follow-up feature. Not `tests/known_failures.txt`: that ledger is for
  regressions the gate must catch, and `strict=True` flips the test to a
  hard failure the moment the follow-up makes it pass, so it cannot be
  forgotten.
- `tests/host/test_quickbattle_bridge_hook.py` — the wrap sets
  `g_sBridgeType` from the matrix before the original `RecreatePlayer` runs,
  for all four callers (`Initialize`, `StartSimulation2`, `EndSimulation`,
  `ShipDestroyed`); installed on every `load_quickbattle`; never
  double-wrapped; a pin changed between two recreations is honoured by the
  second.
- `tests/host/test_bridge_runtime_swap.py` — after `LoadBridge.Load
  ("SovereignBridge")` on a live `GalaxyBridge` set, the per-tick check calls
  `_realize_bridge`; the old bridge/viewscreen/officer instances are
  destroyed and new ones created; the camera eye is re-harvested;
  `wire_after_mission_load` is **not** re-run; no-op when the config is
  unchanged.
- `tests/ui/test_configuration_panel_bridges.py` — payload shape; each
  action; pinned-ship exclusion from the picker; Add disabled until both
  selected; per-tab reset scoped to bridges only; `_focusables` ordering;
  construction without `bridge_pins` unchanged (no tab, no payload block).
- Existing `test_every_setting_key_is_unique_and_in_a_known_section`
  untouched.

### Live verification (Mark, in order)

1. Pin Galaxy → Sovereign, boot QuickBattle: EBridge after the boot
   double-load, officers seated, viewscreen live, ambient/beeps sane.
2. Set As Player Ship → Akira mid-session: bridge follows on recreate.
3. End Combat: ship **and** bridge revert.
4. Remove the Akira pin, relaunch: Akira gets DBridge.
5. Hand-edit `bridges.json` to a bogus bridge: *(missing)* in the panel,
   DBridge loads, one boot-report line names the pin.

## Out of scope (named so it isn't crept in)

- The `_scan_mod_bridges` body (next feature; contract above).
- Campaign / tutorial missions — override by construction.
- An in-game "apply now" bridge reload.
- Multiplayer wiring — a one-liner at its player-creation point once that
  mode exists.
- Our three dev missions (`ship_preview`, `damage_preview`, `combat_stress`)
  keep their literal `LoadBridge.Load("SovereignBridge")`.
- Reacting to `bridges.json` changing on disk while the game runs — it is
  read at boot and rewritten on each panel edit; there is no file watcher.
- Foundation's `sBridge` ship attribute (24 uses in the corpus, all
  `'galaxybridge'`) stays in `unknown_attributes`; a later feature may
  layer it under the player's pins.

## Files touched (expected)

| File | Change |
|---|---|
| `engine/bridge_selection.py` | new — registry, ship universe, `BridgePins`, `install_quickbattle_hook` |
| `engine/host_loop.py` | construct `BridgePins`; `_realize_bridge` factoring + per-tick config check; hook install in `load_quickbattle`; pass `bridge_pins` + Bridges tab to `ConfigurationPanel` |
| `engine/ui/configuration_panel.py` | optional `bridge_pins`; payload block; actions; focusables |
| `native/assets/ui-cef/js/configuration_panel.js`, `css/hello.css` | Bridges tab rendering |
| `tests/unit/test_bridge_selection.py`, `tests/host/test_quickbattle_bridge_hook.py`, `tests/host/test_bridge_runtime_swap.py`, `tests/ui/test_configuration_panel_bridges.py` | new |
| `CLAUDE.md` key-reference table | one row pointing here |
