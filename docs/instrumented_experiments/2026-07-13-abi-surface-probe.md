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

- **`tools/probes/q18a_abi_recon.py`** *(authored)* — tests all six veins on a
  handful of representative targets (`ShipClass`, `TorpedoTube`, `EnergyWeapon`,
  `TorpedoAmmoType`, `ObjectClass`, `NiPoint3`; methods `GetHull`, `Fire`,
  `GetMaxCharge`, `GetName`). Small output, so per-line `print` is fine. Writes
  `game/BCProbe_q18a.cfg`.
- **`q18b_signatures.py`** *(planned, GATED on q18a vein 2)* — only worth building
  if `im_func.__doc__` carries a prototype. Full-surface dump: every method →
  `Cls_M` symbol + docstring/signature. Print-light (this will be ~36k lines like
  q13b), chunked-capable, same completeness invariant.
- **`q18c_members_and_globals.py`** *(planned)* — full dump of the 20 data-member
  classes (field names + live scalar values where readable) and the complete
  `dir(Appc.globals)` with scalar values. Certain to yield data regardless of q18a.

## How to run (q18a recon)

```
uv run python tools/probes/push.py q18a          # dev side
```
Then in `stbc.exe -TestMode` at the **main menu**:
```python
execfile('q18a_abi_recon.py')
```
It prints each vein's result and writes the cfg. Collect with the **generic**
collector (single unnumbered file, no phase suffix):
```
uv run python tools/probes/collect.py q18a       # -> results/q18a_abi_recon.txt
```

## Expected output / how to read it

- **Vein 2 verdict:** look at the `*.im_func.__doc__ (signature?)` lines. If they
  contain a C-style prototype (e.g. `GetHull(ShipClass self) -> float` or the raw
  `float ShipClass_GetHull(ShipClass *)`), **the prize is real** → build q18b. If
  they are `None` or an empty/generic string, signatures were stripped → skip q18b,
  and the method surface stays name-only (still valuable via vein 1's symbol map).
- **Vein 1:** `im_func.__name__` should read `ShipClass_GetHull` etc. — the C
  symbol map is confirmed the moment these are non-generic.
- **Veins 3/4/6:** member-name lists, the `Appc.globals` roster, and `__bases__`
  chains print directly.
- **Vein 5:** `count_Appc_only` + sample = raw functions the shadow layer hides.

## Cleanup

Delete `game/q18a_abi_recon.py` and `game/BCProbe_q18a.cfg`. The probe scrubs its
own cfg keys after writing; `Options.cfg` is untouched.

## Findings

(To be filled in when q18a runs — especially the vein-2 signature verdict, which
decides whether q18b is worth authoring.)
