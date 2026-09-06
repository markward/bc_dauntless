"""Live DOF tuning under --developer.

The point of these keys is that a visual constant gets calibrated in ONE
session: nudge in flight, read the values off stderr, and they become the
defaults in engine/cameras/dof.py. Without them each candidate value costs a
rebuild and a relaunch.

They are aimed at MAX_RADIUS_FRAC and FAR_CEILING, not at the strengths. The
far field is ceiling-bound, not strength-bound -- with FAR_CEILING = 0.4, a
background object at 10x the focus distance has dd = 0.9, so FAR_STRENGTH must
drop below 0.44 before the ceiling stops clipping it. Strength keys would have
been six presses of nothing in one direction and nothing at all in the other.
"""
import engine.dev_mode as dev_mode
import engine.dev_keybindings as dev_keybindings
from engine.cameras import dof
from engine.cameras.dof import (
    FAR_CEILING_MAX, FAR_CEILING_MIN, FAR_CEILING_STEP,
    FocusSolver,
    MAX_RADIUS_FRAC_MAX, MAX_RADIUS_FRAC_MIN, MAX_RADIUS_FRAC_STEP,
    STRENGTH_MAX, STRENGTH_MIN,
)


class _FakeKeys:
    """Hands back a distinct int for any KEY_* name asked of it.

    NOTE: this double answers every name, so it can never catch a constant the
    real _dauntless_host.keys does not export -- that is
    tests/unit/test_host_key_manifest.py's job, and it exists because exactly
    that gap shipped a process-killing dead key past a green suite.
    """

    def __init__(self):
        self._codes = {}

    def __getattr__(self, name):
        return self._codes.setdefault(name, len(self._codes) + 1)


class _FakeHost:
    def __init__(self):
        self.keys = _FakeKeys()


def _register(monkeypatch):
    seen = {}

    def _capture(key, handler, description):
        seen[key] = (handler, description)

    monkeypatch.setattr(dev_mode, "register_dev_keybinding", _capture)
    fake = _FakeHost()
    # register_for_frame tolerates a None session/player -- every handler that
    # needs them checks first.
    dev_keybindings.register_for_frame(fake, None, None)
    return fake, seen


# ── which keys, and what they point at ───────────────────────────────────

def test_all_four_tuning_keys_are_registered(monkeypatch):
    fake, seen = _register(monkeypatch)
    for attr in ("KEY_COMMA", "KEY_PERIOD", "KEY_SEMICOLON", "KEY_APOSTROPHE"):
        assert getattr(fake.keys, attr) in seen, attr


def test_comma_and_period_move_the_blur_magnitude(monkeypatch):
    """The overall "don't over-blur" control, not the strengths."""
    fake, seen = _register(monkeypatch)
    import engine.host_loop as host_loop
    solver = FocusSolver()
    monkeypatch.setattr(host_loop, "_focus_solver", solver, raising=False)

    before = solver.max_radius_frac
    seen[fake.keys.KEY_PERIOD][0]()
    assert solver.max_radius_frac == before + MAX_RADIUS_FRAC_STEP
    seen[fake.keys.KEY_COMMA][0]()
    assert abs(solver.max_radius_frac - before) < 1e-12
    # and the strengths are untouched by these keys
    assert solver.near_strength == dof.NEAR_STRENGTH
    assert solver.far_strength == dof.FAR_STRENGTH


def test_semicolon_and_apostrophe_move_the_far_ceiling(monkeypatch):
    """The background-mush control -- the value the design is least sure of."""
    fake, seen = _register(monkeypatch)
    import engine.host_loop as host_loop
    solver = FocusSolver()
    monkeypatch.setattr(host_loop, "_focus_solver", solver, raising=False)

    before = solver.far_ceiling
    seen[fake.keys.KEY_APOSTROPHE][0]()
    assert solver.far_ceiling == before + FAR_CEILING_STEP
    seen[fake.keys.KEY_SEMICOLON][0]()
    assert abs(solver.far_ceiling - before) < 1e-12


