# Nebula "sensor scale" is an accidental no-op (deferred — measure first)

**Logged:** 2026-09-28, while re-checking the radial system profile spec.
**Area:** `engine/appc/nebula_runtime.py:NebulaTracker._scale_sensor`

## What the code does

On entering a MetaNebula, a ship's base sensor range is multiplied by
`clamp(sensor_density, 0, 1)` and restored on exit. BC's campaign clouds author
`10.5` (Vesuvi 4) and `6.5` (Belaruz 1), so the factor is always `1.0` and
**sensor range never changes**. Only Multi5/Multi6 (`0.5`) do anything.

## Why it is not simply "fixed"

The clamp is ours, not BC's: it arrived in `f79a8b70` (2026-06-22,
"environmental damage + sensor-range scaling") with no evidence behind it. The
stbc-oracle bible §15 names the argument **"sensor scale"** and lists it
explicitly under *Not measured*. Nobody knows what `10.5` does in the original
engine, so any replacement formula would be as invented as the clamp.

Target concealment inside a nebula does work today — it comes from the fbm
density field (`sensor_detection.concealment_at`), not from this argument.

## What closes it

An stbc-oracle measurement: a Galaxy's effective sensor range (e.g. the range
at which a known target is lost / acquired) outside vs inside Vesuvi 4
(`10.5`), Belaruz 1 (`6.5`) and a Multi6-style cloud (`0.5`). Then replace
`_scale_sensor`'s formula with the measured one and pin it in
`tests/oracle/test_nebula.py`.

## Not affected

The radial system profile's `sensors` column acts through
`concealment_at`, not through this path, so it does not wait on this.
