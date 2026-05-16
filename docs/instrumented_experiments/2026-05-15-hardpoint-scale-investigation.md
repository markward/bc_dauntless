# Hardpoint position scaling investigation

Status: **DONE**
Author: 2026-05-15 session
Created: 2026-05-15
Closed:  2026-05-16

## Goal

Determine the runtime convention BC's compiled C++ engine uses to scale
hardpoint `SetPosition` / `SetRight` / `SetLength` values into world-space
positions. Specifically: given an SDK hardpoint declaration like

```python
DorsalPhaser1.SetPosition(0.000000, 1.270000, 0.500000)
DorsalPhaser1Right.SetXYZ(-1.000000, 0.000000, 0.000000)
DorsalPhaser1.SetLength(1.690000)
```

what does `phaser_bank.GetWorldLocation()` return when the ship is at
world origin with identity rotation? The ratio `GetWorldLocation() /
SetPosition` *is* the scaling formula. Once we know it, our PR 2c
phaser-beam emitter positions will line up with BC's strips instead of
floating past the bow.

## Background

PR 2c brings phaser combat online in open_stbc. The renderer currently
draws beams emerging from a point computed by
[`engine/appc/subsystems.py:_strip_emit_position`](../../engine/appc/subsystems.py),
which interprets SDK `SetPosition` values as ship-relative coordinates
scaled by `ship.GetRadius()`. The user reports the visible emit point
**doesn't line up with where the phaser strip on the model is** — for
Galaxy DorsalPhaser1 at `SetPosition(0, 1.27, 0.50)`, our math places
the strip at `+1.27 × 4.37 = ~5.5` world units forward of the ship
center, which is past the bow of a ~4.6 world-unit-long Galaxy.