def test_a_press_prints_all_four_lens_values(monkeypatch, capsys):
    """One line must carry the whole state: printing only the knob that moved
    makes the developer reconstruct the rest from memory across a session."""
    fake, seen = _register(monkeypatch)
    import engine.host_loop as host_loop
    monkeypatch.setattr(host_loop, "_focus_solver", FocusSolver(), raising=False)

    seen[fake.keys.KEY_PERIOD][0]()
    err = capsys.readouterr().err
    for knob in ("max_radius_frac", "far_ceiling",
                 "near_strength", "far_strength"):
        assert knob in err, err


def test_every_handler_survives_no_host_loop_solver(monkeypatch):
    """The handler resolves host_loop._focus_solver lazily. If the loop has
    not started, pressing the key must be a no-op rather than an exception
    that kills the input dispatch."""
    fake, seen = _register(monkeypatch)
    import engine.host_loop as host_loop
    monkeypatch.setattr(host_loop, "_focus_solver", None, raising=False)
    for attr in ("KEY_COMMA", "KEY_PERIOD", "KEY_SEMICOLON", "KEY_APOSTROPHE"):
        seen[getattr(fake.keys, attr)][0]()   # must not raise


def test_the_tuning_keys_are_unbound_in_the_player_input_map():
    """A dev key that shadows a bound action would be a live gameplay bug."""
    from engine import input_map
    bound = {default for _id, _label, _cat, default in input_map.ACTIONS}
    for name in (",", ".", ";", "'"):
        assert name not in bound, "%r is bound to a player action" % name


# ── the nudges themselves ────────────────────────────────────────────────

def test_a_radius_step_is_a_visible_fraction_of_the_default():
    """A step too small to see is why the strength keys felt broken. At 1080p
    the default is a 8.6 px radius and the step is ~2.2 px."""
    assert MAX_RADIUS_FRAC_STEP >= 0.2 * dof.MAX_RADIUS_FRAC


def test_a_ceiling_step_crosses_the_useful_range_in_a_handful_of_presses():
    assert (FAR_CEILING_MAX - FAR_CEILING_MIN) / FAR_CEILING_STEP <= 25


def test_nudging_up_then_down_returns_to_the_start():
    s = FocusSolver()
    start = s.near_strength
    s.nudge_strength(0.1)
    s.nudge_strength(-0.1)
    assert abs(s.near_strength - start) < 1e-9


def test_nudge_saturates_rather_than_running_away():
    s = FocusSolver()
    for _ in range(200):
        s.nudge_strength(0.1)
    assert s.near_strength == STRENGTH_MAX
    for _ in range(200):
        s.nudge_strength(-0.1)
    assert s.near_strength == STRENGTH_MIN


def test_radius_nudge_clamps_at_both_ends():
    s = FocusSolver()
    for _ in range(200):
        s.nudge_max_radius_frac(MAX_RADIUS_FRAC_STEP)
    assert s.max_radius_frac == MAX_RADIUS_FRAC_MAX
    for _ in range(200):
        s.nudge_max_radius_frac(-MAX_RADIUS_FRAC_STEP)
    assert s.max_radius_frac == MAX_RADIUS_FRAC_MIN


def test_far_ceiling_nudge_clamps_at_both_ends():
    s = FocusSolver()
    for _ in range(200):
        s.nudge_far_ceiling(FAR_CEILING_STEP)
    assert s.far_ceiling == FAR_CEILING_MAX
    for _ in range(200):
        s.nudge_far_ceiling(-FAR_CEILING_STEP)
    assert s.far_ceiling == FAR_CEILING_MIN


def test_nudges_never_write_back_to_the_module_constants():
    s = FocusSolver()
    s.nudge_max_radius_frac(MAX_RADIUS_FRAC_STEP)
    s.nudge_far_ceiling(FAR_CEILING_STEP)
    assert dof.MAX_RADIUS_FRAC == 0.008
    assert dof.FAR_CEILING == 0.4
