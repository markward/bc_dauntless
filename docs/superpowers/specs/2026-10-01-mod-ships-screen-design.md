# Mod Ships screen: metadata gate and mod-manager home — Design

**Status:** spec, awaiting review
**Date:** 2026-10-01
**Programme:** Quick Battle redesign, sub-project 3. Its authority is
`2026-10-01-quickbattle-redesign-roadmap.md`. It builds on sub-project 1,
`2026-10-01-ship-metadata-catalog-design.md`, which is merged; §2 below
changes two of that spec's rules.
**Design reference:** the approved spike `spikes/mod-metadata-gate/` on
branch `spike/mod-metadata-gate`. The spike's *design* is approved; its code is
throwaway. Run its `build_assets.py` per its README, then open `index.html`.
The URL hashes `#starred`, `#typed` and `#continue` show the main states.

## Intent

Mod ships arrive without Dauntless metadata (era, role, species, playable,
title, and class membership). Every installed mod in the corpus is in that state
today: DCMPv2's 12 ships and LC Intrepid Pack's 3. This sub-project provides:

1. **A pre-boot "Mods" screen.** In **gate mode** it stops boot until the
   missing metadata is supplied, or the player skips or quits. In **home mode**
   it is a read-only list of installed mod ships, and is the placeholder home of
   a future mod manager.
2. **Two ways to reach home mode:** a `--mods` launch flag, and a pause-menu row
   **Quit and Manage Mods** that shuts down and relaunches into it.
3. **Keyboard input into CEF.** No typed field could receive characters until
   now. Built here, for the pre-boot screen only.
4. **A class model in the catalog.** Ships group into classes by a free-text
   class **name**, with one starred **class default**.
5. **A fix to the Foundation shim**, which drops `SubMenu`/`SubSubMenu` passed in
   a ship definition's `details` dict.

**Success:** booting with the two installed mods lands on the gate. Filling the
table and pressing Continue writes one `zz_Dauntless_<shipFile>.py` per ship and
boots with no reboot. On the next launch nothing is asked, and
`ship_catalog.describe()` reports no incomplete entries. In the catalog,
DCMPv2's twelve ships are one Defiant class with Defiant as default.

## Decisions taken in the brainstorm (2026-10-01)

