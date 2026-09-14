# Where does a firing energy weapon's discharge rate come from?

Status: **RE HALF CLOSED 2026-09-14** (Q-D1..Q-D4 answered from the binary and
ported); live half (Q-D5..Q-D7) still PENDING
Author: 2026-09-09 session
Created: 2026-09-09
Closed:  — (reference half 2026-09-14; live half open)

## Goal

When a phaser fires, what number drains its charge? Two candidate models
disagree by 200x on real mod content, and **no measurement we have ever taken
could tell them apart.**

- **Model P (what we ship).** The bank drains at the hardpoint's authored
  `SetNormalDischargeRate(...)`, per second.
- **Model T (what the RE audit says BC does).** The firing path reads a **flat,
  power-level-indexed table** and leaves `NormalDischargeRate` entirely dead.

This experiment must return the table's *values*, not just which model wins —
Model T is useless to us without them.

## Background

`docs/superpowers/specs/2026-07-15-bc-faithful-weapon-dispatch-design.md` §7
lists the discharge-rate source on its **frozen, do-not-change** list, on the
grounds that our live 2026-06-29 instrumented measurements beat the RE doc's
transcription where the two conflict.

**That freeze rests on evidence which cannot see the difference.** Measured
2026-09-09 across the whole stock tree:

```
stock hardpoint files scanned: 52
NormalDischargeRate values across ALL stock emitters: {1.0: 208}
non-1.0 stock emitters: 0
```

**208 of 208 stock emitters declare exactly 1.0.** On stock content, "read the
property" and "use a flat rate of 1.0" are observationally identical — same
drain, same beam duration, same recharge. The 2026-06-29 probe ran on stock
ships, so whatever it measured, it *could not* have discriminated. The freeze
is real but its stated justification is not load-bearing.

Mod content is the only place the models diverge, and it diverges hugely:

| Hardpoint | Emitters | `NormalDischargeRate` | `MaxCharge` | Drain under Model P |
|---|---|---|---|---|
| every stock ship | 208 | 1.0 | 1.0-5.0 | 1-5 s |
| CGSovereign | 30 | **200.0** | 1.0 | **0.005 s** |
| VoyagerCubeHP (tractors) | 12 | 10.0 | 5.0 | 0.5 s to the floor |
| LC Intrepid | — | 1.0 | 0.8 | 0.8 s |

Live report 2026-09-09, CGSovereign under Model P: *"phasers are blasting for
like 0.1s before being fully drained... i remember the cg sov had rapid fire
phasers but nothing like that."* That is first-hand testimony against Model P,
but it is recollection, not measurement — it motivates the experiment, it does
not settle it.

⚠️ **Do not "fix" this from the armchair.** Switching to a flat 1.0 is tempting
(stock stays byte-identical, since 208/208 already declare 1.0) but it would
bake in a guessed constant for a table BC indexes by power level, and it would
overturn a frozen spec item on inference. Get the values.

## Specific questions

**For the clean-room reference** (`stbc-reference`; see
`reference_stbc_clean_room_mcp` for query craft — `layout` and `api` answer
reliably, bare `behaviour` questions land below the relevance floor):

- **Q-D1** `layout` — `EnergyWeaponProperty` is `0x90` with the energy config at
  `+0x68..+0x8c`; `CombatPropertyLeaves.md` puts `NormalDischargeRate` at
  `+0x70` (getter `0x0063C540`, setter `0x0063CBE0`). **Does anything other
  than the SWIG getter read `+0x70`?** If the firing path never touches it,
  Model T is confirmed structurally.
- **Q-D2** `api` — full entry name `EnergyWeapon::`. Enumerate the entries.
  Is there a discharge/update routine, and what does it read?
- **Q-D3** `layout`/`where` — the dispatch spec cites a power-level damage table
  at `DAT_0089317x` (LOW 0.25 / MED 0.5 / HIGH 0.5). **Is there a sibling table
  for discharge, and what are its values?** These are the numbers Model T needs.
- **Q-D4** — is the rate per *second* or per *tick*? (Q-C1 in
  `2026-05-15-phaser-charge-dynamics.md` asked this of the property and was
  answered "the question is malformed"; it must be re-asked of the table.)

**For a live run** — and this is the part the 2026-06-29 probe got wrong:

- **Q-D5** The probe **MUST fire an emitter whose authored rate is NOT 1.0.**
  A stock ship cannot answer this question no matter how carefully it is
  measured. Either install CGSovereign, or hand-edit one stock hardpoint
  emitter to `SetNormalDischargeRate(200.0)` and fly that.
- **Q-D6** With a non-1.0 emitter firing, sample `GetChargeLevel()` per tick.
  `d_charge/dt` at the authored value ⇒ Model P. `d_charge/dt` at some other
  constant ⇒ Model T, and that constant **is the answer to Q-D3**.
- **Q-D7** Repeat at each phaser power level (LOW / MED / HIGH). If the rate
  changes with power level, the table is confirmed indexed; if not, one flat
  scalar covers it.

## Snippet

`tools/charge_logger.py` (the per-tick charge sampler drafted for
`2026-05-15-phaser-charge-dynamics.md`; that runbook's snippet and analysis
sections still apply verbatim — only the *ship choice* changes, per Q-D5).

## How to run

Follow `2026-05-15-phaser-charge-dynamics.md` for snippet install and capture,
with one mandatory change: **the ship under test must have a non-1.0
`NormalDischargeRate`.** Install the CGSovereign pack into the real BC
installation, or edit one emitter in a stock hardpoint and note the edit in
Cleanup.

## Expected output

