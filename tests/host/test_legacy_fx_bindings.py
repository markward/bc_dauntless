"""New particle/shockwave dict keys cross the binding (spec 2026-10-16 §7.4/§7.5)."""
import os


def test_particle_and_shockwave_keys_accepted():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    h.init(64, 64, "legacy-fx")
    try:
        h.set_particle_emitters([{
            "instance_id": None, "emit_pos": (0.0, 0.0, 0.0), "emit_dir": (0.0, 1.0, 0.0),
            "emit_vel_world": (0.0, 0.0, 0.0), "inherit": 0.0, "emit_velocity": 0.0,
            "angle_variance": 0.0, "emit_life": 1.0, "emit_life_variance": 0.0,
            "emit_frequency": 0.5, "effect_age": 0.1, "stop_age": 1.0, "draw_old_to_new": 1,
            "color_keys": [(0.0, 1.0, 1.0, 1.0)], "alpha_keys": [(0.0, 1.0)],
            "size_keys": [(0.0, 1.0)], "texture_path": "", "seed": 0.5,
            "playback": 2, "fps": 8.0, "pivot": (0.0, -1.0), "orient": 1, "roll_rate": 2.0,
        }])
        h.set_shockwaves([{"world_center": (0.0, 0.0, 0.0), "max_radius": 5.0,
                           "age": 0.1, "lifetime": 1.0, "tint": (0.2, 0.5, 1.0)}])
        h.frame()
    finally:
        h.set_particle_emitters([])
        h.set_shockwaves([])
        h.shutdown()
