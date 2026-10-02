# Quick Battle setup screen and battle start: Design

**Status:** implemented on `feat/qb-setup-screen`, awaiting live check (§8). Approved in brainstorm 2026-10-02. Sections below are corrected to what was BUILT where the build departed from the brainstorm text (§2, §3.2, §3.3, §4.1, §4.3, §4.4, §4.5, §6).
**Date:** 2026-10-02
**Programme:** sub-project 2 of `2026-10-01-quickbattle-redesign-roadmap.md`.
Its "Standing decisions → Setup screen" bind this spec and are not restated in
full here.
**Depends on (all merged):**
- sub-project 1, `2026-10-01-ship-metadata-catalog-design.md` (`engine/ship_catalog/`)
- sub-project 3, `2026-10-01-mod-ships-screen-design.md` (class formation via
  `variant_of` / `class_default`)
- `2026-10-02-cef-text-input-keyboard-capture-design.md` §4.4 (the panel contract
  for text fields)

**Design reference:** the approved spike, `spikes/quickbattle-setup/` on branch
`spike/quickbattle-setup` at commit `e11c4af1` (worktree
`.claude/worktrees/qb-setup-spike`). Run its `build_assets.py`, then open
`index.html`.

## Intent

Replace today's Quick Battle setup panel (which walks BC's `g_pShipsPane` widget
tree) with the spike's screen, built on the ship catalog. Replace BC's
`GenerateShips` (everything spawns 200 GU ahead with random jitter) with group
placement. Each group has an allegiance, a direction, a distance, a difficulty
and named ships. The setup is remembered between battles within a run, player
ship included.

**Success:**
- The screen matches the spike's UX, side by side.
- A battle spawns each group where its Details say, deterministically.
- Named ships carry their hull name (where masks exist) and their display name.
- Neutrals stay inert and never count toward the win.
- Win, End Combat and reopen show the same setup and the same player ship.

## Decisions taken in the brainstorm (2026-10-02)

