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
    yield
    dev_mode._dev_keybindings.clear()
    dev_mode._dev_keybindings.update(saved_registry)
    D._dials = saved_dials


class _Keys:
    KEY_J, KEY_L = 1, 2
    KEY_N, KEY_M = 3, 4
    KEY_U, KEY_O = 5, 6
    KEY_B, KEY_P = 7, 8


class _FakeHost:
    keys = _Keys()


def test_register_binds_eight_distinct_keys():
    D.register(_FakeHost())
    registered = [k for k in dev_mode._dev_keybindings
                 if k in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert sorted(registered) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_pressing_a_key_pushes_the_whole_dict_and_prints(monkeypatch, capsys):
    pushed = []
    import engine.renderer as r
    monkeypatch.setattr(r, "system_nebula_set_dials", lambda d: pushed.append(dict(d)))
    D._dials = dict(D.DEFAULTS)
    D.register(_FakeHost())

    handler, _desc = dev_mode._dev_keybindings[_Keys.KEY_M]   # g +0.05
    handler()

    assert len(pushed) == 1
    assert pushed[0]["g"] == pytest.approx(0.65)
    # the WHOLE dict travels, not just the changed key
    assert set(pushed[0]) == set(D.DEFAULTS)
    out = capsys.readouterr().out
    assert "[nebula dials]" in out


def test_step_functions_clamp_and_scale():
    d = dict(D.DEFAULTS)
    d = D.step(d, "g", +1)
    assert abs(d["g"] - 0.65) < 1e-9
    for _ in range(40):
        d = D.step(d, "g", +1)
    assert d["g"] <= 0.95
    d = D.step(dict(D.DEFAULTS), "floor", -1)
    assert abs(d["floor"] - 0.03 / 1.25) < 1e-9


def test_defaults_match_the_spec():
    assert D.DEFAULTS == {"floor": 0.03, "g": 0.6, "lane_contrast": 0.7,
                          "lane_size": 15000.0, "near_range": 30000.0}
