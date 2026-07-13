# Static ABI surface — deeper introspection of the engine API (q18)

Status: ANSWERED — all six veins (q13c–h) run & analyzed 2026-07-13. Keepers:
        q13c (symbol/owner map), q13h (hierarchy). Settled negatives: q13d
        (no signatures), q13f (globals don't enumerate), q13g (no hidden tier).
Author: Claude session (sparked by q13b's method-name surface)
Created: 2026-07-13
Closed:  —

## Goal

q13 dumped the engine's **constant** surface; q13b dumped its **method-name**
surface. Both proved the `-TestMode` Python 1.5 REPL is a rich window into the
static ABI. This probe family pushes that window as far as it goes: recover
everything the SWIG wrapper exposes *about the API itself* — signatures, C symbol
names, data-member schemas, engine globals, and the real class hierarchy.

It is **static / state-invariant** (like q13, unlike q14–q17 which are all live
dynamic state) — one boot-menu run, no battle, no mission.

## Why (relation to q13b's finding)

q13b already paid off once: it showed the heatmap's #1/#2 stubs
(`TorpedoTube.UpdateCharge/GetMaxCharge`) don't exist on the engine's
`TorpedoTube` at all — they're a caller category error in our code. The method
**names** were enough for that. The veins below add *types, symbols, and struct
fields* on top of the names, which:

- turn q13b's 36k name list into a **typed API reference** (if signatures exist);
- give a **Python-method → C-symbol map** that bridges the API to the RE'd binary
  (`FUN_*` addresses ↔ named `Class_Method` C functions);
- expose **data-struct fields** (e.g. real `TorpedoAmmoType` launch speeds) we
  currently only infer from hardpoint scripts;
- confirm the object hierarchy CLAUDE.md documents from *inference*.

## The six veins (confirmed present in the SWIG source unless noted)

| # | Vein | How | Certainty |
|---|---|---|---|
| 1 | Method → C symbol | `App.Cls.M.im_func.__name__` → `Cls_M` | certain |
| 2 | **Method signature** | `App.Cls.M.im_func.__doc__` (SWIG prototype) | **UNKNOWN — the prize** |
| 3 | Data-member schema + values | `cls.__getmethods__` / `__setmethods__` (20 classes) | certain |
| 4 | Engine globals / sentinels | `dir(Appc.globals)` (`g_k*`, `ANY_TARGET`, …) | certain |
| 5 | Flat C-function table | `dir(Appc)` (superset of `dir(App)`) | certain |
| 6 | Real inheritance tree | `cls.__bases__` recursion | certain |

Vein 2 is the transformational one and the reason for a recon-first approach:
signatures live in the compiled binary, so we cannot verify offline whether BC's
SWIG build embedded them. A ~15-line recon settles it before committing to a
full-surface dump.

## Probes

**Recon (optional fast pre-check):**
- **`tools/probes/q18a_abi_recon.py`** — tests all six veins on a handful of
  representative targets (`ShipClass`, `TorpedoTube`, `EnergyWeapon`,
  `TorpedoAmmoType`, `ObjectClass`, `NiPoint3`). ~15 lines of output; run it first
  to eyeball the **vein-2 signature verdict** before the two heavy per-method
  dumps. Collect with generic `collect.py q18a`.

**Full-surface dumps — one per vein (`q13c`–`q13h`):** all print-light + heartbeat;
`q13c/q13d/q13g` are chunk-capable (`_CHUNK = 1`) for the large ones. Collect each
with `collect_q13.py <stream>` (handles single-file **and** chunk-merge + the
`total_dump_lines` completeness check).

| Probe | Vein | Emits | Collect |
|---|---|---|---|
| `q13c_symbol_map.py` | 1 | `App.Cls.M -> Cls_M` (C symbol per method) | `collect_q13.py q13c` |
| `q13d_signatures.py` | 2 | `App.Cls.M = <repr(doc)>` + `methods_with_nonempty_doc` verdict | `collect_q13.py q13d` |
| `q13e_data_members.py` | 3 | `App.Cls.member = r/w/rw` (the ~20 struct classes) | `collect_q13.py q13e` |
| `q13f_globals.py` | 4 | `Appc.globals.<name> = <value/type>` | `collect_q13.py q13f` |
| `q13g_flat_appc.py` | 5 | `Appc.<name> = shared/only <type>` | `collect_q13.py q13g` |
| `q13h_inheritance.py` | 6 | `App.Cls : Base1, Base2` | `collect_q13.py q13h` |

## How to run (the full batch)

```
uv run python tools/probes/push.py q13c
uv run python tools/probes/push.py q13d
uv run python tools/probes/push.py q13e
uv run python tools/probes/push.py q13f
uv run python tools/probes/push.py q13g
uv run python tools/probes/push.py q13h
```
Then in `stbc.exe -TestMode` at the **main menu**, run each (any order; all
state-invariant):
```python
execfile('q13c_symbol_map.py')
execfile('q13d_signatures.py')
execfile('q13e_data_members.py')
execfile('q13f_globals.py')
execfile('q13g_flat_appc.py')
execfile('q13h_inheritance.py')
```
Each prints a startup marker, a heartbeat every 100 classes (for the class
walkers), and `wrote BCProbe_q13X.cfg … / done`. If any prints `save FAILED`, set
`_CHUNK = 1` at the top of that file and re-run (only `q13c/d/g` need it).

Collect on the dev side:
```
uv run python tools/probes/collect_q13.py q13c q13d q13e q13f q13g q13h
```

## Expected output / how to read it

- **Vein 2 verdict (q13d):** read `methods_with_nonempty_doc` in the inventory.
  `>0` → SWIG embedded prototypes and the per-method `= '<doc>'` lines are the
  **typed API reference**. `0` → docstrings were stripped; the method surface
  stays name-only (still valuable via q13c's symbol map).
- **Vein 1 (q13c):** the `-> Cls_M` symbols are the Python↔C symbol map for RE.
- **Veins 3/4/6 (q13e/f/h):** member schemas, the `Appc.globals` roster, and the
  `__bases__` chains dump directly.
- **Vein 5 (q13g):** `count_Appc_only` + the `only`-tagged rows are the raw engine
  functions the shadow layer hides.

## Cleanup

Delete `game/q18a_abi_recon.py`, `game/q13[c-h]_*.py`, and every
`game/BCProbe_q18a.cfg` / `game/BCProbe_q13[c-h]*.cfg`. The probes scrub their own
cfg keys after writing; `Options.cfg` is untouched.

## Findings — all six veins run 2026-07-13 (results/q13[c-h]_*.txt)

Verdict per vein: **c ✅ valuable · d ❌ negative · e ⚠ narrow · f ❌ failed ·
g ❌ negative (useful) · h ✅ valuable.**

### q13c — symbol map ✅ (and richer than hoped)
36,538 methods → C symbols, no truncation. The symbol *prefix reveals the true
implementing C++ class*, even for inherited methods. `ShipClass`'s 202 methods
resolve to their real owners: `ShipClass_*` 55, `PhysicsObjectClass_*` 23,
`DamageableObject_*` 23, `BaseObjectClass_*` 18, `ObjectClass_*` 14, plus the TG*
framework bases (`TGAttrObject`, `TGEventHandlerObject`, `TGObject`,
`TGTemplatedAttrObject`) and ~50 hand-written Python wrappers (bare `GetX`
`im_func.__name__`, no class prefix — these are the `apply(Appc.X,args)` wrappers
in App.py, not direct instancemethod bindings). This is a **Python-method →
C-symbol → owning-class** map: it tells RE which named symbol backs each method,
and tells the shim which *base class* a method really belongs on.

### q13d — signatures ❌ DEFINITIVE NEGATIVE
`methods_with_nonempty_doc = 0`. **Every** `im_func.__doc__` is `None` — BC's SWIG
build stripped docstrings. The typed-signature prize is **not obtainable through
this interface.** q13d's output is all `= None`; don't pursue signatures this way.
(q13c's symbol map is the consolation, and it's good.)

### q13e — data members ⚠ confirmed but narrow
20 classes, 86 members. Almost all are **math/color/UI structs** (`NiPoint3`,
`NiColor`, `NiFrustum`, `TGPoint3`, `TGColorA`, `NiPoint2`, `GraphicsMenuInfo`,
`TGGroupPlayer`) — the only gameplay struct is **`TorpedoAmmoType`**
(`m_fLaunchSpeed`, `m_iMaxTorpedoes`, `m_pcLaunchSound`, `m_pcModule`, all `rw`).
Takeaway: engine state is almost entirely behind `Get/Set` methods, not exposed
fields — so there is little "free" struct data to read. Values need a live
instance (schema only at the menu).

### q13f — globals ❌ FAILED (retry-by-name possible)
`Appc.globals` imports, but `dir(Appc.globals)` returns **empty** (0 rows) — the
SWIG globals object resolves attributes via `__getattr__` and does not enumerate.
We know the names from App.py source (`g_k*` singletons, `ANY_TARGET`,
`INVALID_DESTINATION`) but can't discover them via `dir()`. If we need their
values, a follow-up must read a *hard-coded name list* off `Appc.globals`, not
enumerate it.

### q13g — flat Appc table ❌ negative, but a *useful* negative
5,802 names; 3,883 `Appc`-only (3,391 builtins + 492 ints). Inspected: the
"hidden" tier is **not** hidden functionality — it is the **flat binding layer**
beneath the shadow classes: `Class_Method` bindings (already mapped by q13c via
`im_func`), `new_X`/`delete_X` ctors/dtors (156 + 228), and flat `Class_CONST`
aliases of the 492 class constants q13 already captured. **Conclusion: the `App`
shadow layer is a complete cover of the engine surface — we are not missing
entry points behind `Appc`.** (This corrects the earlier "whole hidden tier"
first impression.)

### q13h — inheritance ✅ confirmed + real surprises
630 classes. Confirms CLAUDE.md's chain *exactly* from the engine and extends it
to the roots:
`ShipClass → DamageableObject → PhysicsObjectClass → ObjectClass →
BaseObjectClass → TGEventHandlerObject`.
Surprises worth acting on:
- **`TorpedoTube : Weapon`** and **`EnergyWeapon : Weapon`** share a common
  `Weapon` base — the structural reason `UpdateCharge` is EnergyWeapon-only
  (charge is not on the shared `Weapon` base). Directly reinforces q13b's
  TorpedoTube caller-bug finding.
- **`Torpedo : PhysicsObjectClass, WeaponPayload`** — real C++ **multiple
  inheritance** (a physical object *and* a weapon payload).
- **`ShipSubsystem : TGEventHandlerObject`** — subsystems are a **separate
  hierarchy** from `ObjectClass` (both descend `TGEventHandlerObject`); a subsystem
  is *not* an `ObjectClass`.

### Net
The interface's static reach ends at **names, C-symbols/owning-class, inheritance,
and a thin struct-field layer** — not types/signatures (stripped) and not any
hidden functionality (the flat tier is just plumbing). q13c + q13h are the keepers;
q13d/f/g are settled negatives that stop us guessing.