| # | Question | Decision |
|---|---|---|
| D1 | Split 2a / 2b? | **No.** One spec for screen, data, spawning and named ships. The plan lands the screen first. Condition-builder **objectives** ("no more than X neutrals killed", "enemies must not reach Y") become a new sub-project **2c**. |
| D2 | In-game typing | Solved first as its own piece (keyboard capture, merged `751fa00e`). This spec only follows its §4.4 contract. |
| D3 | How much of SDK `QuickBattle.py` survives | **Replace only `GenerateShips`**, with a module-global wrap (the `install_quickbattle_hook` pattern). BC's start chain, preload, AI assignment, win/lose, End Combat and `RecreatePlayer` all stay. Rejected: owning the whole chain (re-verifying lots of BC behaviour for no gain); post-moving BC's spawns (fights its jitter and collision retry). |
| D4 | Placement | Deterministic, no jitter. Line abreast across the direction axis, rows of 5, radius-based gaps. Enemy groups face the player; friendly and neutral groups keep the player's heading. Escorts sit line abreast beside the player, alternating starboard and port. |
| D5 | AI difficulty | **Per group:** Low / Medium / High in Details, default Medium. The player's group gets a Details form with only this row. Free in the SDK: `g_kShips` carries a per-ship level. |
| D6 | Neutrals | **Inert:** in the mission's neutral group, no AI, no `g_kShips` entry, never counted toward the win, no Felix line. A neutral turning hostile when provoked is not built (BC scripts that per mission; it would change the win rule mid-battle). |
| D7 | Win/lose | **BC's, unchanged:** every Enemy-group ship destroyed is a win (the battle continues until End Combat); player death is a loss. A battle with no enemy group has no win condition. |
| D8 | Persistence | **Within a run only.** The current setup, filters and last-preset name live in memory: they survive battles, End Combat, Restart and closing the screen, but **not** quitting the game. Every launch starts from the default setup with the Galaxy. Only presets are on disk. |
| D9 | Ship names | The object name stays BC-style and unique (`Galaxy-1`). The display name is the named ship (the row's pick, else the class default); a class without variants keeps `<Title>-N`. Duplicate picks get an ordinal: `USS Dauntless (2)`. The player gets the same treatment. Hulls without masks get the display name and render nameless. |
| D10 | Small items | Deleting a group **with ships** asks first. Presets can be deleted (× per row, with confirmation). Loading a preset over unsaved changes asks first. Battles stay where the player is (no Change Combat Region). Start needs at least one non-player ship. |
| D11 | Fidelity to the spike | **As close to the spike's UX as possible.** Markup, layout, spacing, states and copy are ported. The only additions are D5's Difficulty row and D10's confirmations and preset ×, each built from the spike's existing pieces. |

## 1. Units

A new package, `engine/quickbattle/`. Everything except `spawn` is pure and
testable without the engine.

| Unit | Job |
|---|---|
| `scenario.py` | Data model (§2), defaults, invariants, JSON round-trip, reconciliation against the catalog, `battle_plan()`. |
| `presets.py` | `quickbattle_presets.json` beside `settings.json`, through `SettingsStore` (the `bridge_selection` pattern). |
| `stats.py` | Hull and shield-total probe per catalog ship, plus the playable maxima (§5). |
| `placement.py` | Pure placement maths (§4.4). No App calls: takes plain vectors and radii. |
| `naming.py` | Object names and display names (D9). |
| `spawn.py` | The provider, `sync_sdk`, `install_generate_ships_hook(qb)` and `apply_player_identity` (§4). |

**Rewritten:**
- `engine/ui/quick_battle_setup_panel.py`: a state machine over a `Scenario`, with no BC widget reads (§3).
- `native/assets/ui-cef/js/quick_battle_setup.js`
- `native/assets/ui-cef/css/quick_battle_setup.css`
- the panel's section of `native/assets/ui-cef/index.html`

**Removed:**
- `_sync_quickbattle_player_revert` and its per-tick call (`engine/host_loop.py`). This is why the player ship survives End Combat.
- the old panel's `g_pShipsPane`, `g_pFriendMenu` and `g_pEnemyMenu` reads and their event verbs.

**Kept:**
- `_inject_quickbattle_player_defaults` (boot is still the Galaxy, D8)
- `_sync_quickbattle_spawn_set`
- `_sync_quick_battle_panel` (open and close follow `g_bDialogUp`)
- `foundation.quickbattle.register` (its detail-table rows still give each ship file its AI module and destroyed line)
- `bridge_selection.install_quickbattle_hook`

## 2. Data model (`scenario.py`)

```
Scenario { groups: [Group] }
Group    { id, name, custom_name: bool, player: bool,
           allegiance: "friendly" | "enemy" | "neutral",
           direction:  "fore" | "aft" | "port" | "starboard" | "dorsal" | "ventral" | None,
           distance:   "close" | "standard" | "long" | "out_of_range" | None,
           difficulty: "low" | "medium" | "high",
           entries: [Entry] }
Entry    { id, ship: <CatalogEntry.ship_id>, variant: <Variant.name> | None, player: bool }
```

- **Enums are string ids**, never indices.
- **Distances:**

  | id | km | GU |
  |---|---|---|
  | close | 20 | ≈114 |
  | standard | 35 | 200 |
  | long | 80 | ≈457 |
  | out_of_range | 150 | ≈857 |

  km → GU via `engine/units.py` only.
- **Ids** are short random strings, stable for an object's life. Panel events address objects by id, and 2c's conditions will too.
- **`variant: None`** means the class default (`variants[0]`).
- **Default scenario:**
  - "Friendly group": the player group, holding the player Galaxy, difficulty medium.
  - "Enemy group": enemy, fore, standard, medium, empty.
  - The Enemy group is the add target.
- **New group:** enemy, fore, standard, medium. Its name comes from `autoName`: "Enemy group", "Enemy group 2", … using the first free number.
- **Unedited names follow allegiance.** If Details changes the allegiance and `custom_name` is false, the name is re-derived. Rename sets `custom_name`.
- **Invariants** (enforced here, not by the UI):
  - Exactly one player group and exactly one player entry, and it's in that group.
  - The player group's allegiance is always `friendly`, and its direction and distance are `None`.
  - The player entry's ship must be playable; a player variant must be playable (`Variant.playable`, else the entry's flag).
  - The player entry can't be removed or moved, and the player group can't be deleted.
  - "Set as player ship" swaps the player entry's ship in place and resets its variant to `None`.
