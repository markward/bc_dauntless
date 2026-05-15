# Phaser charge dynamics investigation

Status: **PENDING**
Author: 2026-05-15 session
Created: 2026-05-15
Closed:  —

## Goal

Determine how `EnergyWeapon.GetChargeLevel()` evolves tick-by-tick in
live BC. Specifically: what is the per-second drain rate while firing,
the per-second recharge rate while idle, the actual threshold for
`CanFire()` returning true, and the auto-stop / restart hysteresis. The
goal is to pin down the unit semantics of `SetNormalDischargeRate(1.0)`
and `SetRechargeRate(0.08)` — currently a guess in PR 2c that produces
~2-second bursts (much shorter than BC feel).

## Background

PR 2c's phaser combat ([design](../superpowers/specs/2026-05-14-phaser-combat-design.md))
implements continuous fire via the existing `_EnergyWeaponFireMixin`
charge model. Per-bank drain rate was assumed to be `units / second`
based on a comment in
[`engine/appc/properties.py`](../../engine/appc/properties.py), but
that comment was inferred, not measured. The smoke-test feedback:
sustained fire lasts a couple of seconds before all banks deplete and
stop, much shorter than BC's roughly-5-second bursts.

Three things could be off:

1. The unit of `NormalDischargeRate` (per-second? per-tick? per-minute?
   fraction-of-max-per-second?).
2. The recharge formula (constant rate vs. proportional to depletion).
3. The auto-stop threshold (drops below `MinFiringCharge` vs. drops to
   zero) and the restart hysteresis (must climb back to `MaxCharge` vs.
   just past `MinFiringCharge`).

The only authoritative answer is BC's own runtime values, which we can
sample via `bank.GetChargeLevel()` every tick.

Related context:

- [`engine/appc/subsystems.py:_EnergyWeaponFireMixin.UpdateCharge`](../../engine/appc/subsystems.py) — current implementation.
- [`docs/instrumented_experiments/2026-05-15-hardpoint-scale-investigation.md`](2026-05-15-hardpoint-scale-investigation.md) — partner experiment, runs at the same time on the same setup.
- [`docs/instrumented_experiments/2026-05-12-system-scale-investigation.md`](2026-05-12-system-scale-investigation.md) — recent completed example following this template.

## Specific questions

Each must end with a numeric answer in the **Findings** section.

- **Q-C1** Per-second discharge rate while firing. Compute from
  `(charge_pre - charge_post) / wall_dt` over a known firing window.
  Is it exactly `SetNormalDischargeRate(1.0)` (i.e. unit = per-second),
  or some other multiple?
- **Q-C2** Per-second recharge rate while idle (RED alert, weapons on,
  not firing). Compute the same way. Is it exactly
  `SetRechargeRate(0.08)`?
- **Q-C3** The actual threshold above which `bank.CanFire()` returns
  true. Equal to `SetMinFiringCharge(3.0)`? Some other constant? Read
  by stepping current charge down with controlled fire bursts and
  watching when `CanFire()` flips.
- **Q-C4** The auto-stop threshold while firing — does the bank stop
  the moment charge drops below `MinFiringCharge`, or only when it
  hits zero? Read by sustained fire from full charge and noting at
  what `charge_level` `IsFiring()` flips back to 0.
- **Q-C5** Restart hysteresis — once a bank auto-stops because of
  depletion, what charge level does it need to *re-start* firing if
  the player keeps the trigger held? Equal to `MinFiringCharge`? Equal
  to `MaxCharge` (i.e. fully recharged)? Or somewhere between?
- **Q-C6** Does the rate scale with `WeaponSystemProperty.SetPowerLevel`
  (PP_LOW vs PP_HIGH) or with alert level (yellow vs red)? Bonus —
  helps explain whether engineers shifting power to weapons matters.

## Snippet

Save as `tools/charge_logger.py`. Same install path as
[`tools/appc_logger.py`](../../tools/appc_logger.py) — `tools/setup.py`
will append it to `game/scripts/App.py` after we point it there (step 2
of *How to run*).