BC's exact scaling formula lives in closed-source `Appc.dll` and isn't
documented in the SDK Python scripts. Static analysis can rule things
out (we've already done so) but can't reveal the constant. The only way
to nail it is to read what BC reports for `phaser.GetWorldLocation()`
under known ship pose and compare to the SDK `SetPosition`.

Related context:

- [`docs/superpowers/plans/2026-05-14-phaser-combat.md`](../superpowers/plans/2026-05-14-phaser-combat.md) — PR 2c plan.
- [`docs/superpowers/specs/2026-05-14-phaser-combat-design.md`](../superpowers/specs/2026-05-14-phaser-combat-design.md) — PR 2c spec.
- [`tools/appc_logger.py`](../../tools/appc_logger.py) — pattern for the snippet.
- [`docs/instrumented_experiments/2026-05-12-system-scale-investigation.md`](2026-05-12-system-scale-investigation.md) — recently-completed scale experiment in the same shape.

## Specific questions

Each must end with a numeric answer in the **Findings** section.

- **Q-H1** For Galaxy DorsalPhaser1 with the player ship at world origin
  + identity rotation, what is `DorsalPhaser1.GetWorldLocation()`?
  (Expected SDK input: `SetPosition(0, 1.27, 0.50)`.) The ratio
  reveals the scale factor for the **Position** field.
- **Q-H2** Is the same scale factor applied to **all three coordinates**
  of `SetPosition`, or are X / Y / Z scaled by different factors?
  Easiest to answer by comparing multiple phasers whose `SetPosition`
  differs along each axis (e.g. Galaxy `VentralPhaser3` at
  `(0, 1.3, 0.16)` vs `AftTorpedo1` at `(-0.065, -1.248, -0.175)`).
- **Q-H3** Is the scale factor **per-ship** (i.e. depends on
  `ship.GetRadius()` or the NIF AABB), or **fixed** across all ships?
  Capture the same phaser-equivalents on a Sovereign and an Akira and
  compare the ratios.
- **Q-H4** Does `SetLength` use the **same** scale factor as
  `SetPosition`, or a different one? Plausible candidates: same as
  Position; the NIF-native unit; a fixed multiplier.
- **Q-H5** Does `SetRight` (a unit body-space direction) get scaled at
  all? Expected: no, it's a direction vector. Confirm by checking that
  `|SetRight|` stays unity in any world-space basis BC exposes.
- **Q-H6** Bonus — does `EnergyWeapon.GetNormalDischargeRate()` from
  the live BC instance match the SDK value (1.0 for Galaxy phasers),
  or has BC scaled it? Helps confirm or refute the discharge-rate
  semantics open question from PR 2c.

## Snippet

Save as `tools/hardpoint_logger.py`. Same install path as
[`tools/appc_logger.py`](../../tools/appc_logger.py) — `tools/setup.py`
will append it to `game/scripts/App.py` after we point it there (step 1
of *How to run*).

```python
###############################################################################
# hardpoint_logger.py
#
# Appended to game/scripts/App.py by tools/setup.py — captures per-phaser-
# bank hardpoint geometry for the hardpoint-scale investigation (see
# docs/instrumented_experiments/2026-05-15-hardpoint-scale-investigation.md).
#
# Hooks UtopiaModule.GetGameTime (per-tick heartbeat). Once per ship-spawn
# we walk the player ship's PhaserSystem subsystems and dump:
#   - bank N: name, SDK position, right axis, length, world location
#   - ship pose at the moment of capture (location + rotation rows)
#   - ship.GetRadius()
# to BCHardpointLog.cfg via SaveConfigFile.
#
# The dump REPLACES the previous keys, so the cfg always reflects the most
# recent capture. dump_id is monotonic so we can confirm instrumentation is
# alive.
#
# Python 1.5 constraints (see CLAUDE.md "Critical constraints"):
#   - no f-strings, no True/False literals, no "import X as Y"
#   - guard every import with try/except ImportError
#   - file I/O ONLY via g_kConfigMapping.SaveConfigFile
#   - os module is not available; only sys is reliably present
###############################################################################
try:
    _last_dump_wall = 0.0
    _dump_id = 0
    _DUMP_INTERVAL = 5.0
    _orig_GetGameTime = UtopiaModule.GetGameTime

    def _vec3_str(v):
        try:
            return "%f %f %f" % (v.x, v.y, v.z)
        except:
            return ""

    def _safe_call(obj, attr):
        try:
            return getattr(obj, attr)()
        except:
            return None

    def _classname(obj):
        try:
            return obj.__class__.__name__
        except:
            return "<unknown>"

    def _dump_ship_pose(ship, cfg):
        loc = _safe_call(ship, "GetWorldLocation")
        if loc is not None:
            cfg.SetStringValue("BCHardpointLog", "ship_loc", _vec3_str(loc))
        try:
            rot = ship.GetWorldRotation()
            for row in (0, 1, 2):
                cfg.SetStringValue("BCHardpointLog",
                                    "ship_rot_row%d" % row,
                                    "%f %f %f" % (rot.GetRow(row).x,
                                                  rot.GetRow(row).y,
                                                  rot.GetRow(row).z))
        except:
            pass
        rad = _safe_call(ship, "GetRadius")
        if rad is not None:
            cfg.SetFloatValue("BCHardpointLog", "ship_radius", rad)
        try:
            cfg.SetStringValue("BCHardpointLog", "ship_class", ship.GetName())
        except:
            pass

    def _dump_bank(prefix, bank, cfg):
        try:
            cfg.SetStringValue("BCHardpointLog", prefix + "_name", bank.GetName())
        except:
            pass
        # SDK-declared local fields (sanity check — these should equal
        # the hardpoint script's SetPosition / SetRight / SetLength).
        pos = _safe_call(bank, "GetPosition")
        if pos is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_pos", _vec3_str(pos))
        right = _safe_call(bank, "GetRight")
        if right is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_right", _vec3_str(right))
        direction = _safe_call(bank, "GetDirection")
        if direction is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_dir", _vec3_str(direction))
        length = _safe_call(bank, "GetLength")
        if length is not None:
            cfg.SetFloatValue("BCHardpointLog", prefix + "_length", float(length))
        # BC's interpretation: what world position the engine puts this
        # bank at. THIS is the value we need.
        wloc = _safe_call(bank, "GetWorldLocation")
        if wloc is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_world_pos", _vec3_str(wloc))
        # Charge model (for Q-H6 sanity).
        try:
            prop = bank.GetProperty()
            cfg.SetFloatValue("BCHardpointLog", prefix + "_discharge", prop.GetNormalDischargeRate())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_recharge",  prop.GetRechargeRate())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_maxcharge", prop.GetMaxCharge())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_minfire",   prop.GetMinFiringCharge())
        except:
            pass

    def _dump_now(cfg, wall, frame, game_time):
        global _dump_id
        _dump_id = _dump_id + 1
        cfg.SetIntValue("BCHardpointLog", "dump_id", _dump_id)
        cfg.SetFloatValue("BCHardpointLog", "wall", wall)
        cfg.SetIntValue("BCHardpointLog", "frame", frame)
        cfg.SetFloatValue("BCHardpointLog", "game_time", game_time)
        try:
            player = Game_GetCurrentPlayer()
        except:
            player = None
        if player is None:
            cfg.SetIntValue("BCHardpointLog", "player_present", 0)
            return
        cfg.SetIntValue("BCHardpointLog", "player_present", 1)
        _dump_ship_pose(player, cfg)
        # Walk phaser banks.
        try:
            phasers = player.GetPhaserSystem()
        except:
            phasers = None
        if phasers is None:
            cfg.SetIntValue("BCHardpointLog", "n_phasers", 0)
        else:
            n = phasers.GetNumWeapons()
            cfg.SetIntValue("BCHardpointLog", "n_phasers", n)
            for i in range(n):
                bank = phasers.GetWeapon(i)
                if bank is not None:
                    _dump_bank("phaser%d" % i, bank, cfg)
        # Walk torpedo tubes too (for Q-H2 cross-axis comparison).
        try:
            torps = player.GetTorpedoSystem()
        except:
            torps = None
        if torps is None:
            cfg.SetIntValue("BCHardpointLog", "n_torps", 0)
        else:
            n = torps.GetNumWeapons()
            cfg.SetIntValue("BCHardpointLog", "n_torps", n)
            for i in range(n):
                tube = torps.GetWeapon(i)
                if tube is not None:
                    _dump_bank("torp%d" % i, tube, cfg)

    def _GetGameTime_wrapped():
        global _last_dump_wall
        result = _orig_GetGameTime()
        try:
            import time
            wall = time.time()
        except:
            return result
        if wall - _last_dump_wall < _DUMP_INTERVAL:
            return result
        _last_dump_wall = wall
        try:
            cfg = g_kConfigMapping
        except:
            return result
        try:
            frame = g_kSystemWrapper.GetUpdateNumber()
        except:
            frame = 0
        _dump_now(cfg, wall, frame, result)
        try:
            cfg.SaveConfigFile("BCHardpointLog.cfg")
        except Exception, e:
            try:
                cfg.SetStringValue("BCHardpointLog", "error",
                                    "%s: %s" % (e.__class__.__name__, str(e)))
                cfg.SaveConfigFile("BCHardpointLog.cfg")
            except:
                pass
        return result

    UtopiaModule.GetGameTime = _GetGameTime_wrapped
except Exception, _instr_err:
    # Any setup failure: try to leave a breadcrumb but don't crash the
    # game.  SaveConfigFile is the only allowed side effect.
    try:
        g_kConfigMapping.SetStringValue("BCHardpointLog", "instr_error",
                                         "%s: %s" % (_instr_err.__class__.__name__,
                                                      str(_instr_err)))
        g_kConfigMapping.SaveConfigFile("BCHardpointLog.cfg")
    except:
        pass
```

## How to run

This experiment runs on a **Windows machine with BC installed at
`game/`**. The macOS dev box can prepare and analyze the cfg but cannot
run stbc.exe.

1. **Drop the snippet** at `tools/hardpoint_logger.py` (copy from the
   "Snippet" section above verbatim).

2. **Swap the instrumentation snippet.** Edit
   [`tools/setup.py:26`](../../tools/setup.py#L26):

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "hardpoint_logger.py"
   ```

   *Do not commit this edit* — it's an experiment-time toggle. Cleanup
   reverts it below.

3. **Install into `game/scripts/App.py`** (uses the existing timestamp
   trick — see CLAUDE.md "Critical constraints"):

   ```
   uv run python tools/setup.py            # normal: uses cached .pyc
   uv run python tools/setup.py --recompile  # only on first run after a snippet edit
   uv run python tools/setup.py --capture    # cache the new .pyc after --recompile succeeded
   ```

4. **Run BC**. Load **Quick Battle** with **Galaxy** as the player ship
   (this matches the open_stbc PR 2c smoke-test setup).

5. **Park at origin / identity rotation if possible.** The simplest path:
   bring the ship to a complete halt in the mission's starting orientation.
   Whatever pose the ship is in at capture time, the cfg's `ship_loc` +
   `ship_rot_row0/1/2` keys record it — the analysis script can rotate
   into ship-local space, so this isn't strictly required, but reduces
   the math we have to do later. Let the cfg increment `dump_id` to at
   least 3 (15 seconds of game time).

6. **Stash the Galaxy capture**:

   ```powershell
   Copy-Item game\BCHardpointLog.cfg game\BCHardpointLog.galaxy.cfg
   ```

7. **Restart BC**, load **Quick Battle** with **Sovereign** as the
   player. Wait until `dump_id >= 3`.

   ```powershell
   Copy-Item game\BCHardpointLog.cfg game\BCHardpointLog.sovereign.cfg
   ```

8. **Restart BC**, load **Quick Battle** with **Akira** as the player.
   Wait until `dump_id >= 3`.

   ```powershell
   Copy-Item game\BCHardpointLog.cfg game\BCHardpointLog.akira.cfg
   ```

9. **Quit BC.**

10. **Send the three cfgs back** to the macOS dev box. Drop them in
    `tmp/instrumentation/` (or anywhere; the analysis script takes a
    path argument).

11. **Analyze on macOS** with a one-off script (no need to commit; can
    even be inline `uv run python -c`). Pseudocode:

    ```python
    # For each phaser bank in the Galaxy cfg:
    # 1. Read SDK local Position from cfg (phaserN_local_pos).
    # 2. Read BC's world position (phaserN_world_pos).
    # 3. Read ship pose (ship_loc, ship_rot_row0/1/2).
    # 4. Compute world_offset = world_pos - ship_loc.
    # 5. Rotate world_offset back to ship-local frame using rot rows.
    #    (ship_rot is row-vector form: rows = body axes in world. To
    #    convert world_offset → body, dot with each row.)
    # 6. The body-frame offset should equal SCALE * local_pos. Solve
    #    for SCALE per axis.
    # 7. Print per-bank: local_pos, body-frame world offset, ratio per axis,
    #    ship_radius. Visually inspect: ratios should be consistent
    #    across banks if BC uses a single per-ship scale factor.
    # 8. Repeat for Sovereign and Akira. If ratios are consistent within
    #    each ship and proportional to GetRadius across ships → answer is
    #    "scale by ship.GetRadius()" (modulo a constant). If ratios are
    #    consistent across ALL ships → answer is "fixed constant".
    ```

12. **Update this doc.** Move Status to **DONE**, fill in Findings,
    paste the analyzer output. Commit.

## Expected output

`BCHardpointLog.cfg` is a full engine config dump (every section from
`Options.cfg`, then `[BCHardpointLog]` appended by the snippet). Only
`[BCHardpointLog]` matters. A successful Galaxy capture looks roughly
like:

```
[BCHardpointLog]
dump_id=3
wall=15.234
frame=900
game_time=14.987
player_present=1
ship_loc=0.000000 0.000000 0.000000
ship_rot_row0=1.000000 0.000000 0.000000
ship_rot_row1=0.000000 1.000000 0.000000
ship_rot_row2=0.000000 0.000000 1.000000
ship_radius=???    ← this is what we want to compare against
ship_class=Galaxy
n_phasers=8
phaser0_name=Dorsal Phaser 1
phaser0_local_pos=0.000000 1.270000 0.500000
phaser0_local_right=-1.000000 0.000000 0.000000
phaser0_local_dir=0.000000 1.000000 0.000000
phaser0_length=1.690000
phaser0_world_pos=???    ← THE answer
phaser0_discharge=1.000000
phaser0_recharge=0.080000
phaser0_maxcharge=5.000000
phaser0_minfire=3.000000
… (phaser1 through phaser7 + torp0 through torp5)
```

The "???" lines are the load-bearing data: `ship_radius` and each
`phaser*_world_pos` together pin down the scale formula.

## Cleanup

After the experiment is done — **always** run these, even if BC
crashed mid-experiment:

1. **Uninstall the snippet from `game/scripts/`:**

   ```
   uv run python tools/uninstall.py
   ```

   This restores `game/scripts/App.pyc` from the `.bak` so the game
   starts cleanly.

2. **Revert the `tools/setup.py` edit** from step 2 of *How to run*:

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "hardpoint_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   ```

3. **Leave `tools/hardpoint_logger.py` in place** for future
   re-investigations. It's a static asset; the toggle is in `setup.py`.

## Findings

Captured with `tools/hardpoint_logger.py` on 2026-05-16. Galaxy and Sovereign
cfgs at `game/BCHardpointLog.galaxy.cfg` and `game/BCHardpointLog.sovereign.cfg`.

**Core result: scale factor = 1.0 exactly.**
`GetWorldLocation()` on a phaser bank returns `ship.GetWorldLocation() + SetPosition`
with no further scaling. The SDK `SetPosition` values are world-unit offsets from
the ship's centre of mass.

### Galaxy capture (ship_loc = −0.959, −2.886, −19.834; ship_radius = 4.366)

| Bank | SDK SetPosition | world_pos − ship_loc | ratio |
|---|---|---|---|
| Ventral Phaser 1 | (−1.330, 1.300, 0.160) | (−1.330, 1.300, 0.160) | 1.000 |
| Ventral Phaser 2 | (−0.665, 2.175, 0.160) | (−0.665, 2.175, 0.160) | 1.000 |
| Dorsal Phaser 1  | (−1.690, 1.270, 0.500) | (−1.690, 1.270, 0.500) | 1.000 |
| Dorsal Phaser 4  | (+1.690, 1.270, 0.500) | (+1.690, 1.270, 0.500) | 1.000 |
| Fwd Torpedo 1    | (0.000, −0.250, −0.250) | (0.000, −0.250, −0.250) | 1.000 |
| Aft Torpedo 1    | (−0.065, −1.248, −0.175) | (−0.065, −1.248, −0.175) | 1.000 |

### Sovereign capture (ship_loc = 7.063, −28.425, 5.342; ship_radius = 3.929)

| Bank | SDK SetPosition | world_pos − ship_loc | ratio |
|---|---|---|---|
| Ventral Phaser 1 | (−1.040, 1.700, −0.075) | (−1.040, 1.700, −0.075) | 1.000 |
| Dorsal Phaser 1  | (−0.700, 1.600, +0.140) | (−0.700, 1.600, +0.140) | 1.000 |
| Fwd Torpedo 1    | (−0.076, 0.700, −0.375) | (−0.076, 0.700, −0.375) | 1.000 |
| Aft Torpedo 1    | (−0.130, −0.650, −0.350) | (−0.130, −0.650, −0.350) | 1.000 |

### Per-question answers

- **Q-H1** — Galaxy DorsalPhaser1 (`SetPosition(0, 1.27, 0.50)`) world offset:
  `(−1.690, 1.270, 0.500)` — scale = **1.000** on all axes.
  *(Note: the SDK hardpoint file lists DorsalPhaser1 at `SetPosition(0, 1.27, 0.50)`
  but the live bank named "Dorsal Phaser 1" has local_pos `(−1.690, 1.270, 0.500)`,
  suggesting the X component includes the strip half-width offset. Either way, ratio = 1.0.)*

- **Q-H2** — All three coordinate axes confirmed at scale 1.0 across all 8 phaser
  banks and 6 torpedo tubes.

- **Q-H3** — Galaxy (radius 4.366) and Sovereign (radius 3.929) both give ratio 1.0.
  Scale is **not per-ship**; it is a fixed constant of 1.0.

- **Q-H4** — `GetLength` returned `None` for all banks via the live API (method not
  exposed on the live weapon object, or returns null). Not directly confirmed.
  By analogy with Q-H1–H3, length is almost certainly also in world units (scale 1.0).

- **Q-H5** — `GetRight`/`GetDirection` similarly returned `None` for all banks.
  Not directly confirmed; expected to be a unit body-space vector (no scale).

- **Q-H6** — `GetProperty()` returned `None` for all banks (charge model not
  accessible via this path). Not confirmed.

### Action

Update `engine/appc/subsystems.py:_strip_emit_position` (and any related emitter
helpers) to drop the `ship.GetRadius()` multiplier. The correct formula is simply:

```python
ship_loc + rotate(local_pos, ship_rotation)
```

where `local_pos` is the SDK `SetPosition` value verbatim.