- **Reconciliation** (on loading a preset, and on a catalog generation change):
  - an unknown ship's row is dropped;
  - an unknown variant goes back to `None`;
  - an unknown or non-playable player ship becomes `Galaxy` if it is installed and playable, else the **first playable ship** in the catalog. The player entry is **never dropped** — not even when its ship is uninstalled and no fallback exists (then it is left as is and logged), so the "exactly one player entry" invariant holds through any catalog change.

  Each drop is logged once.
- **`battle_plan(scenario, catalog) -> BattlePlan`:**
  - A player order: the ship file to spawn (the variant's `script`, else the class `ship_id`), the registry, the display name.
  - Per non-player entry, in group order then row order, a spawn order with:
    - the ship file;
    - the class `ship_id` (for the detail-table lookup);
    - title, registry and display name;
    - allegiance, direction, distance in GU, and the AI level (low 0.0, medium 0.5, high 1.0).
  - Derived, never stored.
- **`can_start`:** at least one non-player entry exists in any group.
- **Comparison for "unsaved changes":** two scenarios are equal when they are equal after dropping ids.

## 3. The screen

### 3.1 Fidelity

The spike is the reference (D11). Port its markup structure, classes (renamed
into the panel's namespace), layout, spacing, colours, states, empty states and
copy. Use the cp-\* family (`configuration_panel.css`) as the spike does. No
drag-and-drop, no native `<select>`, no `title=` tooltips.

**Additions:**
- **Difficulty:** a segmented row in Details, after Distance.
- **The player group's Details:** only the Difficulty row.
- **Confirmations:** one shared overlay in the spike's "Overwrite preset?" style. It is used for:
  - "Delete ‹group› and its N ship(s)?" (only when the group has ships)
  - "Delete preset ‹name›?"
  - "Overwrite preset?" (as in the spike)
  - "Load ‹name›? Your current setup has unsaved changes." (only when dirty)
- **A × on each row** of the Load preset menu.

### 3.2 State ownership

Python owns all state:
- the scenario and the add target;
- the selected card (the sheet);
- the Details draft and the confirmation (a pending confirmation is **modal**: every verb except `confirm`, `cancel`, `esc` and `close` is refused while it is up, so nothing can change the scenario its action was asked about);
- the era and species filters;
- the preset names, the current preset name, the dirty flag and `can_start`.

The JS renders what it is sent. It owns only the open popover menu, which
closes on re-render or an outside click (the `mods_screen.js` pattern), and
**the rename in progress**: there is no rename-start verb. The page shows the
inline field itself and reports only the committed result (`rename:<gid>:<urlenc>`,
§3.5).

### 3.3 Pushes (Python → JS)

- **`setQuickBattleCatalog(payload)`** is pushed when the screen opens and when the catalog generation changes. It carries:
  - **per class:** id, title, species, role, era span, playable, variants (name and playable), icon data URL (`ship_icons`), bio, and hull and shield total (or null);
  - the hull and shield maxima;
  - the era, role and species tables. Each species row has an insignia `file://` URL, or else the flagship's icon;
  - the Details tables, so the page never hard-codes a label: `allegiances` (`{id, label}`), `directions` (`{id, label}`), `distances` (`{id, label, km}`) and `difficulties` (`{id, label}` — Low / Medium / High).
- **`setQuickBattleSetup(payload)`** carries the §3.2 state, and is skipped when unchanged (`_last_pushed`). Its `confirm` is `null` or `{title, name, body, ok, before, after}`: `body` is the whole sentence, and `before` / `after` are the text around `name`, so the page bolds the name **by position** (never by searching the sentence for it — "set" would hit "setup").
- **Bio:** from `Ships.tgl`'s "‹name› Description", with the "Shield Rating" and "Hull Rating" lines stripped. With no entry the sheet shows "No description available."

### 3.4 Events (JS → Python)

All events are `dauntlessEvent('quick-battle-setup/<verb>')`, addressed by id:

| Area | Verbs |
|---|---|
| Filters and sheet | `era:<id>` · `species:<name>` · `select:<ship>` (toggles the sheet) |
| Adding ships | `add:<ship>` · `set-player:<ship>` |
| Groups | `target:<gid>` · `group-new` · `details:<gid>` · `draft:<field>:<value>` · `draft-update` · `draft-cancel` · `rename:<gid>:<urlenc>` · `group-delete:<gid>` |
| Ship rows | `variant:<eid>:<urlenc or empty>` · `move:<eid>:<gid>` · `remove:<eid>` |
| Presets | `preset-load:<urlenc>` · `preset-save:<urlenc>` · `preset-delete:<urlenc>` |
| Dialogs | `confirm` · `cancel` |
| Footer | `start` · `close` · `esc` |

- Python validates every verb. An unknown id or verb is logged and ignored.
- These verbs can raise a confirmation instead of acting: `group-delete` (group with ships), `preset-delete`, `preset-save` (existing name), and `preset-load` (when dirty). `confirm` then performs the pending action.

### 3.5 Text fields

Rename and the preset-name input follow the keyboard-capture contract (keyboard spec §4.4):
- `data-panel="quick-battle-setup"` on the panel root;
- commit on the DOM `change` event;
- expect an edit to be abandoned on Esc, on panel close and on mission swap.

An empty or unchanged value is ignored.

### 3.6 Esc

With no text field focused, the game's Esc reaches the panel's `handle_key_esc`:
1. It runs the page's `qbEscape()`.
2. That closes the popover menu if one is open.
3. Otherwise it sends `esc`. Python then closes the innermost of: confirmation → Details draft → sheet → the screen (as `close`).

### 3.7 Open, close, start

- **Open:** unchanged. The XO's "QuickBattle Configuration" → `g_bDialogUp` → `_sync_quick_battle_panel`. BC disables that button for the whole battle, so the screen never opens mid-battle.
- **Close:** fires `ET_CLOSE_DIALOG`, as today.
- **Start:** only when `can_start`. It fires `ET_CLOSE_DIALOG`, then `on_start()` (→ `start_quickbattle`), then closes.
- **The XO's "Start Simulation" button** is enabled or disabled from `can_start` whenever the scenario changes outside a battle. BC did this in `AddShipAs*`, which is no longer called.

## 4. Battle start

### 4.1 The provider and the SDK sync

- **`spawn.set_provider(fn)`** registers a zero-argument callable that returns the **current** `BattlePlan`, or `None`. The panel registers itself at construction.
  - The plan is computed at call time, never cached, so XO **Start Simulation** and **Restart** (which bypass the screen) spawn the current setup.
  - With no provider, or a provider returning `None`, every hook falls back to BC's original behaviour. This is how headless tests that fill `g_kEnemyList` directly keep working.
- **`spawn.sync_sdk(qb, plan)`** runs on every scenario change outside a battle, and once at Start. It:
  - sets `g_sPlayerType` from the player order;
  - writes `g_kFriendList` / `g_kEnemyList` as preload manifests, in BC's 6-tuple shape. Neutrals are included (in `g_kFriendList`), so `StartSimulationAction` preloads every model. **They are not write-only:** `StartSimulation2` runs `if len(g_kEnemyList) > 0: bWonOrLost = 0` right after `GenerateShips()` to arm the win, so our `generate_ships` writes the manifests too, from the plan it spawns — a hook-driven Start arms the win even if nothing called `sync_sdk` first. (BC's own fallback `GenerateShips` has no neutral concept, so with no provider a neutral manifest spawns as an ordinary friendly — accepted, since that path runs BC unmodified.);
  - enables or disables the XO's Start Simulation button from `can_start` (§3.7).

### 4.2 Start Battle (`_MissionLoader.start_quickbattle`, extended)

1. `_sync_quickbattle_spawn_set()`.
2. `spawn.sync_sdk(qb, provider())`.
3. Post `ET_START_SIMULATION` to `g_pXO`, as today.

BC then runs: loading text → preload → `StartSimulation2` → `RecreatePlayer()`
→ `GenerateShips()` (ours) → AI from `g_kShips` → red alert. Restart replays the
current plan.

### 4.3 The player

- **Ship type:** `g_sPlayerType` is already right, because `sync_sdk` set it. `RecreatePlayer` (and the bridge hook around it) is untouched.
- **Hull name and display name** are applied by `spawn.apply_player_identity(player)` in two places:
  - in `generate_ships`, before radii are seeded (so the registry-keyed model load matches the one realisation makes);
  - in QuickBattle's reconcile step (`engine/host_loop.py`, the `session.mission_name == "QuickBattle"` block in `_reconcile_runtime_ships`), for every newly created, not-yet-realised player. That covers battle start, End Combat and a death outside the battle.

  It queues the player order's registry (§4.6) and sets its display name. It is idempotent (last write wins per texture slot). Fallbacks to `registry_texture.apply_class_default`: no provider or no plan, **or a class mismatch** — a live player whose `ships.<Leaf>` script is not the plan's player ship file never gets another ship's registry and name.

  ⚠️ The reconcile block has **no `has_replacements` guard** (the brainstorm assumed one). BC's `MissionLib.CreatePlayerShip` pre-queues the class's default NCC on every Federation player it (re)creates, so that guard skipped every Fed player and the named ship never applied. The scenario's named player is authoritative over that default.
- **"Set as player ship"** only changes the scenario (and, through `sync_sdk`, `g_sPlayerType`). The new ship appears at the next `RecreatePlayer`: at battle start, or after End Combat.

### 4.4 Placement (`placement.py`)

- **Axes:** read from the player's world rotation **after** `RecreatePlayer`:
  - fore = `GetCol(1)`, aft = −fore
  - starboard = `GetCol(0)`, port = −starboard
  - dorsal = `GetCol(2)`, ventral = −dorsal

  (right-handed, CLAUDE.md)
- **Anchor:** `player_pos + axis × distance_gu`, centre to centre.
- **Formation (non-player groups):** a line abreast across the direction axis.
  - The lateral axis is starboard for fore, aft, dorsal and ventral, and fore for port and starboard.
  - Slots alternate outwards from the anchor: 0, +1, −1, +2, −2.
  - Rows hold up to 5 ships. Each further row sits one row-gap further from the player along the axis.
  - Slot spacing in a row is the two neighbours' radii plus a margin.
  - The row gap is the largest radius in the two rows plus the margin.
  - The margin is a named constant.
- **Escorts (the player group's non-player entries):** line abreast beside the player, slot 1 starboard, slot 2 port, alternating outwards, spaced by radii plus the margin. Same heading as the player.
- **Facing:**
  - Enemy ships face the player: `AlignToVectors(toward player, player up)`, as BC does.
  - Friendly and neutral ships take the player's rotation.
- **Radii are seeded early.** Nothing is realised at `GenerateShips` time and a ship's `GetRadius()` is normally seeded only at realisation, so every created ship and the just-recreated player report **0** — spacing would collapse to the margin and hulls overlap. `spawn.set_radius_fn(fn)` registers the host's seeder (`_MissionLoader._seed_quickbattle_ship_radius`, registered at QuickBattle boot), which loads the class's model through the same runtime load realisation uses (the native load dedupe makes realisation's later call free) and seeds the radius. `generate_ships` seeds every created ship and the player before placement.
- **Occupied slots:** `Set.IsLocationEmptyTG` is a stub that always reports empty, and two groups with the same direction and distance share an anchor. So each placement is also checked against a **within-call overlap list** (every ship placed so far in this `GenerateShips`, exact distance against both radii plus the margin). On a clash, nudge outwards along the lateral axis by `2·radius + margin` (never one radius — a zero radius would never move), up to a bounded number of tries, then accept.
- **No randomness.** The same scenario and the same player pose give the same positions.

### 4.5 `GenerateShips` (ours, `spawn.py`)

`install_generate_ships_hook(qb)` replaces `qb.GenerateShips` at
module level. It is idempotent, and marked and unwrappable like the bridge
hook. The replacement mirrors BC's preamble and then spawns.

1. Reset `g_iNumFriends` and `g_iNumEnemies`, and empty `g_kShips`. `RemoveAllNames` on the friendly, enemy **and neutral** groups (`pMission.GetNeutralGroup()`), then re-add the player to friendlies.
2. For each spawn order:
   - **Create:**
     - `loadspacehelper.CreateShip(ship_file, g_pSet, "<Title>-N", "")`, with N a running index across the battle.
     - Then `SetDisplayName(display_name)`.
     - If the order has a registry, `ReplaceTexture(<path>, "ID")` **before the ship is realised** (§4.6).
   - **Place and face** (§4.4); update the proximity manager as BC does.
   - **Group membership:** `AddName` to the friendly, enemy or neutral group by allegiance.
   - **Friendly and enemy only:** `g_kShips[objID] = (ai_module, destroyed_line, side, ai_level)`.
     - `ai_module` and `destroyed_line` come from BC's detail tables (`g_dFriendlyShipTypeToDetails` / `g_dEnemyShipTypeToDetails`, stock plus Foundation-registered rows), looked up by the class's ship file.
     - Fallbacks: `QuickBattleFriendlyAI` / `QuickBattleAI` and BC's generic destroyed lines.
     - Enemies increment `g_iNumEnemies`; friendlies increment `g_iNumFriends`.
   - **Neutral:** nothing more (D6).
3. **Failure handling:**
   - If one ship fails to create or place, log it and continue with the rest.
   - Fall back to BC's original `GenerateShips` (over the manifests, logged loudly) **only if the hook raises before any ship is created**. Once a ship exists, any failure in the placement pass is logged and swallowed: falling back then would spawn BC's whole roster on top of ours.

### 4.6 Named ships

- **The registry path** is `Data/Models/Ships/<class model dir>/<Registry>.tga`, or the class's path in `registry_texture.DEFAULT_REGISTRY_BY_CLASS` when it is the class default.
- Only the file stem matters to `hull_decals.resolve_registry`. The native loader resolves textures by basename, and a missing texture leaves the hull nameless.
- **Script variants** spawn their own script and get a registry only if the variant itself declares one. The class default's registry never applies to them.
- **The class default's registry** is `variants[0].registry`, else `DEFAULT_REGISTRY_BY_CLASS`.
- **Display names** (`naming.py`):
  - the variant name, else `<Title>-N`;
  - the second and later uses of the same name in one battle get " (2)", " (3)", …;
  - the player counts first.

## 5. Stats probe (`stats.py`)

The engine's primary hull is the **first** `HullProperty` in the property set
(`engine/appc/ships.py:1238`). The probe follows BC's own loader sequence
(`loadspacehelper.py:88-91`):

1. **Find the hardpoint file:** import `ships.<ship_id>` (mod overlay, stats overlay) and read `GetShipStats()["HardpointFile"]`.
2. **Snapshot** `g_kModelPropertyManager`'s local templates.
3. **Load:** `ClearLocalTemplates()`, reload `ships.Hardpoints.<file>` (our hardpoint override pass fires here), then `LoadPropertySet(scratch)`.
4. **Read the values:**
   - **hull** = the first `HullProperty`'s `GetMaxCondition()`;
   - **shields** = Σ `ShieldProperty.GetMaxShields(face)` over faces 0–5.
5. **Restore** the snapshot in a `finally`.

**Caching and maxima:**
- The probe runs lazily on the first screen open and is cached per catalog generation.
- The maxima are the largest hull and the largest shield total over **playable** classes.
- A value above the maximum renders capped and gold, tagged "off scale".

**When a ship has no data:** a probe failure gives `None`, and the sheet shows "No hardpoint data for this entry." Never parse hardpoint text, and never show `Ships.tgl`'s rating lines.

## 6. Presets file (`presets.py`)

```
quickbattle_presets.json
{ "version": <SettingsStore schema version>,
  "presets": { "<name>": { "saved_at": "<ISO 8601>", "scenario": { <scenario JSON> } } } }
```

- `default_presets_path()` = `settings_store.default_settings_path().parent / "quickbattle_presets.json"`. It is resolved at use, never captured at import.
- `SettingsStore` semantics: an absent file means no presets; a corrupt one is renamed `.corrupt`; writes are atomic. Failures are logged and swallowed.
- The top-level `version` is `SettingsStore`'s own schema version (the file is a `SettingsStore` file with one `presets` section), not a presets-format number.
- API: `names()`, `load(name) -> Scenario | None` (**raw**, not reconciled — `presets.py` has no catalog dependency; the panel reconciles the loaded scenario against its catalog index before using it), `save(name, scenario)`, `delete(name)`, `exists(name)`.
- Names are trimmed, and empty names are refused. Preset names sort with a case-insensitive sort.

## 7. Testing

| Area | Coverage |
|---|---|
| `scenario` | defaults; every invariant; set-player; autoName and allegiance-follow; reconciliation (unknown ship, unknown variant, unplayable player); JSON round-trip; `battle_plan` (ship file for script variants, registry, AI levels, GU distances); `can_start`; id-free equality |
| `presets` | absent, corrupt, save, overwrite, delete, names order, path resolved at use |
| `placement` | all six axes; lateral axis choice; slot order; row breaks at 5; gaps from radii; escort sides; facing per allegiance; determinism; nudge on occupied |
| `naming` | object names; display names; ordinals with the player first; classes without variants |
| `stats` | stock values (Warbird hull 24,000; Sovereign shield total 49,500); templates restored after the probe; a hardpoint override wins; probe failure gives `None`; playable-only maxima |
| Panel | every verb; confirmations; Esc layers; dirty detection; filter counts; `can_start`; the XO Start button synced |
| `spawn` (host) | `g_kShips` contents and AI levels; neutral membership with no `g_kShips` entry; `g_iNumEnemies`; the registry queued before realise; display names; failure isolation; the fallback to BC's original; idempotent install |
| JS / HTML | source-shape tests: `data-panel`, `qbEscape`, no `<select>`, no `title=`, both entry points |
| E2E (headless) | Start a scenario with Enemy fore Standard and Neutral port Close. Check positions and groups. Destroy all enemies → win sequence. Destroy the player → loss. End Combat → the player ship type is unchanged and the setup is intact. |

Tests that encode removed behaviour are rewritten or deleted in the same change:
the old panel's tests, and the revert hook's tests. The gate is
`scripts/check_tests.sh`.

## 8. Live checks (Mark)

1. The screen beside the spike: layout, pills, catalog, sheet, scale bars, group menus, presets.
2. Enemy fore Standard and Neutral port Close: placement, facing, neutral colours, neutrals inert.
3. Ambassador USS Excalibur as the player: hull name and display name.
4. Win → End Combat → reopen: same setup, same player ship.
5. Typing in Rename and preset names fires no game keys.

## Open for Mark

- **Enter on an UNCHANGED pre-filled preset name does nothing.** In the spike it overwrites the current preset. The page commits text on the DOM `change` event (§3.5), and an unchanged value fires no `change`. Fixing it needs a keyboard-capture contract extension (e.g. a commit event on Enter), not a page-only change.

## Out of scope

- **Objectives / condition builder (2c).**
- **Provoked neutrals.**
- Per-group AI orders beyond difficulty.
- Change Combat Region.
- Persisting the current setup across launches.
- Authoring hull-name masks for Galaxy, Nebula and Akira.
