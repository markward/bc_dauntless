# Static ABI surface — deeper introspection of the engine API (q18)

Status: PENDING (recon q18a authored; full dumps gated on recon results)
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

## Findings

(To be filled in when q18a runs — especially the vein-2 signature verdict, which
decides whether q18b is worth authoring.)