```python
###############################################################################
# charge_logger.py
#
# Appended to game/scripts/App.py by tools/setup.py — captures per-tick
# charge dynamics for the player's first phaser bank. See
# docs/instrumented_experiments/2026-05-15-phaser-charge-dynamics.md.
#
# Hooks UtopiaModule.GetGameTime (per-tick heartbeat). On every Nth tick
# (downsampled to keep the cfg manageable) we sample:
#   - wall time, frame, game_time
#   - first phaser bank: charge_level, is_firing, can_fire
#   - parent PhaserSystem: power_level, is_on
#   - ship alert level
# A ring of up to MAX_SAMPLES rows is written to BCChargeLog.cfg.
# Once the ring fills, oldest samples are evicted (we want trailing data,
# not the boot).  The user can quit when they've covered the scenarios
# in the runbook.
#
# Python 1.5 constraints (see CLAUDE.md "Critical constraints"):
#   - no f-strings, no True/False literals, no "import X as Y"
#   - guard every import with try/except ImportError
#   - file I/O ONLY via g_kConfigMapping.SaveConfigFile
#   - os module is not available; only sys is reliably present
###############################################################################
try:
    _samples = []          # ring buffer of (wall, game_t, frame, charge, firing,
                            #                can_fire, power_level, alert, is_on)
    _MAX_SAMPLES = 600     # 10 minutes at 1 Hz, or 60 seconds at 10 Hz
    _SAMPLE_EVERY_N_TICKS = 6   # ~10 Hz at 60-tick fixed step
    _save_every = 0
    _SAVE_EVERY_N_SAMPLES = 30  # write cfg ~3x/sec so a crash keeps tail
    _tick_counter = 0
    _orig_GetGameTime = UtopiaModule.GetGameTime

    def _alert_str(a):
        try:
            return "%d" % int(a)
        except:
            return "?"

    def _safe_call(obj, attr):
        try:
            return getattr(obj, attr)()
        except:
            return None

    def _sample(game_t):
        try:
            import time
            wall = time.time()
        except:
            wall = 0.0
        try:
            frame = g_kSystemWrapper.GetUpdateNumber()
        except:
            frame = 0
        try:
            player = Game_GetCurrentPlayer()
        except:
            player = None
        if player is None:
            return ("%.4f" % wall, "%.4f" % game_t, "%d" % frame,
                    "no_player", "", "", "", "", "")
        try:
            phasers = player.GetPhaserSystem()
        except:
            phasers = None
        if phasers is None or phasers.GetNumWeapons() == 0:
            return ("%.4f" % wall, "%.4f" % game_t, "%d" % frame,
                    "no_phasers", "", "", "", "", "")
        bank = phasers.GetWeapon(0)
        charge = _safe_call(bank, "GetChargeLevel")
        firing = _safe_call(bank, "IsFiring")
        can_fire = _safe_call(bank, "CanFire")
        power_level = _safe_call(phasers, "GetPowerLevel")
        is_on = _safe_call(phasers, "IsOn")
        alert = _safe_call(player, "GetAlertLevel")
        return ("%.4f" % wall,
                "%.4f" % game_t,
                "%d" % frame,
                "%.6f" % (charge if charge is not None else -1.0),
                "%d" % (firing if firing is not None else -1),
                "%d" % (can_fire if can_fire is not None else -1),
                "%d" % (power_level if power_level is not None else -1),
                _alert_str(alert),
                "%d" % (is_on if is_on is not None else -1))

    def _flush(cfg):
        cfg.SetIntValue("BCChargeLog", "n_samples", len(_samples))
        # First / last sample summary (cheap sanity-check rows).
        if _samples:
            first = _samples[0]
            last  = _samples[-1]
            cfg.SetStringValue("BCChargeLog", "first_sample",
                                " ".join(first))
            cfg.SetStringValue("BCChargeLog", "last_sample",
                                " ".join(last))
        # Each sample row gets its own key — analyzer parses them by index.
        for i in range(len(_samples)):
            row = _samples[i]
            cfg.SetStringValue("BCChargeLog", "s%d" % i, " ".join(row))
        # Column legend for the analyzer.
        cfg.SetStringValue("BCChargeLog", "columns",
                            "wall game_t frame charge firing can_fire power_level alert is_on")
        try:
            cfg.SaveConfigFile("BCChargeLog.cfg")
        except:
            pass

    def _GetGameTime_wrapped():
        global _tick_counter, _save_every
        result = _orig_GetGameTime()
        _tick_counter = _tick_counter + 1
        if _tick_counter % _SAMPLE_EVERY_N_TICKS != 0:
            return result
        row = _sample(result)
        _samples.append(row)
        if len(_samples) > _MAX_SAMPLES:
            # Drop the oldest — keep trailing window.
            del _samples[0]
        _save_every = _save_every + 1
        if _save_every >= _SAVE_EVERY_N_SAMPLES:
            _save_every = 0
            try:
                _flush(g_kConfigMapping)
            except:
                pass
        return result

    UtopiaModule.GetGameTime = _GetGameTime_wrapped
except Exception, _instr_err:
    try:
        g_kConfigMapping.SetStringValue("BCChargeLog", "instr_error",
                                         "%s: %s" % (_instr_err.__class__.__name__,
                                                      str(_instr_err)))
        g_kConfigMapping.SaveConfigFile("BCChargeLog.cfg")
    except:
        pass
```

