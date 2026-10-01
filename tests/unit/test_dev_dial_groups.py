"""One owner for the dev dial keys / L O (minor-rocks spec §5, M4)."""
import pytest

import engine.dev_dial_groups as g


@pytest.fixture(autouse=True)
def _fresh():
    g.reset()
    yield
    g.reset()


def _group(name, order, log):
    vals = {k: 1.0 for k in order}
    def step(dial, direction):
        vals[dial] += direction
        log.append((name, dial, direction))
    g.register_group(name, order, lambda: dict(vals), step)
    return vals


def test_first_registered_group_is_active():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    assert g.groups() == ("nebula", "minors")
    assert g.active() == "nebula"


def test_slash_cycles_dials_within_the_active_group_only():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    assert g.selected() == "veil"
    g.cycle_dial()
    assert g.selected() == "g"
    g.cycle_dial()
    assert g.selected() == "veil"


def test_push_steps_the_selected_dial_of_the_active_group():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer", "halo_inner"), log)
    g.cycle_active()
    assert g.active() == "minors"
    g.cycle_dial()
    g.push(+1)
    assert log == [("minors", "halo_inner", 1)]


def test_cycle_active_wraps_and_keeps_each_groups_selection():
    log = []
    _group("nebula", ("veil", "g"), log)
    _group("minors", ("halo_outer",), log)
    g.cycle_dial()                     # nebula -> g
    g.cycle_active()                   # minors
    g.cycle_active()                   # back to nebula
    assert g.active() == "nebula" and g.selected() == "g"


def test_reregistering_a_group_replaces_it():
    log = []
    _group("nebula", ("veil",), log)
    _group("nebula", ("veil", "g"), log)
    assert g.groups() == ("nebula",)


def test_register_keys_claims_exactly_slash_l_o(monkeypatch):
    import engine.dev_mode as dev_mode
    claimed = []
    monkeypatch.setattr(dev_mode, "register_dev_keybinding",
                        lambda key, fn, desc: claimed.append(key))
    class _Keys:
        KEY_SLASH, KEY_L, KEY_O = 1, 2, 3
    class _H:
        keys = _Keys
    g.register_keys(_H)
    assert sorted(claimed) == [1, 2, 3]
