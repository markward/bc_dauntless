import pytest

import engine.dev_mode as dev_mode
from engine import dev_nebula_dials as D


@pytest.fixture(autouse=True)
def _isolate_registry_and_dial_state():
    """Snapshot/restore the shared dev-keybinding registry (test_dev_keybindings.py's
    pattern) AND dev_nebula_dials' own live `_dials` state, so a press in one
    test can't leak into another."""
    saved_registry = dict(dev_mode._dev_keybindings)
    saved_dials = dict(D._dials)
    saved_selected = D._selected
    yield
    dev_mode._dev_keybindings.clear()
    dev_mode._dev_keybindings.update(saved_registry)
    D._dials = saved_dials
    D._selected = saved_selected


class _Keys:
    KEY_SLASH, KEY_L, KEY_O = 1, 2, 3


class _FakeHost:
    keys = _Keys()


def _press(key):
    handler, _desc = dev_mode._dev_keybindings[key]
    handler()


def test_register_binds_exactly_the_three_macbook_keys():
    """A MacBook has no numpad and no Pause; only /, L and O are free in
    every namespace (see the module docstring), so the five dials share
    them: / selects the dial, L steps it down, O steps it up."""
    dev_mode._dev_keybindings.clear()
    D.register(_FakeHost())
    assert sorted(dev_mode._dev_keybindings) == [1, 2, 3]


def test_slash_cycles_the_selected_dial_through_all_six(capsys):
    D.register(_FakeHost())
    D._selected = 0
    seen = [D.selected()]
    for _ in range(len(D.DIAL_ORDER)):
        _press(_Keys.KEY_SLASH)
        seen.append(D.selected())
    assert seen[0] == "veil", "veil is the first thing Mark tunes (spec)"
    assert sorted(set(seen)) == sorted(
        ["veil", "floor", "g", "lane_contrast", "near_range", "conceal_cap"])
    assert seen[-1] == seen[0], "cycling wraps"
    assert "[nebula dials]" in capsys.readouterr().out


def test_l_and_o_step_the_selected_dial_and_push_the_native_dials(monkeypatch, capsys):
    pushed = []
    import engine.renderer as r
    monkeypatch.setattr(r, "system_nebula_set_dials", lambda d: pushed.append(dict(d)))
    D._dials = dict(D.DEFAULTS)
    D.register(_FakeHost())
    D._selected = D.DIAL_ORDER.index("g")

    _press(_Keys.KEY_O)   # g +0.05
    assert pushed[-1]["g"] == pytest.approx(0.65)
    # the whole NATIVE dial set travels; veil and conceal_cap are Python-side
    assert set(pushed[-1]) == set(D.DEFAULTS) - {"veil", "conceal_cap"}
    _press(_Keys.KEY_L)
    assert pushed[-1]["g"] == pytest.approx(0.6)
    assert "[nebula dials]" in capsys.readouterr().out


def test_veil_steps_multiplicatively_and_stays_a_transmittance():
    d = D.step(dict(D.DEFAULTS), "veil", +1)
    assert d["veil"] == pytest.approx(0.15 * 1.25)
    d = D.step(dict(D.DEFAULTS), "veil", -1)
    assert d["veil"] == pytest.approx(0.15 / 1.25)
    for _ in range(40):
        d = D.step(d, "veil", +1)
    assert d["veil"] <= 0.99   # k_sys = -ln(veil)/I needs 0 < veil < 1


def test_step_functions_clamp_and_scale():
    d = dict(D.DEFAULTS)
    d = D.step(d, "g", +1)
    assert abs(d["g"] - 0.65) < 1e-9
    for _ in range(40):
        d = D.step(d, "g", +1)
    assert d["g"] <= 0.95
    d = D.step(dict(D.DEFAULTS), "floor", -1)
    assert abs(d["floor"] - 0.0916 / 1.25) < 1e-9


def test_defaults_match_the_spec():
    # floor 0.0916: Mark's live pick, 2026-09-29 (0.03 read too dark).
    assert D.DEFAULTS == {"veil": 0.15, "floor": 0.0916, "g": 0.6,
                          "lane_contrast": 0.7, "lane_size": 15000.0,
                          "near_range": 30000.0, "conceal_cap": 0.27}
    from engine.systems import profile as P
    assert D.DEFAULTS["veil"] == P.VEIL_DEFAULT


# ── Concealment cap dial (Mark 2026-09-29: make it debuggable like the floor) ─

def test_conceal_cap_default_is_the_sensor_constant():
    from engine.appc import sensor_detection as sd
    assert D.DEFAULTS["conceal_cap"] == pytest.approx(sd.PROFILE_CONCEALMENT_CAP)


def test_conceal_cap_steps_by_a_hundredth_and_stays_below_lock_break():
    from engine.appc import sensor_detection as sd
    d = D.step(dict(D.DEFAULTS), "conceal_cap", -1)
    assert d["conceal_cap"] == pytest.approx(0.26)
    for _ in range(10):
        d = D.step(d, "conceal_cap", +1)
    assert d["conceal_cap"] < sd.LOCK_BREAK_T
    for _ in range(100):
        d = D.step(d, "conceal_cap", -1)
    assert d["conceal_cap"] == 0.0


def test_conceal_cap_is_in_the_cycle_and_not_sent_native():
    assert "conceal_cap" in D.DIAL_ORDER
    assert "conceal_cap" not in D._native(dict(D.DEFAULTS))