| # | Question | Decision |
|---|---|---|
| D1 | Typing a title (CEF has no keyboard path) | **Build CEF keyboard forwarding** as part of this sub-project, because other features need it too. |
| D2 | Many incomplete ships | **One screen for all of them**, grouped by mod. Superseded in shape by D8. |
| D3 | Pre-fill from what the mod already says | **Yes:** title from `name`, species from race, playable from the player-menu registration, role **Tactical** ("most new ships are tactical"). Era starts blank. |
| D4 | Escape besides answering | **Skip for now:** boot with the incomplete ships left out of Quick Battle for this session, and ask again next launch. Quit is also offered. |
| D5 | Variants of one class (DCMPv2's Defiants) | Variant-of is declared on the **child**. Refined by D9. |
| D6 | Era display | **Lead with the era code** (`DS9 · VOY`) everywhere, with the name secondary. This matches the Quick Battle spike. |
| D7 | Inferred grouping | **Pre-fill Variant of from `SubMenu`** (minus a trailing "Class"). Rows without a `SubMenu` start blank. The shared-icon signal shown in the spike is **not** used. |
| D8 | Screen layout | **A table:** one row per ship and one column per value, with page-drawn cell pickers. **Ticked rows:** an edit to one ticked row applies to every ticked row. |
| D9 | What "Variant of" holds | **Free text, a class name**, with quick-pick from values typed on other rows and stock class names. A class has exactly **one starred default**. |
| D10 | Scope versus a mod manager | The screen is the **placeholder home of the future mod manager**: read-only in home mode for now. Enabling and disabling mods is a later phase. |
| D11 | Reaching home mode | **Both** the `--mods` launch flag and a pause-menu **Quit and Manage Mods** relaunch. |

## 1. The screen

### 1.1 Layout

The screen uses the cp-* modal family: the runtime `configuration_panel.css`,
not `docs/ui_designs/08`. It has the header "New mod ships need details" in gate
mode and "Mod Ships" in home mode, one sentence of explanation, a table, and a
footer.

**Table columns, in order:** tick box, icon, **Title** (typed, with the
`shipFile.py` underneath in small text), **Variant of** (typed),
**Default** (★), **Era**, **Role**, **Species**, **Playable**. A header row per
mod shows its name, its ship and class counts, and a tick box that ticks the
whole mod.

**Cell behaviour.** Everything is page-drawn: no native `<select>` and no
native tooltips, as required by off-screen CEF.

| Cell | Behaviour |
|---|---|
| Title | A real `<input>`. A blank title marks the row incomplete. |
| Variant of | A real `<input>`. Focusing it opens a list of names typed on **other** rows, with counts ("Defiant · 11 ships"). Once the player types, a **Stock classes** section lists stock titles that match. The list ends with **Clear (own class)**, and narrows as the player types. Blank means the ship is its own class. |
| Default | Shown only on rows that name a class. ★ marks the default and ☆ the other members; clicking ☆ moves the star. For a **stock** class name it reads *stock default* and cannot be clicked. |
| Era | A From/To picker: two columns of `tag` (bright) and name (dim), plus **All eras (timeless)**. Picking From beyond To, or To before From, drags the other end along. |
| Role | A list of four: Tactical, Auxiliary, Station, Automated / Unmanned. |
| Species | The species already in the catalog (`ship_catalog.species()`), plus **New…**, which turns the cell into a typed field. |
| Playable | Yes or No. Once set, a click flips it. |

**Missing values** show in the warning colour (`set…`).

**Ticked rows.** While any row is ticked, a bar reads "N ticked — any edit to a
ticked row applies to all N", with a Clear button. Every edit made on a ticked
row, including typing in Variant of, applies to all ticked rows.

**Footer.** Quit sits on the left. On the right are a status line ("N ships need
details: …", or "All ships complete"), then the mode's buttons:

| Mode | Buttons |
|---|---|
| Gate | **Skip for now**, **Continue** (disabled until every editable row is complete) |
| Home | **Play** |

### 1.2 Modes

| | Gate mode | Home mode |
|---|---|---|
| Opens when | Boot finds `ship_catalog.incomplete_ships()` non-empty and CEF is up | `--mods` was given and nothing is incomplete |
| Rows | Every mod ship. **Incomplete ships are editable**; complete ships are listed read-only, so the class names already in use stay visible | Every mod ship, read-only |
| Main action | **Continue**: write, re-load, re-check, boot | **Play**: boot |
| Other actions | Skip for now, Quit | Quit |

When `--mods` is given and something is incomplete, gate mode wins, because its
read-only rows already show everything home mode would.

**Read-only rows** render their values as plain text: no inputs, no pickers.
They cannot be ticked, and a mod's header tick box ticks only its editable
rows. A complete ship's metadata cannot be edited from this
screen in this sub-project (see Not in scope).

### 1.3 Where it runs

The screen runs in `engine/host_loop.py:run()`, right after
`foundation.load_plugins()` and the catalog boot line (~line 9412), and before
the game loop exists. It reuses the first-run picker's pre-boot loop: hologram
mode with the scene off, a page-load handler, mouse forwarding, and now keyboard
forwarding. That loop moves out of `_run_first_run_screen` into one
`_run_preboot_panel(panel, view_w, view_h)`, used by both screens.

`_run_first_run_screen` keeps its behaviour, and its tests guard that.

**No screen** (boot simply continues) when any of these holds:
- CEF did not come up (`cef_ready` is false, or a `--no-cef` build).
- `run()` was reached headless or by a tool. Neither can drive a UI, so neither
  may block. The catalog boot line already names the incomplete ships, and the
  game proceeds as if the player had chosen "skip for now".
- Mods are disabled (`--disable-mods`), so nothing is incomplete and there is
  nothing to show.

## 2. Catalog changes (extends sub-project 1)

### 2.1 Classes are names

- **`variant_of`** in the `dauntless` dict is **free text: a class name**. It is
  compared trimmed and case-folded. This replaces the earlier, unbuilt idea of a
  ship-id pointer.
- **A ship with no `variant_of`** is its own class, exactly as today. Its class
  key is its ship id.
- **Every ship naming the same class makes one catalog entry.**
  - The entry's **title** is the class name, in the first spelling seen.
  - Its **`ship_id`** is the **default member's** `shipFile`.
  - Each member becomes a **variant**: `Variant(name=<member title>, script=<member shipFile>)`.
    This is the same record shape as USS Enterprise → `Enterprise.py`.
  - The default member is `variants[0]`, written **name-only** because it
    spawns the entry's own script.
- **`'class_default': 1`** on one member marks the default. If none or several
  members are marked, the default is picked in this order:
  1. the member whose title equals the class name;
  2. a member whose title contains it as a whole word ("USS Intrepid LC" for
     "Intrepid");
  3. the first member in load order.
- **A stock class name** (one matching a stock entry's title, such as
  "Nebula") joins the stock entry.
  - The mod ship is appended to that entry's variants.
  - The stock default stays: `class_default` on the mod ship is ignored, with a
    warning in `errors`.
- **A class name matching another mod's class** joins it. Classes cross mod
  boundaries.

### 2.2 A class's values come from its members

Every member must carry all five mandatory fields itself (the table shows them
per row). The class combines them:

| Field | Class value |
|---|---|
| Era | The span covering every member, from the lowest from to the highest to. Any member with `'all'` makes the class `'all'`. |
| Role, Species | Must agree across members. A disagreement makes the class **incomplete**: the key goes in `missing`, and `errors` names the conflict ("role: Tactical (Defiant) vs Station (Lynx)"). |
| Playable | True if any member is playable. Each variant also records its own `playable`, which sub-project 2's "Set as player ship" reads. |
| Title | The class name; each variant is named by its member's title. |

`Variant` gains a `playable: bool | None` field. It is `None` for stock
registry variants, which inherit the entry's value.

### 2.3 Two levels in the API

The gate works on **ships**; consumers of the catalog work on **classes**. Both
are exposed:

```python
@dataclass(frozen=True)
class ShipRecord:            # one per ShipDef in the catalog (stock and mod)
    ship_id: str             # shipFile, display spelling
    mod: str | None          # owning mod (None = stock)
    shipdef_attr: str | None # Foundation.ShipDef attribute name, for the writer
    icon: str
    values: dict             # parsed own values (title, era, role, species, playable)
    variant_of: str | None   # class name as written, or None
    class_default: bool
    missing: tuple           # mandatory keys this SHIP still lacks
    errors: tuple
    raw_name: str            # ShipDef.name
    raw_race: str | None
    sub_menu: str | None     # ShipDef.SubMenu (after the §4 shim fix)
    player_menu: bool        # registered on the QuickBattle player menu
```

**New functions:**

| Function | Returns |
|---|---|
| `ships(source=None)` | Every `ShipRecord`; `source` is `"stock"`, `"mod"` or None for all |
| `incomplete_ships()` | Mod `ShipRecord`s with non-empty `missing`, **plus every mod member of a class that is incomplete through a role/species conflict** (§2.2). Each member ship can be complete alone while the class is not, and the player fixes the conflict by editing a member. This is the gate's trigger and its editable rows. |
| `suggestions(record)` | The pre-fill dict for one ship (§2.4) |
| `skip_for_session(ship_ids)` | Hides those ships for this process (§3.3) |
| `skipped()` | Their ids |

**Existing functions:** `entries()`, `entry()`, `incomplete()` and `species()`
keep their meaning over **class** entries. Sub-project 1's per-definition
merge (stock section, then mods per key) is unchanged: it now yields a
`ShipRecord`, and classes are formed from those records.

### 2.4 Suggestions (the pre-fills)

| Key | Suggested from |
|---|---|
| `title` | `ShipDef.name` |
| `species` | race: `Fed` → Federation; `Klingon`, `Romulan`, `Cardassian`, `Ferengi` and `Kessok` map to themselves; any other race gives nothing |
| `playable` | `True` if registered on the player menu, else nothing |
| `role` | `tactical` |
| `variant_of` | `SubMenu` with a trailing "Class" (and its whitespace) removed, if the result is non-empty; else nothing |
| `era` | nothing |

Suggestions are only pre-fills. They are written to disk only when the player
presses Continue.

### 2.5 Changes to sub-project 1's rules

1. `variants[0]` may be **name-only**: the class default spawns the entry's own
   script.
2. The idea of `variant_of` pointing at a ship id is dropped; it is free text
   (§2.1).

Sub-project 1's spec gets a short "Amended by sub-project 3" note pointing here.

## 3. Writing, skipping and re-loading

### 3.1 The written file (refines sub-project 1 §6)

The file is `<mod content root>/<Scripts>/<Custom>/<Ships>/zz_Dauntless_<shipFile>.py`.
Each path segment uses the mod's own spelling, found from the index key of an
existing `custom/ships/*.py` in that mod. If the mod has no such file, the
default spelling is `scripts/Custom/Ships`.

There is one file per **edited** ship, containing only the keys the player set:

```python
import Foundation
if hasattr(Foundation.ShipDef, 'DCMPAvenger'):
    d = Foundation.ShipDef.DCMPAvenger
    if not hasattr(d, 'dauntless'):
        d.dauntless = {}
    d.dauntless.update({
        'title': 'Avenger', 'species': 'Federation',
        'era': ('DS9', 'DS9'), 'role': 'tactical', 'playable': 1,
        'variant_of': 'Defiant',
    })
```

`'class_default': 1` is added on the starred member. The file is Python
1.5-safe and guarded, so it is harmless in the original BC.

### 3.2 Continue

1. Python re-validates every editable row. The page is never the authority.
2. If any row fails, nothing is written and the status line names it.
3. Each file is written to `.tmp` and then renamed (`os.replace`).
4. Each written file is added to the mod index by
   **`mods.register_sdk_file(raw_rel, abs_path, mod_name)`**, the SDK-target
   sibling of `register_game_file`.
5. Each file is run with `runpy.run_path` inside
   `shipdef.plugin_origin(mod_name, key)`.
6. `ship_catalog.invalidate()`.
7. If `incomplete_ships()` is now empty, boot proceeds. Otherwise the screen
   shows again (with the run errors from §3.4), **once**. After that, boot
   proceeds as if the player had skipped.

### 3.3 Skip for now

- `ship_catalog.skip_for_session(<incomplete ship ids>)`. Skipped ships drop out
  of `ships()`, `entries()`, `incomplete()` and `incomplete_ships()` for the
  process.
- `foundation.quickbattle._inject_registered_ships` does not inject a skipped
  ship. Its rows stay in the SDK tables, which is harmless, but it gets no
  button.
- Nothing is persisted. The next launch asks again.

### 3.4 Errors

| Fault | Behaviour |
|---|---|
| A write fails (read-only folder, disk full) | The screen stays open with a red line naming the file and the OS error. Skip for now and Quit still work. Files already written stay; they are correct and harmless. |
| A written file raises when run | Recorded (`catalog.describe()` and the screen's status line); that ship stays incomplete. |
| The screen itself raises | Logged with `dev_mode.log_swallowed`. Boot continues as "skip for now". A gate bug must never stop boot. |

## 4. Foundation shim fix

`ShipDefinition.__init__` reads `SubMenu` and `SubSubMenu` from `details` when
they are present. They are applied after the defaults, so an explicit attribute
set later still wins.

**Consequence:** the nested Quick Battle menus ("Defiant Class", "LC Intrepid
Class") that `foundation/quickbattle._resolve_category_chain` already supports
will start appearing live. Their tests set the attribute directly, which is why
they never saw the bug. A new test constructs through `details`.

## 5. Entry points

### 5.1 `--mods`

- `engine/mods.py` gains `MODS_SCREEN_FLAG = "--mods"` and
  `mods_screen_requested(argv=None) -> bool`.
- `host_main.cc` needs no change: `--mods` is not one of its `argv[1]` modes, so
  it reaches `run_host_loop()`.

### 5.2 Pause menu: Quit and Manage Mods

- `default_pause_menu` gains a production row **"Quit and Manage Mods"**
  (action id `quit-manage-mods`). It sits **immediately above** Exit Program,
  which stays last. The handler is injected as `on_quit_manage_mods`.
- The host-loop handler records a relaunch request with
  `_dauntless_host.request_relaunch(["--mods"])`, then sets the same quit flag
  as Exit Program. Shutdown proceeds exactly as it does today, including
  `cef_shutdown()`.

### 5.3 Relaunch (native)

- **`host_bindings.cc`:** a new `request_relaunch(extra_args: list[str])` stores
  the request in a process global (last call wins). The no-CEF stub build stores
  it too.
- **`host_main.cc`:** after `Py_FinalizeEx()`, if a relaunch is pending:
  - compute `platform::executable_path(argv[0])`;
  - build the new argv: the original argv minus any `--mods`, plus the extra
    args;
  - call `execv`.
- **Windows:** use `_spawnv(_P_NOWAIT, …)` and return `rc`. Windows has no true
  `exec` that keeps the console and process identity, and a new process is what
  BC players expect.
- **On failure** (`executable_path` fails, or `execv` returns), print the reason
  to stderr and return `rc`. The game has already shut down cleanly.
- The `--developer`, `--game-dir`, `--sdk-dir` and `--mods-dir` flags survive
  because the original argv is reused.

## 6. Keyboard input into CEF

- **Native capture** in `renderer::Window`:
  - a `glfwSetCharCallback` and a `glfwSetKeyCallback` push events onto a
    bounded queue (256 entries, oldest dropped);
  - the char callback records `{kind=char, codepoint}`;
  - the key callback records `{kind=key, glfw_key, action, mods}`, only for the
    editing keys: Backspace, Delete, Left, Right, Up, Down, Home, End, Enter,
    Tab and Escape;
  - this sits alongside the existing scroll accumulator.
- **`drain_text_events() -> list[tuple]`** (a binding) empties the queue. The
  existing key-state polling for game bindings is untouched.
- **`cef_send_key_event(kind, code, mods)`:**
  - for a char, a `KEYEVENT_CHAR` with `character` set;
  - for a key, a `KEYEVENT_RAWKEYDOWN` or `KEYEVENT_KEYUP`, using the
    Windows virtual-key code mapped from the GLFW key (VK_BACK, VK_DELETE,
    VK_LEFT… VK_RETURN, VK_TAB, VK_ESCAPE) and the `EVENTFLAG_*` modifiers;
  - `native_key_code` is set as well, as macOS needs.
- **The mapping** is a pure function `glfw_key_to_windows_vk(int) -> int` with a
  gtest.
- **Forwarding** happens only in `_run_preboot_panel`, which drains every frame
  and forwards everything. Escape is also offered to the panel
  (`handle_key_esc`): in the gate it does nothing, and in home mode it acts as
  Play.
- **In-game forwarding** is built by
  `2026-10-02-cef-text-input-keyboard-capture-design.md`: a native key gate,
  page-reported focus and release triggers. The in-game host drains the queue
  every frame and forwards it only while a field holds the keyboard.

## 7. Units

| Unit | Job |
|---|---|
| `engine/ship_catalog/catalog.py` (extend) | `ShipRecord`, class formation, `ships()`, `incomplete_ships()`, `suggestions()`, `skip_for_session()`, `skipped()` |
| `engine/ship_catalog/schema.py` (extend) | `variant_of` and `class_default` keys; `Variant.playable` |
| `engine/ship_catalog/gate_writer.py` (new) | Render a `zz_` file, write it atomically, register it, run it under `plugin_origin`. Pure rendering is split from the I/O. |
| `engine/ui/mods_screen_panel.py` (new) | The screen's state machine, in the shape of `FirstRunPanel`: rows, ticked set, class-default resolution, validation through `schema`, outcome (`continue` / `skip` / `play` / `quit`). No I/O except through an injected writer. |
| `native/assets/ui-cef/js/mods_screen.js`, `css/mods_screen.css`, entries in `index.html` | The page: renders the payload and reports clicks and typed values. Ported from the spike's design. |
| `engine/host_loop.py` | `_run_preboot_panel` (extracted), the gate and home call after `load_plugins`, and the pause-row handler |
| `engine/ui/pause_menu.py` | The new row |
| `engine/mods.py` | `register_sdk_file`, `MODS_SCREEN_FLAG`, `mods_screen_requested` |
| `engine/foundation/shipdef.py` | The `SubMenu`/`SubSubMenu` fix |
| `engine/foundation/quickbattle.py` | Skip-aware injection |
| `native/src/renderer/window.{h,cc}` | The text-event queue and callbacks |
| `native/src/ui_cef/cef_lifecycle.{h,cc}` | `send_key_event` |
| `native/src/host/host_bindings.cc` | `drain_text_events`, `cef_send_key_event`, `request_relaunch`, plus their no-CEF stubs |
| `native/src/host/host_main.cc` | Post-finalize relaunch |

## 8. Testing

| Test | Covers |
|---|---|
| `tests/unit/test_ship_catalog_classes.py` | Class formation by name (case- and whitespace-folded), the default resolution order, a `class_default` conflict, stock-class joins (appended, stock default kept, a warning), cross-mod classes, era union including `'all'`, role/species conflict making the entry incomplete, playable any-of, and `Variant.playable` |
| `tests/unit/test_ship_catalog_ships.py` | `ShipRecord` fields, `ships(source=…)`, `incomplete_ships()`, `suggestions()` (each source, plus the `SubMenu`-without-"Class" and empty cases), `skip_for_session` hiding from every view |
| `tests/unit/test_foundation_shipdef_submenu.py` | `SubMenu`/`SubSubMenu` from `details`; a later attribute still wins; menu injection nests through `details` |
| `tests/unit/test_gate_writer.py` | Rendering (keys present, Python 1.5-safe, guarded); the path spelling follows the mod; atomic write; `register_sdk_file`; re-run under `plugin_origin` makes the catalog complete; a write failure raises a typed error naming the file |
| `tests/unit/test_mods_screen_panel.py` | Mode selection; read-only rows; the ticked-rows rule for every field; Variant of quick-pick contents (other rows' values with counts, stock matches once typing, Clear); default ★ moves and auto-picks; Continue disabled or enabled and re-validated; the outcomes (continue, skip, play, quit); write error surfaced; the once-only re-show; `render_payload` diff-caching and `invalidate()` |
| `tests/unit/test_pause_menu.py` (extend) | The new row's position (just above Exit Program) and its action id |
| `tests/unit/test_mods.py` (extend) | `register_sdk_file`; `mods_screen_requested` |
| `tests/host/test_preboot_panel_loop.py` | `_run_preboot_panel` drains text events into `cef_send_key_event`, forwards the mouse, and exits on outcome. Uses the existing host test doubles. |
| `tests/integration/test_mods_screen_e2e.py` | A temp mod tree with two ships, no metadata and a shared `SubMenu`: load plugins, the panel opens in gate mode with the suggestions, fill it, Continue, files written, catalog complete, one class with the right default. Skip leaves the ships out of injection. |
| `native/tests/…/text_input_test.cc` | `glfw_key_to_windows_vk`; the queue's bound and order |

**Manual live checks**, recorded in the plan. Headless tests cannot see these:

1. Typing in the Title and Variant of cells on macOS, including Backspace,
   arrows, Enter and Tab.
2. The gate on the two real installed mods: fill, Continue, relaunch, and no
   gate on the next launch.
3. `--mods` home mode, then Play.
4. Pause → **Quit and Manage Mods** relaunches into home mode, keeping
   `--developer`.
5. Nested Quick Battle menus now appear for DCMPv2 and LC.

## Not in scope

- **Editing an already-complete ship's metadata.** For now, delete its `zz_`
  file to be asked again. An editor belongs to the mod-manager phase.
- **Enabling or disabling mods**, load order, conflicts and anything else of the
  mod manager beyond the read-only home.
- **In-game keyboard forwarding** (§6).
- **Switching `bridge_selection` to the catalog's `playable`.** It is now
  unblocked, but stays a follow-up.
- **The setup screen** (sub-project 2).