Sample row format (space-separated, one per `s<index>` key):

```
wall game_t frame charge firing can_fire power_level alert is_on
1731.4321 12.3456 740 4.527319 1 1 1 2 1
```

## How to run

This experiment runs on a **Windows machine with BC installed at
`game/`**. The macOS dev box can prepare and analyze the cfg but cannot
run stbc.exe.

1. **Drop the snippet** at `tools/charge_logger.py` (copy from the
   "Snippet" section above verbatim).

2. **Swap the instrumentation snippet.** Edit
   [`tools/setup.py:26`](../../tools/setup.py#L26):

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "charge_logger.py"
   ```

   *Do not commit this edit* — it's an experiment-time toggle.

3. **Install** into `game/scripts/App.py`:

   ```
   uv run python tools/setup.py            # normal: uses cached .pyc
   uv run python tools/setup.py --recompile  # first run after a snippet edit
   uv run python tools/setup.py --capture    # cache the new .pyc after --recompile
   ```

4. **Launch BC, load Quick Battle as Galaxy.** Bring the ship to a
   complete halt facing an enemy at modest range. Set **RED alert**
   (this powers the phasers on so charge dynamics happen). Do NOT lock
   a target yet.

5. **Sit idle for 30 seconds.** This baseline captures the recharge
   curve (charge should be at `MaxCharge`, plateauing — confirms the
   recharge cap). Useful for Q-C2 sanity even before firing.

6. **Lock a target and fire.** Press **Tab** to acquire, then **hold
   LBUTTON for 10 full seconds**. Don't release until the bank
   visually stops firing. This captures:
   - The full discharge curve from `MaxCharge` to auto-stop (Q-C1).
   - The exact `charge_level` at which `IsFiring` flips to 0 (Q-C4).
   - The `CanFire` flag during depletion (Q-C3).

7. **Release LBUTTON** and **wait 30 seconds without firing.** Captures
   the recharge ramp (Q-C2) and pins down when `CanFire` flips back to
   1 (related to Q-C5).

8. **Press LBUTTON again momentarily** — *one click* — to see whether
   the bank fires immediately on the first non-zero recharge or has to
   wait for a higher threshold (Q-C5). Repeat 4-5 times with brief
   pauses between clicks, recharging a little each time.

9. **(Optional, for Q-C6)** Change weapons power level (Engineering
   redistribution, if QuickBattle exposes it) or drop to yellow alert.
   Repeat the discharge step. If we can't toggle these in QuickBattle,
   skip — the cfg captures the static `power_level` and `alert` values
   anyway, so any natural variation in the data is informative.

10. **Quit BC.**

11. **Send `game/BCChargeLog.cfg` back** to the macOS dev box. The cfg
    accumulates a 60-second trailing window of samples, so 30s idle +
    10s fire + 30s recharge + 5 clicks fits easily in `_MAX_SAMPLES`
    (10-min budget at 1 Hz, with ~10 Hz sampling that's a 60-sec window).

12. **Analyze on macOS** with a one-off script (no need to commit; can
    be inline `uv run python -c`). Pseudocode:

    ```python
    # Parse [BCChargeLog] section out of game/BCChargeLog.cfg.
    # Read the column legend, then each s0, s1, s2... row.
    # Build a time series: (game_t, charge, firing, can_fire).
    #
    # Q-C1: Find the firing windows (firing transitions 0→1 then 1→0).
    #       Within each, fit charge(t) = charge_0 - rate * (t - t_0).
    #       The slope IS the per-second discharge rate.
    # Q-C2: Find idle windows where charge < MaxCharge and not firing.
    #       Slope of charge(t) IS the per-second recharge rate.
    # Q-C3: At the moment can_fire flips 0→1 during recharge, what's
    #       the charge_level? Compare with SDK MinFiringCharge=3.0.
    # Q-C4: At the moment firing flips 1→0 mid-burst, what's the
    #       charge_level? Compare with SDK MinFiringCharge=3.0 and 0.0.
    # Q-C5: After auto-stop, when the player clicks again (firing
    #       transitions 0→1), what was the charge_level at click-time?
    # Q-C6: Did power_level or alert change during the run? Compare
    #       discharge slopes across windows where they differ.
    ```

13. **Update this doc.** Move Status to **DONE**, fill in Findings,
    paste the analyzer output. Commit.

## Expected output

`BCChargeLog.cfg` is a full engine config dump with a `[BCChargeLog]`
section appended. A successful capture looks like:

```
[BCChargeLog]
n_samples=600
columns=wall game_t frame charge firing can_fire power_level alert is_on
first_sample=1731.0000 0.1500 9 5.000000 0 1 1 2 1
last_sample=1731.9990 60.0000 3600 4.870000 0 1 1 2 1
s0=1731.0000 0.1500 9 5.000000 0 1 1 2 1
s1=1731.1000 0.3000 18 5.000000 0 1 1 2 1
...
s120=1742.0000 12.0000 720 4.900000 1 1 1 2 1   ← fire pressed
s121=1742.1000 12.1500 729 4.800000 1 1 1 2 1   ← discharging
s122=1742.2000 12.3000 738 4.700000 1 1 1 2 1
...
s220=1751.0000 22.0000 1320 2.95     0 0 1 2 1  ← auto-stop here
...
s420=1771.0000 42.0000 2520 3.10     0 1 1 2 1  ← recharged past threshold
```

(Numbers above are illustrative — the actual rates ARE what the
experiment reveals.)

## Cleanup

After the experiment is done — **always** run these, even if BC
crashed mid-experiment:

1. **Uninstall the snippet from `game/scripts/`:**

   ```
   uv run python tools/uninstall.py
   ```

2. **Revert the `tools/setup.py` edit** from step 2 of *How to run*:

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "charge_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   ```

3. **Leave `tools/charge_logger.py` in place** for future re-runs.

## Findings

*(Pending the Windows session — fill in once the cfg is captured.)*

- **Q-C1** — Per-second discharge rate: _TBD_ (SDK declares 1.0)
- **Q-C2** — Per-second recharge rate: _TBD_ (SDK declares 0.08)
- **Q-C3** — CanFire threshold: _TBD_ (SDK declares MinFiringCharge=3.0)
- **Q-C4** — Auto-stop threshold while firing: _TBD_
- **Q-C5** — Restart-after-depletion threshold: _TBD_
- **Q-C6** — Rate dependence on power_level / alert: _TBD_

Once filled in, retune `_EnergyWeaponFireMixin.UpdateCharge` to match
BC's actual semantics and drop the assumed-per-second interpretation.