`BCChargeLog.cfg` rows of `frame, game_time, charge0..charge7`. The
discriminator is a single slope:

```
authored rate 200.0, MaxCharge 1.0
  Model P  -> charge0 falls 1.0 -> 0.0 within ONE tick
  Model T  -> charge0 falls at the table's rate, order 1.0/s, ~1 s to empty
```

## Analysis

Slope of `charge0(t)` while `is_firing0 == 1`, in charge-units per second.
Compare against the authored 200.0 and against 1.0. Report the measured
constant to 3 significant figures — under Model T that number is the
deliverable, not a sanity check.

## Cleanup

- `uv run python tools/uninstall.py` to restore the game.
- Revert any hand-edited stock hardpoint (note which file and emitter).
- If CGSovereign was installed into the real BC tree for the run, remove it.

## Findings

**Reference half — answered 2026-09-14 by the clean-room RE project** (the
server itself returned `no-match` on the property name, no object model for
`EnergyWeaponProperty`, and below-floor on the behaviour question; the RE
project reconstructed it from the image). Behavioural facts only are
recorded here.

**Neither model was right. The property is not dead — but phasers don't read
it.** Three energy-weapon subclasses, three consumption models; there is no
shared base-class discharge (the common `UpdateCharge` has a recharge arm
only):

| Subclass | Drain | Reads `NormalDischargeRate`? |
|---|---|---|
| `PhaserBank` | per-second **table** × dt, continuous while the beam is up | **No** |
| `PulseWeapon` | flat **per-shot** cost inside Fire = property × power scale | **Yes** |
| `TractorBeamProjector` | none — charge is set to MaxCharge every tick (Medium-High) | No |

- **Q-D1** — Phaser: a table, the sibling of the damage table and contiguous
  with it. Damage `0x00893170` = LOW 0.25 / MED 0.5 / HIGH 0.5; **discharge
  `0x0089317c..0x00893184` = LOW 0.35 / MED 1.0 / HIGH 1.0**; default arm
  0.0. Indexed by the **owning `PhaserSystem`'s power level** (system field
  `+0xf0`, reached through the bank's owner pointer) — not the bank, not the
  property. Confidence High. CGSovereign at MED: 1.0 ÷ 1.0/s = **1.0 s**
  drain; its authored 200.0 is never loaded.
- **Q-D2** — Phaser: per second × dt (the same dt the recharge arm uses).
  Pulse: per shot, no dt. One asymmetry to record: recharge is scaled by
  bank condition, **discharge is not**. Confidence High.
- **Q-D3** — Two sibling tables, not one (see Q-D1). For pulse the power
  scale is applied to the *property*: LOW ×0.5 / MED ×1.0 / HIGH ×2.0,
  on the weapon's own `EnergyWeapon` PowerSetting (`+0xac`) — a **different
  field** from the phaser's `PhaserSystem` PowerLevel (`+0xf0`).
- **Q-D4** — Yes, indexed by power level (both tables). Readers of the
  property field: exactly one engine accessor with five callers — three in
  the pulse power-scaling routine, one in a multiplayer state-hash
  accumulator (Medium-High that it is sync, not gameplay), one the SWIG
  getter. Zero on any phaser path.
- **Also answered (not asked):** exhaustion stops the beam on the same
  update, no interval (High). `CanFire` confirms §1.6's asymmetry directly:
  `MinFiringCharge < charge` to start, `charge > 0` to sustain. **And a
  two-stage fixed windup exists** on the phaser fire path: state 1 arms the
  beam FX for **0.35 s with the charge frozen** (neither drained nor
  recharged), state 2 connects for **0.25 s** (Medium-High), state 3 applies
  damage. Drain runs only in states 2–3. So the retail ~1 s burst is
  ~0.35 s windup + ~1.0 s of table drain, and even the old 5 ms bug would
  have shown ≥0.35 s of beam under a correct windup model. **The windup is
  NOT ported** — separate design; it touches beam FX and damage start.
- **Q-D5/6/7** — _TBD_ (live). Now a confirmation run, not a discriminator:
  the prediction for a CGSovereign phaser at MED is a ~1.35 s visible beam
  with the charge slope at −1.0/s starting ~0.35 s after the fire press.

**Ported 2026-09-14** (`engine/appc/weapon_subsystems.py`,
`tests/unit/test_energy_weapon_discharge_source.py`): `PhaserBank` drains
from `PHASER_DISCHARGE_BY_POWER_LEVEL` via the parent system's power level;
`PulseWeapon.Fire` subtracts `NormalDischargeRate ×
PULSE_COST_SCALE_BY_POWER_SETTING[PowerSetting]` instead of dumping to 0
(stock BoP re-arms in ~2 s, not ~9 s). **Assumed, not RE'd:** the default
PowerSetting is MED — the SDK never calls `SetPowerSetting` and the
constructor value was not read. The `2026-07-15` spec's §7 frozen entry is
rewritten accordingly. Not ported: tractor no-discharge (ours drains toward
MinFiringCharge as a designed hold), the windup.

The old §1.6 audit was half-right twice: it looked at a phaser and correctly
saw a table, then generalised to "the property is dead", which is false for
pulse. That is why it never reconciled with the 2026-06-29 measurements.

Once answered:

- ~~If **Model T**~~ Done (phaser). The freeze rested on stock-only evidence
  that could not discriminate — recorded in §7 so nobody re-freezes it on
  the same reasoning.
- ~~If **Model P**~~ True for pulse only; the tier-1 gap list in
  `2026-09-09-mod-distribution-tiers-design.md` is updated.
- The live half (Q-D5..7) confirms the port; it no longer decides it.
