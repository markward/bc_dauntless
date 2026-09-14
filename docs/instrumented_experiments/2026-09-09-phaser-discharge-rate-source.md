# Where does a firing energy weapon's discharge rate come from?

Status: **PENDING** — needs BOTH the clean-room reference AND a live run
Author: 2026-09-09 session
Created: 2026-09-09
Closed:  —

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

*(pending)*

- **Q-D1** — _TBD_
- **Q-D2** — _TBD_
- **Q-D3** — _TBD_ (the table's values; the deliverable if Model T wins)
- **Q-D4** — _TBD_
- **Q-D5/6/7** — _TBD_

Once answered:

- If **Model T**, change `_EnergyWeaponFireMixin.UpdateCharge` to the measured
  table and rewrite §7's frozen entry — recording that the original freeze
  rested on stock-only evidence that could not discriminate, so nobody
  re-freezes it on the same reasoning.
- If **Model P**, the mods are simply authored this way, and the tier-1 gap
  list in `2026-09-09-mod-distribution-tiers-design.md` should say so and stop
  calling it a divergence.
