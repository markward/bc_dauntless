"""Report-only bench: the idle space.shield / space.weapons scopes, and what
the frame profiler itself costs.

    uv run python tools/bench_idle_passes.py [frames] [width] [height] [load]

Reproduces the idle scene from the 2026-10-03 live capture -- ONE ship, its
shield registered and never hit, nothing firing -- in a headless host.
`load` extra hulls stacked in front of the camera put the GPU under fragment
pressure without adding anything to the shield or weapons inputs.

Prints (1) frame wall time with the profiler off vs on, and (2) the
profiler's per-scope CPU ms. Asserts nothing.

Reading it: a headless hidden window is not the live one (no vsync, no CEF),
so compare WITHIN a run. What this bench established (Debug, this Mac,
2026-10-03): the shield and weapons scopes cost ~0.015 ms each when idle --
the price of an empty scope -- and the profiler's own GL_TIMESTAMP queries,
which this driver answers with zeros, added +1.9 ms/frame idle and +6 ms/frame
under load, landing in whichever cheap scope issued them. The profiler now
never issues those on a 0-bit driver and times the top-level passes with
GL_TIME_ELAPSED instead; this bench is how that overhead is checked. See
docs/engine/frame-profiler.md.
"""
import os
import sys
import time

os.environ.setdefault("OPEN_STBC_HOST_HEADLESS", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.helpers import bc_assets  # noqa: E402

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = (bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures"
              / "FedShips" / "High")
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
WATCH = ("space.shield", "space.weapons", "space.hull_interior",
         "space.lens_flare", "space.opaque", "space.particles", "space.dust")


def _translated(x, y, z):
    return IDENTITY[:12] + [x, y, z, 1.0]


def _ms_per_frame(h, frames):
    t0 = time.perf_counter()
    for _ in range(frames):
        h.frame()
    return (time.perf_counter() - t0) * 1000.0 / frames


def main(frames=300, width=640, height=360, load=0):
    import _dauntless_host as h
    h.init(width, height, "bench_idle_passes")
    try:
        model = h.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        iid = h.create_instance(model)
        h.set_world_transform(iid, IDENTITY)
        for i in range(load):
            extra = h.create_instance(model)
            h.set_world_transform(extra, _translated(0.0, -1400.0 + i * 2.0, 0.0))
        cx, cy, cz, radius = h.get_instance_bounds(iid)
        # Ellipsoid mode (0), 1 s decay, never hit: the live idle state.
        h.shield_register(iid, 0, 1.0, (0.4, 0.6, 1.0, 1.0), (cx, cy, cz),
                          (radius * 0.5, radius, radius * 0.25))
        h.set_camera(eye=(0.0, -1500.0, 300.0), target=(0.0, 0.0, 0.0),
                     up=(0.0, 0.0, 1.0), fov_y_rad=1.0472, near=1.0,
                     far=100000.0)
        h.set_lighting((0.1, 0.1, 0.1), [])
        _ms_per_frame(h, 60)                       # warm

        print(f"{width}x{height}  load_hulls={load}  frames={frames}  "
              f"(one shielded Galaxy, unhit, nothing firing)")
        for rnd in range(3):
            h.profiler_set_enabled(False)
            off = _ms_per_frame(h, frames)
            h.profiler_set_enabled(True)
            _ms_per_frame(h, 40)                   # warm, enabled
            on = _ms_per_frame(h, frames)
            print(f"  round {rnd}: profiler off {off:7.3f}  on {on:7.3f} "
                  f"ms/frame  (+{on - off:.3f})")
        f = h.profiler_frame()
        print(f"  gpu timer: {f.get('gpu_timer', '?')} (counter bits: "
              f"timestamp {f.get('timestamp_bits', '?')}, time_elapsed "
              f"{f.get('elapsed_bits', '?')}); frame gpu {f['gpu_ms']:.3f} ms; "
              f"timestamp queries issued {f.get('timestamp_queries', '?')}")

        scopes = {s["name"]: s for s in h.profiler_scopes()}
        print(f"  {'scope':<24}{'cpu ms':>10}{'gpu ms':>10}{'calls':>7}")
        for name in ("frame", "space") + WATCH:
            s = scopes.get(name)
            if s is None:
                print(f"  {name:<24}{'absent':>10}")
                continue
            gpu = (f"{s['gpu_ms']:>10.4f}" if s.get("gpu_measured", True)
                   else f"{'-':>10}")
            print(f"  {name:<24}{s['cpu_ms']:>10.4f}{gpu}{s['calls']:>7}")
    finally:
        h.profiler_set_enabled(False)
        h.shutdown()


if __name__ == "__main__":
    main(*[int(a) for a in sys.argv[1:]])
